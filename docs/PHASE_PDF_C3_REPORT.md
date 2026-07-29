# Phase PDF-C.3 — Qwen-VL-Max Multi-modal LLM

> **Version**: v0.9.0-dev
> **Last updated**: 2026-07-29
> **Based on commit**: `1becf2e` (Phase PDF-C.2)
> **关联**: `70bf641` (Phase PDF-C.1 PyMuPDF+pdfplumber) / `app/rag/parser_pdf.py` / `app/rag/parser_pdf_v2.py` / `app/rag/parser_pdf_ocr.py` / `openspec/tasks/pdf-parser-c.md`

## 0. 简介

Phase PDF-C.3 实施 **Qwen-VL-Max 多模态 LLM** 处理复杂 layout PDF (text_ratio < 0.2, scan/图表/双栏/复杂公式)。复用现有 `DASHSCOPE_API_KEY` (跟 `DashScopeEmbeddingClient` 同源), 0 新接入成本, 0 新依赖。Pi 端**不**耗 CPU (纯网络调用), 1 page ≈ 3-5s。Vision 默认 opt-in (`prefer_vision=False`), 跟 Phase C.1+C.2 行为**完全兼容**。

**当前生产部署**: https://kb.sxy.homes
**新增依赖**: 0 (复用现有 httpx + PyMuPDF + DASHSCOPE_API_KEY)

### 4 个 parser 路由 (Phase C.3 完整图)

| Path | 触发条件 | Extractor | 性能 (1 page) |
|---|---|---|---|
| `parser_pdf_v2` (Phase C.1) | text_ratio > 0.5, prefer_v2=True | pymupdf + pdfplumber | 0.05s |
| `parser_pdf_ocr` (Phase C.2) | text_ratio < 0.5, prefer_ocr=True | tesseract chi_sim+eng | 2-3s |
| **`parser_pdf_vision` (Phase C.3)** | **text_ratio < 0.2, prefer_vision=True** | **qwen-vl-max API** | **3-5s (网络)** |
| `parser_pdf` (pypdf fallback) | PyMuPDF 失败 / prefer_v2=False | pypdf | 0.5s |

## 1. 快速开始

### 1.1 Pi 端配置 (admin 一次性设环境变量)

```bash
# ssh 到 Pi
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.88.102

# 复用现有 DASHSCOPE_API_KEY (跟 embedding 同源, 0 新 key)
echo "DASHSCOPE_API_KEY=sk-xxxx" >> /opt/youfu-known/.env

# (可选) 多 key 轮询 — 你fu 暂用 1 key, 备用 _2 留给将来
echo "DASHSCOPE_API_KEY_2=sk-yyyy" >> /opt/youfu-known/.env

# 重启 uvicorn
bash scripts/restart.sh
```

### 1.2 Vision 路径 (opt-in)

默认**不**启用 vision, 跟 Phase C.1+C.2 行为完全一致:

```python
# 默认: PyMuPDF + pdfplumber, vision 关
sections = load_document("complex_layout.pdf")
# → PyMuPDF 失败 → pypdf fallback (text_ratio=0, sections 可能空)

# 显式启用 vision (复杂 layout)
sections = load_document("complex_layout.pdf", prefer_vision=True)
# → inspector 检测 text_ratio < 0.2 → 走 parser_pdf_vision (Qwen-VL-Max)
```

### 1.3 缓存策略 (复用 Phase C.2 pdf_cache vision_json 字段)

```python
from app.rag.pdf_cache import PdfCache
from app.storage.paths import get_db_path

cache = PdfCache(get_db_path())
sections = parse_pdf_vision("complex.pdf")
cache.put("complex.pdf", vision_sections=sections)  # sha256 dedup + LRU 10GB

# 下次相同 file
result = cache.get("complex.pdf")
# → 直接返 cache, skip Qwen-VL (节省 3-5s/page, ¥0.5/page)
```

## 2. 关键设计 (Hermes V0-V12 亲自跑 + subagent 实施)

### 2.1 Qwen-VL-Max API (阿里百炼, OpenAI 兼容)

- **endpoint**: `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- **model**: `qwen-vl-max` (2024 阿里发布, 中文 OCR + 图表 + 公式 都强)
- **请求格式**: OpenAI 兼容 multimodal (image_url + text), 跟 minimax 同款
- **认证**: `Authorization: Bearer <DASHSCOPE_API_KEY>` (复用现有)
- **响应**: `choices[0].message.content` str 或 multimodal blocks list

### 2.2 多 key 轮询 + failover (跟 minimax_client 同款)

- 从 `settings.qwen_vl.api_keys` 读多个 key
- 每次 `avision()` 按 round-robin 选 key, 失败 (尤其 429 / 5xx) 自动切下一个
- 60s 冷却窗口 (跟 MiniMaxChatClient.COOLDOWN_SECONDS 同款)
- 环境变量 fallback: `DASHSCOPE_API_KEY` + `_2` + `_3` + ... (跟 embedding 复用)

### 2.3 4 个 parser 旁路 adapter 模式

跟 32 commits DDD Theme B + INC-005 "不替换" 同款:

```
PDF file
   ↓
[Step 1: PDFInspector]    text_ratio > 0.5 → text / < 0.5 → ocr / < 0.2 → vision
   ↓ (text_path)
[Step 2a: PyMuPDF + pdfplumber]    0.05s/page, layout + tables + images
   ↓ (ocr_path)
[Step 2b: Tesseract chi_sim + eng]    2-3s/page, 扫描件 OCR
   ↓ (vision_path, opt-in)
[Step 2c: Qwen-VL-Max API]    3-5s/page, 复杂 layout + 多模态
   ↓
[Step 3: SQLite pdf_cache]    sha256 → cache hit skip (vision_json 字段复用)
   ↓
[Step 4: RecursiveChunker]    现有, 适配 sections
   ↓
[Step 5: DashScope Embedding]    现有, 1024d
   ↓
[Step 6: Chroma Upsert]    现有
```

### 2.4 Section shape (Phase C.3 扩展)

```python
{
    "page": int,  # 1-based
    "text": str,
    "tables": List[List[List[str]]],  # pdfplumber tables (Phase C.1)
    "images": List[dict],  # PyMuPDF image bbox (Phase C.1)
    "metadata": {
        "extractor": "pymupdf" | "pymupdf+pdfplumber" | "tesseract" | "qwen-vl-max" | "pypdf_fallback",
        # Phase C.3 新加:
        "model": "qwen-vl-max",  # vision 模型名 (审计 trail)
        "dpi": 200,  # 渲染分辨率 (跟 OCR 同款)
    },
}
```

## 3. API 完整列表 (无新 endpoint)

Vision 在 ingest pipeline 内调用, **不**暴露新 HTTP API。

跟 `app/rag/parser_pdf_vision.py` 同步, 1 个核心函数:

```python
def parse_pdf_vision(
    path: str | Path,
    *,
    dpi: int = 200,
    prompt: str = PROMPT_EXTRACT,
    client: Optional[QwenVLClient] = None,
) -> List[dict]:
    """Parse PDF with Qwen-VL-Max multimodal LLM (复杂 layout).
    
    流程:
    1. PyMuPDF 渲染每页到 PNG (dpi=200, ~50ms/page)
    2. Qwen-VL-Max API 接收 image + prompt (~3-5s/page)
    3. 返 sections: [{page, text, metadata: {extractor: 'qwen-vl-max', model, dpi}}]
    
    错误类型:
    - FileNotFoundError: PDF 不存在
    - RuntimeError: PyMuPDF 未装 / Vision API 失败
    """
```

跟 `app/llm/qwen_vl_client.py` 同步, 1 个核心 class:

```python
class QwenVLClient:
    """Async multi-modal client for DashScope Qwen-VL-Max.
    
    多 key 支持 (跟 MiniMaxChatClient 同款):
        DASHSCOPE_API_KEY      # 优先 (主 key)
        DASHSCOPE_API_KEY_2    # 备用 1
        DASHSCOPE_API_KEY_3    # 备用 2
        ...
    
    BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    MODEL = "qwen-vl-max"
    COOLDOWN_SECONDS = 60
    
    Methods:
        - avision(image_png, prompt, **kw) -> str  # 返 markdown
    """
```

## 4. 常见错误 (5 个)

### 4.1 FileNotFoundError

**复现**: `parse_pdf_vision("/nonexistent.pdf")`
**报错**: `FileNotFoundError: PDF not found: /nonexistent.pdf`
**修复**: 检查文件路径, 用 `Path.exists()` 预 check。

### 4.2 RuntimeError: PyMuPDF not installed

**复现**: Pi 端**没**装 `pip install pymupdf`
**报错**: `RuntimeError: PyMuPDF not installed; parser_pdf_vision requires it`
**修复**: `pip install pymupdf==1.25.5` (Phase C.1 已装, 0 新依赖)。

### 4.3 RuntimeError: All Qwen-VL keys failed

**复现**: 所有 DASHSCOPE_API_KEY 都失效 / 429
**报错**: `RuntimeError: Qwen-VL vision request failed after trying N key(s)`
**修复**: 检查 key 配额 / 余额 / 网络, 重启 uvicorn 重试。

### 4.4 401 / Vision 慢 (3-5s/page)

**复现**: 100 页复杂 layout PDF
**耗时**: 100 × 4s = ~7 分钟
**优化**:
- 缓存: 重复 PDF 不重跑 vision (sqlite sha256 dedup, vision_json 字段复用)
- 并发: `asyncio.Semaphore(2)` (Phase C.4 KB settings)
- KB settings `enable_vision_llm=false`: 跳过 vision (纯文本 / scan-only PDF)

### 4.5 Storage 满 (LRU 触发)

**复现**: pdf_cache 总大小 > 10GB
**触发**: 自动 LRU clean (按 created_at DESC 删最旧)
**修复**: 手动调 `pdf_cache.lru_clean(max_size_bytes=20GB)` 调整上限。

## 5. 故障排查

### 5.1 Vision 不工作 (key 失效)

**Root cause**: DASHSCOPE_API_KEY 失效 / 阿里百炼 quota 用完
**修法**:
1. 查 https://dashscope.console.aliyun.com/ → API-Key 管理
2. 查 余额 / 配额, 充值 或 加 DASHSCOPE_API_KEY_2 备用
3. **不**重启 uvicorn 即可热加载 (round-robin 自动选下一个可用 key)

### 5.2 Vision 慢 (>10s/page)

**Root cause**: 网络延迟 / DPI 太高
**修法**:
1. Pi 端 `ping dashscope.aliyuncs.com` 应 < 100ms
2. 调低 `dpi=150` (默认 200), 牺牲精度换速度
3. 加 `DASHSCOPE_API_KEY_2` 并发: Phase C.4 KB settings `enable_concurrent_vision=true`

### 5.3 PyMuPDF + Qwen-VL 都失败

**Root cause**: 损坏 PDF / 加密 PDF / Qwen-VL quota 用完
**修法**: 走 `parser_pdf.py` (pypdf fallback) 试. 如果还失败, 报 `RuntimeError` 给 caller。

### 5.4 P5b/P8a lifespan idempotent fail (lifespan 二次启 crash)

**Root cause**: lifespan 第二次启时, sqlite 重复 create pdf_cache 表
**修法**: 已修 (Phase C.2 用 `CREATE TABLE IF NOT EXISTS` + idempotent migration, Phase C.3 复用)。

## 6. 测试

### 6.1 单元测试

- **`tests/test_parser_pdf_vision.py` (3 测试, pytest)**: mock Qwen-VL API + sample_complex.pdf fixture
- 现有 `tests/test_parser_pdf_ocr.py` (Phase C.2, 5 测试, 0 回归)
- 现有 `tests/test_pdf_cache.py` (Phase C.2, 5 测试, 0 回归)
- 现有 `tests/test_parser_pdf_v2.py` (Phase C.1, 11 测试, 0 回归)

### 6.2 集成测试

- 现有 `tests/integration/test_admin_lifespan.py` (1 测试, 0 回归)

### 6.3 端到端测试

- 现有 `web/tests/e2e/admin.spec.ts` (后台管理端 阶段 5, 3 测试, 0 回归)

### 6.4 跑全量

```bash
# backend
.venv/bin/python -m pytest tests/ -q  # 248 passed (245 baseline + 3 new)

# frontend 单元
cd web && npm test  # 17 passed (5 pre-existing fail 跟本任务无关)

# Pi 端 (vision 需要网络 + DASHSCOPE_API_KEY)
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.88.102
cd /opt/youfu-known
.venv/bin/python -m pytest tests/test_parser_pdf_vision.py -v  # 3 passed (mock API)
```

## 7. 部署 URL

| 部署 | URL | 备注 |
|---|---|---|
| 本地 (Vite dev) | http://localhost:5173/ | `YOUFU_VITE_API_TARGET=http://127.0.0.1:8765` |
| 生产 (Cloudflare Tunnel) | https://kb.sxy.homes | 锁 8000 (SSH tunnel 才能从本机访问) |
| 后端 (uvicorn) | http://127.0.0.1:8765 | API 端, 不直接 browser 访问 |
| 树莓派 (192.168.88.102) | ssh://youfu@192.168.88.102 | 网络可达 dashscope.aliyuncs.com 时 vision 可用 |
| 阿里百炼 API | https://dashscope.aliyuncs.com | Qwen-VL-Max endpoint (OpenAI 兼容) |

## 关键设计决策 (跟 Phase C.1+C.2 + INC-005 + Theme A 同款)

1. **Qwen-VL-Max API (阿里百炼, OpenAI 兼容, 中文好)** — 复用现有 DASHSCOPE_API_KEY
2. **SQLite pdf_cache vision_json 字段 (Phase C.2 已预留, Phase C.3 复用)** — 跟 Theme A 双写期同款, 不新加存储系统
3. **`prefer_vision=False` default** — 跟 Phase C.1+C.2 行为完全兼容, opt-in 启用
4. **¥5000/月上限 (1 万页)** — 跟 32 commits DDD P2.18 LLM slow 教训同款, 配额限制避免失控
5. **多 key 轮询 + failover** — 跟 minimax_client.py 同款, 0 接入成本
6. **Pi 端网络可达** — 0 新 apt 包, 0 新 Python dep
7. **Per-page 防御** — 1 个 page vision 失败不 abort 整个 document (跟 INC-005 + Phase C.2 同款)
8. **`metadata.extractor='qwen-vl-max'` + `metadata.model='qwen-vl-max'`** — 审计 trail, 跟 Phase C.1 + C.2 marker 同款
9. **PyMuPDF 复用** — Phase C.1 已装, Phase C.3 复用 `fitz.open` + `page.get_pixmap().tobytes("png")`

## 改动 (6 文件: 4 新 + 2 改, +820/-3)

| Path | 状态 | 改动 |
|---|---|---|
| app/rag/parser_pdf.py | (不动) | INC-005 |
| app/rag/parser_pdf_v2.py | (不动) | Phase C.1 已 commit |
| app/rag/parser_pdf_ocr.py | (不动) | Phase C.2 已 commit |
| app/rag/parser_pdf_vision.py | A (新) | +241 行 (Qwen-VL-Max API + page rendering) |
| app/llm/qwen_vl_client.py | A (新) | +297 行 (多模态 client + 多 key failover) |
| app/rag/loader.py | M (+63) | load_document 加 prefer_vision kwarg + vision dispatch branch |
| app/config.py | M (+22) | 新加 QwenVLConfig + Settings.qwen_vl 字段 |
| app/rag/pdf_cache.py | (不动) | Phase C.2 vision_json 字段已预留, **不**改 |
| tests/test_parser_pdf_vision.py | A (新) | +164 行 (3 测试, mock API) |
| docs/PHASE_PDF_C3_REPORT.md | A (新) | 本文档 |

## 不改清单 (跟硬约束一致)

- **0 改** `app/rag/parser_pdf.py` (Hermes 类, INC-005)
- **0 改** `app/rag/parser_pdf_v2.py` (Phase C.1 已 commit, **不**改)
- **0 改** `app/rag/parser_pdf_ocr.py` (Phase C.2 已 commit, **不**改)
- **0 改** `app/rag/pdf_inspector.py` (Phase C.1 已 commit, **不**改)
- **0 改** `app/rag/pdf_cache.py` (Phase C.2 vision_json 字段已加, **不**改)
- **0 改** `backend/main.py` (lifespan 段不动)
- **0 改** `app/rag/chunker.py` (适配留给后续 phase, 跟 Theme B 同款)
- **0 改** `app/llm/minimax_client.py` (已有, 跟它同款 pattern 参考)
- **0 改** `app/llm/embedding_client.py` (已有, 跟它同款 pattern 参考)
- **0 改** 现有 `tests/test_*.py` (新增独立 test_*.py)
- **0 改** `web/src/components/Admin*` (后台管理端已 commit)
- **0 改** `web/package.json`
- **0 改** `openspec/tasks/` 现有 spec (除新增 pdf-parser-c.md)
- **0 改** 现有 `docs/*` (除新增)
- **0 commit** (本次, 留 Hermes 亲自 commit + push)

## 验收 (Hermes V0-V12 亲自跑)

| V | 项 | 结果 |
|---|---|---|
| V0 | 新文件清单 | ✅ parser_pdf_vision 241 + qwen_vl_client 297 + test_vision 164 + report ~330 = ~1032 LOC |
| V1 | 0 改 parser_pdf.py + parser_pdf_v2.py + parser_pdf_ocr.py + main.py | ✅ 0 行 |
| V2 | 0 改现有 tests | ✅ 0 行 (除新加) |
| V3 | 0 改 web/src/components/ | ✅ 0 行 |
| V4 | 全量 pytest | ✅ **248 passed** (245 baseline + 3 new, 0 回归) |
| V5 | new 3 test pass | ✅ 3 passed in 1.06s |
| V5b | lifespan idempotent | ✅ 1 passed |
| V6 | vitest frontend | ✅ 17 passed (5 pre-existing fail 跟本任务无关) |
| V7 | build + tsc 0 错 | ✅ exit 0 |
| V12.1 | spec scope (6 类允许文件: 4 新 + 2 改) | ✅ 0 行 (除允许) |
| V12.2 | parser_pdf.py 0 改 | ✅ 0 行 |
| V12.3 | parser_pdf_v2.py 0 改 | ✅ 0 行 |
| V12.4 | parser_pdf_ocr.py 0 改 | ✅ 0 行 |
| V12.5 | main.py 0 改 | ✅ 0 行 |
| V12.6 | chunker.py 0 改 | ✅ 0 行 |
| V12.7 | pdf_cache.py 0 改 | ✅ 0 行 (vision_json 字段 Phase C.2 已预留) |

## 下一步 (Phase PDF-C.4 留给下一轮)

- 派 Kimi 写 `web/src/components/KBSettings.tsx` (KB 配置 + `enable_ocr` / `enable_vision_llm`)
- 适配 `web/src/components/Uploader.tsx` (PDF 上传进度, vision 时显示 "Qwen-VL 处理中...")
- 加 Vitest (KBSettings + Uploader)
- 阶段 C.5: e2e 测试覆盖 vision 路径
- 阶段 C.6: 必做 INC-012 postmortem + self_improve.py (沉淀 vision-llm + 适配 opt-in)

## 关联

- `openspec/tasks/pdf-parser-c.md` (6 阶段 spec, 7.7KB)
- commit `1becf2e` (Phase PDF-C.2: Tesseract OCR + SQLite cache)
- commit `70bf641` (Phase PDF-C.1: PyMuPDF + pdfplumber + Inspector)
- commit `858622f` (CI: GitHub Actions 5 jobs + V-rung 集成)
- `docs/PHASE_PDF_C1_REPORT.md` (Phase C.1 实施报告)
- `docs/PHASE_PDF_C2_REPORT.md` (Phase C.2 实施报告)
- `docs/ADMIN_GUIDE.md` (后台管理端操作手册)
- `docs/deploy.md` (跟本文同款风格参考)
- `verifies` skill v1.0 / `decision_tree.yaml` (16 rules)
- INC-001 (P5b idempotent fail)
- INC-004 (asyncio.Semaphore 避免阻塞)
- INC-005 (P2.32 verify-session scope drift, 不替换)
- INC-011 (spec-doc-drift, 阶段 C.6 触发)
- Theme A 双写期模式 (sqlite 旁路)
- Theme B 旁路 adapter 模式 (4 个 parser 并存)
- 32 commits DDD P2.18 LLM slow 教训 (¥5000/月上限)
- 树莓派 4 Model B 硬件实测 (ssh -i id_rsa_pi, Cortex-A72 @ 1.8GHz, 4 核, 7.6GB RAM)

## 自我反思 (Hermes V12 anti-lie)

- ✅ V0 新文件清单: 实测 wc -l, 4 个新文件 ~1032 LOC
- ✅ V1 0 改 runtime: git diff HEAD -- 4 个文件 = 0 行
- ✅ V2 0 改现有 tests: git diff HEAD -- tests/ (除新加) = 0 行
- ✅ V3 0 改 web: git diff HEAD -- web/src/components/ = 0 行
- ✅ V4 pytest 248 passed: 实测 (.venv/bin/python -m pytest tests/ -q)
- ✅ V5 new 3 test pass: 实测 (1.06s)
- ✅ V5b lifespan: 实测 1 passed
- ✅ V12.7 pdf_cache.py 0 改: vision_json 字段 Phase C.2 已预留, 复用

**Step 3 AMENDMENT-PHASE2-AUTOPILOT 授权 hermes 自动通过 (Phase PDF-C.3 Qwen-VL-Max multi-modal LLM)**