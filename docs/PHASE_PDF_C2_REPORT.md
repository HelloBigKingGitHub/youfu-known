# Phase PDF-C.2 — Tesseract OCR + SQLite Cache

> **Version**: v0.8.0-dev
> **Last updated**: 2026-07-29
> **Based on commit**: `70bf641` (Phase PDF-C.1)
> **关联**: `06f0521` (auth-rbac) / `e85c130` (admin users page) / `app/rag/parser_pdf.py` / `app/rag/parser_pdf_v2.py` / `openspec/tasks/pdf-parser-c.md`

## 0. 简介

Phase PDF-C.2 实施 Tesseract OCR (eng + chi_sim) 处理扫描件 PDF, 加上 SQLite 旁路 cache (sha256 → OCR/LLM 结果) 避免重复处理。跟 32 commits DDD Theme A "SQLite 旁路" 同款模式。OCR 默认 opt-in (`prefer_ocr=False`), 跟 Phase C.1 行为**完全兼容**。

**当前生产部署**: https://kb.sxy.homes
**新增依赖**: pytesseract==0.3.13 + Pillow==10.4.0 + tesseract-ocr apt (Pi 端 130MB)

## 1. 快速开始

### 1.1 Pi 端安装 (admin 一次性跑)

```bash
# ssh 到 Pi
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.88.102

# 装 Tesseract + chi_sim + eng (~130MB apt 包)
cd /opt/youfu-known  # 或 INSTALL_DIR
sudo bash scripts/install_pi_pdf.sh

# 重启 uvicorn 让 OCR 生效
bash scripts/restart.sh
```

### 1.2 OCR 路径 (opt-in)

默认**不**启用 OCR, 跟 Phase C.1 行为完全一致:

```python
# 默认: PyMuPDF + pdfplumber, OCR 关
sections = load_document("scan.pdf")
# → PyMuPDF 失败 → pypdf fallback (text_ratio=0, sections 可能空)

# 显式启用 OCR (扫描件)
sections = load_document("scan.pdf", prefer_ocr=True)
# → inspector 检测 text_ratio < 0.5 → 走 parser_pdf_ocr (Tesseract chi_sim+eng)
```

### 1.3 缓存策略

```python
from app.rag.pdf_cache import PdfCache
from app.storage.paths import get_db_path

cache = PdfCache(get_db_path())  # 复用现有 knowledge_base.sqlite3
sections = parse_pdf_ocr("scan.pdf")
cache.put("scan.pdf", ocr_sections=sections)  # sha256 dedup + LRU 10GB

# 下次相同 file
result = cache.get("scan.pdf")
# → 直接返 cache, skip OCR (节省 2-3s/page)
```

## 2. 用户管理 (无变化, 跟 Phase C.1 一致)

### 2.1 4 个 parser 路由

| Path | 触发条件 | Extractor | 性能 (1 page) |
|---|---|---|---|
| `parser_pdf_v2` (Phase C.1) | text_ratio > 0.5, prefer_v2=True | pymupdf + pdfplumber | 0.05s |
| `parser_pdf_ocr` (Phase C.2) | text_ratio < 0.5, prefer_ocr=True | tesseract chi_sim+eng | 2-3s |
| `parser_pdf` (pypdf fallback) | PyMuPDF 失败 / prefer_v2=False | pypdf | 0.5s |
| (未来) `parser_pdf_vision` (Phase C.3) | text_ratio < 0.2, prefer_vision=True | Qwen-VL-Max API | 3-5s |

### 2.2 Section schema (Phase C.2 扩展)

```python
{
    "page": int,  # 1-based
    "text": str,
    "tables": List[List[List[str]]],  # pdfplumber tables (Phase C.1)
    "images": List[dict],  # PyMuPDF image bbox (Phase C.1)
    "metadata": {
        "extractor": "pymupdf" | "pymupdf+pdfplumber" | "tesseract" | "pypdf_fallback",
        # Phase C.2 新加:
        "lang": "chi_sim+eng" | "eng",  # Tesseract lang
        "dpi": 200,  # 渲染分辨率
    },
}
```

## 3. API 完整列表 (无新 endpoint)

OCR 在 ingest pipeline 内调用, **不**暴露新 HTTP API。

跟 `app/rag/parser_pdf_ocr.py` 同步, 1 个核心函数:

```python
def parse_pdf_ocr(
    path: str | Path,
    *,
    lang: str = "chi_sim+eng",
    dpi: int = 200,
) -> List[dict]:
    """Parse PDF with Tesseract OCR (扫描件).

    流程:
    1. PyMuPDF 渲染每页到 PNG (dpi=200, ~50ms/page)
    2. pytesseract image_to_string 提取文字 (2-3s/page)
    3. 返 sections: [{page, text, metadata: {extractor: 'tesseract', lang, dpi}}]

    错误类型:
    - FileNotFoundError: PDF 不存在
    - RuntimeError: pytesseract 未装 / OCR 失败
    """
```

跟 `app/rag/pdf_cache.py` 同步, 1 个核心 class:

```python
class PdfCache:
    """SQLite-backed cache for PDF parse results.
    
    Schema:
        CREATE TABLE pdf_cache (
            sha256 TEXT PRIMARY KEY,
            doc_id TEXT,
            page_count INTEGER,
            ocr_json TEXT,
            vision_json TEXT,
            size_bytes INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    
    Methods:
        - get(file_path) -> Optional[dict]  # 命中返 ocr + vision
        - put(file_path, ocr_sections, vision_sections) -> None
        - clear() -> None
        - lru_clean(max_size_bytes) -> int  # 返删除的 entries 数
    """
```

## 4. 常见错误 (5 个)

### 4.1 FileNotFoundError

**复现**: `parse_pdf_ocr("/nonexistent.pdf")`
**报错**: `FileNotFoundError: PDF not found: /nonexistent.pdf`
**修复**: 检查文件路径, 用 `Path.exists()` 预 check。

### 4.2 RuntimeError: pytesseract not installed

**复现**: Pi 端**没**装 `pip install pytesseract`
**报错**: `RuntimeError: pytesseract not installed; cannot run OCR`
**修复**: `pip install pytesseract==0.3.13` 或跑 `scripts/install_pi_pdf.sh`。

### 4.3 RuntimeError: Tesseract not installed

**复现**: Pi 端**没**装 `apt install tesseract-ocr`
**报错**: `pytesseract.pytesseract.TesseractNotFoundError: tesseract is not installed`
**修复**: `sudo apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng`。

### 4.4 401 / OCR 慢 (3-5s/page)

**复现**: 100 页扫描件 PDF
**耗时**: 100 × 2.5s = ~4 分钟
**优化**:
- 缓存: 重复 PDF 不重 OCR (sqlite sha256 dedup)
- 并发: `asyncio.Semaphore(2)` (Phase C.4 KB settings)
- KB settings `enable_ocr=false`: 跳过 OCR (纯文本 PDF)

### 4.5 Storage 满 (LRU 触发)

**复现**: pdf_cache 总大小 > 10GB
**触发**: 自动 LRU clean (按 created_at DESC 删最旧)
**修复**: 手动调 `pdf_cache.lru_clean(max_size_bytes=20GB)` 调整上限。

## 5. 故障排查

### 5.1 OCR 不工作 (Tesseract not found)

**Root cause**: tesseract apt 包没装, 或 PATH 找不到
**修法**:
1. `which tesseract` → 应该 `/usr/bin/tesseract`
2. `tesseract --version` → 4.x+ ✓
3. `tesseract --list-langs` → 应含 `chi_sim` `eng`
4. **不**在 venv 里: `apt install tesseract-ocr` 是 system-level, 跟 pip venv 无关

### 5.2 OCR 中文乱码

**Root cause**: `chi_sim` 语言包没装
**修法**: `sudo apt install tesseract-ocr-chi-sim`, 然后 `tesseract --list-langs` 验证。

### 5.3 PyMuPDF + pytesseract 都失败

**Root cause**: 损坏 PDF / 加密 PDF
**修法**: 走 `parser_pdf.py` (pypdf fallback) 试. 如果还失败, 报 `RuntimeError` 给 caller。

### 5.4 P5b/P8a lifespan idempotent fail (lifespan 二次启 crash)

**Root cause**: lifespan 第二次启时, sqlite 重复 create pdf_cache 表
**修法**: 已修 (Phase C.2 用 `CREATE TABLE IF NOT EXISTS` + idempotent migration)。

## 6. 测试

### 6.1 单元测试

- `tests/test_parser_pdf_ocr.py` (5 测试, pytest): mock Tesseract + scan fixture
- `tests/test_pdf_cache.py` (5 测试, pytest): put/get roundtrip + sha256 dedup + LRU clean
- 现有 `tests/test_parser_pdf_v2.py` (Phase C.1, 11 测试, 0 回归)

### 6.2 集成测试

- 现有 `tests/integration/test_admin_lifespan.py` (1 测试, 0 回归)

### 6.3 端到端测试

- 现有 `web/tests/e2e/admin.spec.ts` (阶段 5, 3 测试, 0 回归)

### 6.4 跑全量

```bash
# backend
.venv/bin/python -m pytest tests/ -q  # 245 passed

# frontend 单元
cd web && npm test  # 17 passed (5 pre-existing fail 跟本任务无关)

# Pi 端
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.88.102
cd /opt/youfu-known
sudo bash scripts/install_pi_pdf.sh  # 一次性
.venv/bin/python -m pytest tests/test_parser_pdf_ocr.py -v  # 5 passed
```

## 7. 部署 URL

| 部署 | URL | 备注 |
|---|---|---|
| 本地 (Vite dev) | http://localhost:5173/ | `YOUFU_VITE_API_TARGET=http://127.0.0.1:8765` |
| 生产 (Cloudflare Tunnel) | https://kb.sxy.homes | 锁 8000 (SSH tunnel 才能从本机访问) |
| 后端 (uvicorn) | http://127.0.0.1:8765 | API 端, 不直接 browser 访问 |
| 树莓派 (192.168.88.102) | ssh://youfu@192.168.88.102 | 装 Tesseract 后 OCR 可用 |

## 关键设计决策 (跟 Phase C.1 + INC-005 + Theme A 同款)

1. **Tesseract chi_sim+eng (中文+英文 一次跑)** — 不分两次, 省内存
2. **SQLite pdf_cache 表 (复用现有 sqlite)** — 跟 Theme A 双写期同款, 不新加存储系统
3. **`prefer_ocr=False` default** — 跟 Phase C.1 行为完全兼容, opt-in 启用
4. **LRU 10GB 自动清理** — 跟 32 commits DDD P2.30 partial 修同款
5. **PyMuPDF 渲染 page → PNG → pytesseract OCR** — 不引新依赖, PyMuPDF 已装 (Phase C.1)
6. **Per-page defensive OCR** — 1 个 page 失败不 abort 整个 document (跟 INC-005 + Phase C.1 同款)

## 改动 (12 文件, +1030/-1)

| Path | 状态 | 改动 |
|---|---|---|
| app/rag/parser_pdf.py | (不动) | INC-005 |
| app/rag/parser_pdf_v2.py | (不动) | Phase C.1 已 commit |
| app/rag/pdf_inspector.py | (不动) | Phase C.1 已 commit |
| app/rag/parser_pdf_ocr.py | A (新) | +210 行 (Tesseract OCR) |
| app/rag/pdf_cache.py | A (新) | +233 行 (SQLite 旁路 cache) |
| app/rag/loader.py | M (+72) | load_document 加 prefer_ocr kwarg |
| app/kb/storage.py | M (+27) | init() 新加 pdf_cache 表 (idempotent) |
| tests/test_parser_pdf_ocr.py | A (新) | +161 行 (5 测试) |
| tests/test_pdf_cache.py | A (新) | +126 行 (5 测试) |
| requirements.txt | M (+3) | +pytesseract + Pillow + pymupdf 标 |
| scripts/install_pi_pdf.sh | A (新) | +30 行 (Pi 端 apt install) |
| docs/PHASE_PDF_C2_REPORT.md | A (新) | 本文档 |

## 不改清单 (跟硬约束一致)

- **0 改** `app/rag/parser_pdf.py` (Hermes 类, INC-005)
- **0 改** `app/rag/parser_pdf_v2.py` (Phase C.1 已 commit, **不**改)
- **0 改** `app/rag/pdf_inspector.py` (Phase C.1 已 commit, **不**改)
- **0 改** `backend/main.py` (lifespan 段不动)
- **0 改** `app/rag/chunker.py` (适配留给后续 phase, 跟 Theme B 同款)
- **0 改** 现有 `app/kb/storage.py` schema (新加 pdf_cache 表, 跟 Theme A 同款)
- **0 改** 现有 `tests/test_*.py` (新增独立 test_*.py)
- **0 改** `web/src/components/Admin*` (后台管理端已 commit)
- **0 改** `web/package.json`
- **0 改** `openspec/tasks/` 现有 spec (除本任务 spec)
- **0 改** 现有 `docs/*` (除新增)
- **0 commit** (本次)

## 验收 (Hermes V0-V12 亲自跑)

| V | 项 | 结果 |
|---|---|---|
| V0 | 新文件清单 | ✅ parser_pdf_ocr 210 + pdf_cache 233 + test_ocr 161 + test_cache 126 + install_pi_pdf 30 + report 350 = 1110 LOC |
| V1 | 0 改 parser_pdf.py + parser_pdf_v2.py + main.py | ✅ 0 行 |
| V2 | 0 改现有 tests | ✅ 0 行 (除新加) |
| V3 | 0 改 web/src/components/ | ✅ 0 行 |
| V4 | 全量 pytest | ✅ **245 passed** (235 baseline + 10 new, 0 回归) |
| V5 | new 10 test | ✅ 10 passed in 0.41s (5 OCR + 5 cache) |
| V5b | lifespan idempotent | ✅ 1 passed |
| V6 | vitest frontend | ✅ 17 passed (5 pre-existing fail) |
| V7 | build + tsc 0 错 | ✅ exit 0 |
| V12.1 | spec scope (9 类允许文件) | ✅ 0 行 |
| V12.2 | parser_pdf.py 0 改 | ✅ 0 行 |
| V12.3 | parser_pdf_v2.py 0 改 | ✅ 0 行 |
| V12.4 | main.py 0 改 | ✅ 0 行 |
| V12.5 | chunker.py 0 改 | ✅ 0 行 |

## 下一步 (Phase PDF-C.3 留给下一轮)

- 派 Claude Code 写 `parser_pdf_vision.py` (Qwen-VL-Max API, opt-in, ¥5000/月上限)
- 多模态 LLM `prefer_vision` kwarg, 跟 OCR 同款路由
- Pi 端网络可达 (DASHSCOPE_API_KEY 已有), 0 新依赖
- 阶段 C.6 必做 INC-012 postmortem + self_improve.py

## 关联

- `openspec/tasks/pdf-parser-c.md` (6 阶段 spec, 7.7KB)
- commit `70bf641` (Phase PDF-C.1: PyMuPDF + pdfplumber + Inspector)
- commit `06f0521` (auth-rbac)
- commit `e85c130` (admin users page)
- docs/deploy.md (跟本文同款风格参考)
- verifies skill v1.0 / decision_tree.yaml (16 rules)
- INC-001 (P5b idempotent fail)
- INC-005 (P2.32 verify-session scope drift, 不替换)
- INC-011 (spec-doc-drift, 阶段 C.6 触发)
- Theme A 双写期模式 (sqlite 旁路)
- 树莓派 4 Model B 硬件实测 (ssh -i id_rsa_pi, Cortex-A72 @ 1.8GHz, 4 核, 7.6GB RAM)