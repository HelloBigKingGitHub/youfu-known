# PDF 知识库解析 (树莓派 4 适配版)

> **任务编号**: pdf-parser-c
> **派发对象**: Claude Code (后端, 阶段 1+2+3) + Kimi (前端, 阶段 4)
> **状态**: ✅ 已完成 (5 commits: `70bf641` / `1becf2e` / `f8217c1` / `849b939` / `4a2feb2`)
> **基于**: 当前 `app/rag/parser_pdf.py` (pypdf==6.1.1 纯文本提取)
> **部署**: 树莓派 4 Model B (aarch64, Cortex-A72 @ 1.8GHz, 4 核, 7.6GB RAM)

## 背景

当前 PDF 解析**只**支持纯文本 (pypdf), 缺口巨大:

| 场景 | 现状 (pypdf) | **期望 (C-RPi)** |
|---|---|---|
| 纯文本 PDF (80% 场景) | ✅ 可提取, 但 layout 乱 | ✅ PyMuPDF + pdfplumber 准确提取 |
| 表格 PDF (10% 场景) | ❌ 表格错位成一行 | ✅ pdfplumber tables 识别 |
| 扫描件 PDF (5% 场景) | ❌ **完全丢** | ✅ Tesseract OCR (eng + chi_sim) |
| 复杂 layout (4% 场景) | ❌ 文字错位 | ✅ Qwen-VL-Max 多模态 LLM (opt-in) |
| 图片/公式 (1% 场景) | ❌ **完全丢** | ✅ PyMuPDF image bbox + opt-in vision |

## 设计目标 (树莓派 4 适配, 跟 32 commits DDD "0 改 runtime" 一致)

### 范围 (本次 6 阶段)

1. **Phase C.1**: PyMuPDF + pdfplumber + Inspector (text_ratio 检测)
2. **Phase C.2**: Tesseract OCR + SQLite cache (旁路, 复用现有 sqlite)
3. **Phase C.3**: Qwen-VL-Max 多模态 LLM (opt-in, API 调用)
4. **Phase C.4**: UI + KB settings + Uploader (前端)
5. **Phase C.5**: 集成测试 + e2e + CI V-rung 集成
6. **Phase C.6**: docs + spec sync + INC-012 postmortem + self_improve

### 不在范围 (留作后续)

- 树莓派 GPU 加速 (Pi 4 **没** GPU, 等 Pi 5)
- 本地大模型 (Qwen2-VL / Llama 3 Vision) - 树莓派 RAM 不够
- PDF 编辑 / 注释 / OCR 校对工具
- 多语言混合 OCR (目前只 chi_sim + eng)

### 性能目标 (树莓派 4 实测)

| 操作 | 时间 (1 page) | 备注 |
|---|---|---|
| PyMuPDF 提取 | 0.05s | native C, Pi OK |
| pdfplumber 表格 | 0.1s | 纯 Python |
| Tesseract eng OCR | 1-2s | 英文扫描件 |
| Tesseract chi_sim OCR | 2-3s | 中文扫描件 |
| Qwen-VL-Max API | 3-5s | 网络, Pi 不耗 CPU |
| DashScope Embedding | 0.05s | 1024d |
| **典型 100 页纯文本** | **30s** | ✅ 可接受 |
| **典型 100 页英文扫描** | 3-5min | ⚠️ 慢但可接受 |
| **典型 100 页中文扫描 + Vision** | 5-10min | ⚠️ 慢, 建议 background |

### 成本目标

| 项 | 估算 (1 万页/月) |
|---|---|
| PyMuPDF + pdfplumber + Tesseract | $0 (本地 CPU) |
| Qwen-VL-Max API (opt-in) | ¥5000/月 |
| SQLite cache | $0 (复用现有 sqlite) |
| **总计** | **¥5000/月** (opt-in 默认关) |

## 设计架构 (跟 32 commits DDD "旁路 adapter" 一致)

### Pipeline (PDF → sections → chunks → vectors)

```
PDF file
   ↓
[Step 1: PDFInspector]    text_ratio > 50%? → text_path / < 50%? → ocr_path
   ↓ (text_path)
[Step 2a: PyMuPDF + pdfplumber]    0.05s/page, layout + tables + images
   ↓ (ocr_path)
[Step 2b: Tesseract chi_sim + eng]    1-3s/page, 扫描件 OCR
   ↓ (opt-in)
[Step 2c: Qwen-VL-Max API]    3-5s/page, 复杂 layout + 多模态
   ↓
[Step 3: SQLite pdf_cache]    sha256 → cache hit skip
   ↓
[Step 4: RecursiveChunker]    现有, 适配 sections
   ↓
[Step 5: DashScope Embedding]    现有, 1024d
   ↓
[Step 6: Chroma Upsert]    现有
```

### 关键决策 (跟我推荐答案一致)

1. **PyMuPDF 不替换 pypdf** - 新加 parser_pdf_v2.py, pypdf fallback (跟 INC-005 "不替换" 一致)
2. **OCR 默认关, opt-in** (KB settings `enable_ocr=true`)
3. **多模态 LLM 默认关, opt-in** (KB settings `enable_vision_llm=true`)
4. **缓存**: SQLite `pdf_cache` 表 (复用 `storage/knowledge_base.sqlite3`, 永久 + LRU 10GB)
5. **混合 OCR**: tesseract eng + chi_sim 同时装, 按 PDF 内容自动选
6. **并发限流**: `asyncio.Semaphore(2)` (Pi 4 4 核, 留 2 核给 PDF)
7. **异步**: fire-and-forget asyncio task (跟现有 ingest pipeline 同款)

### 关键防御 (跟 32 commits DDD 经验一致)

- **P5b 教训**: lifespan 二次启 idempotent
- **INC-004 教训**: asyncio.Semaphore 避免阻塞
- **P2.18 LLM 慢教训**: Qwen-VL API 月度配额限制
- **INC-005 教训**: 0 改 runtime, 旁路 adapter 模式
- **INC-011 教训**: 6 阶段 spec sync (阶段 6 实施)

## 文件结构 (跟后台管理端 8 阶段同款)

```
app/rag/
├── parser_pdf.py              # 现有 (pypdf), 保留, **不**改
├── parser_pdf_v2.py           # 新 (PyMuPDF + pdfplumber), 阶段 C.1
├── parser_pdf_ocr.py          # 新 (Tesseract chi_sim + eng), 阶段 C.2
├── parser_pdf_vision.py       # 新 (Qwen-VL-Max API), 阶段 C.3
├── pdf_inspector.py           # 新 (text_ratio 检测), 阶段 C.1
├── pdf_cache.py               # 新 (SQLite 旁路), 阶段 C.2
└── tests/
    ├── test_parser_pdf_v2.py       # 新 (10 test), 阶段 C.1
    ├── test_parser_pdf_ocr.py      # 新 (5 test), 阶段 C.2
    ├── test_pdf_inspector.py       # 新 (5 test), 阶段 C.1
    └── test_pdf_cache.py           # 新 (3 test), 阶段 C.2

storage/
└── knowledge_base.sqlite3     # 现有, 加 pdf_cache 表 (阶段 C.2)

docs/
├── PDF_PARSER_GUIDE.md        # 新 (操作手册 ~300 行), 阶段 C.6
└── PHASE_PDF_C{1,2,3,4,5}_REPORT.md   # 新 (5 个报告), 每阶段 1 个

openspec/tasks/
└── pdf-parser-c.md            # 本文件, 阶段 C.6 sync

scripts/
└── install_pi_pdf.sh          # 新 (一键装: tesseract + chi_sim + eng), 阶段 C.2
```

## 硬约束 (6 阶段统一)

- **0 改** `app/rag/parser_pdf.py` (现有 pypdf 保留, 跟 32 commits DDD 一致)
- **0 改** `backend/main.py` (lifespan 段不动)
- **0 改** `app/storage/` 现有 schema (新增 pdf_cache 表, 不改现有表)
- **0 改** `app/rag/chunker.py` (适配, 跟 32 commits DDD Theme B "旁路 adapter" 同款)
- **0 改** `app/llm/` (Qwen-VL 跟 minimax_client 同款, 现有架构适配)
- **0 改** 现有 `tests/test_*.py` (新增独立 test_*.py)
- **0 改** `web/src/components/Admin*` (后台管理端 8 阶段已 commit)
- **0 改** 现有 `docs/deploy.md` / `docs/ADMIN_GUIDE.md` (新增 PDF_PARSER_GUIDE)
- **0 改** `web/package.json` / `pyproject.toml` (新依赖仅加, 不删)
- **0 改** `openspec/tasks/` 现有 spec (除本文件)
- **0 commit** (subagent 必跑, 我亲自 commit + push)

## 验收 (Hermes V0-V12 亲自跑, 每阶段)

跟后台管理端 8 阶段同款 V-rung:
- **V0**: scope audit (新文件列表)
- **V1**: runtime audit (0 改 app/parser_pdf.py + main.py)
- **V2**: pytest regression (现有 219 passed 0 回归)
- **V4**: new tests (新 test 100% pass)
- **V5**: lifespan smoke test (P5b/P8a idempotent)
- **V7**: build + tsc 0 错
- **V12**: anti-lie (4 invariant, 跟 INC-005 同款)

## 关联

- 跟 32 commits DDD Theme A "SQLite 双写期" 同款
- 跟 32 commits DDD Theme B "旁路 adapter" 同款
- 跟 32 commits DDD INC-001 / INC-003 (P5b/P8a lifespan idempotent) 同款
- 跟后台管理端 8 阶段 (admin 后台 + 测试 + CI) 同款
- 跟 verifies skill v1.0 (decision_tree 16 rules) 同款
- INC-011 (spec-doc-drift) - 阶段 C.6 必触发

## 下一步 (LOOP)

按 6 阶段 LOOP 推进, 每阶段:
1. 我**亲自**写 spec (本文件)
2. 我**亲自**派 Claude Code subagent (阶段 1-3) / Kimi subagent (阶段 4)
3. 我**亲自** V0-V12 验
4. 我**亲自** commit + push
5. 立刻下一阶段 (不等人, 跟你 "不要停" 同款)

Refs:
- 32 commits DDD (32 commits / +34122 净改 / 1037 pytest / 0 改 runtime)
- 后台管理端 8 阶段 (commit `59e030e` ... `858622f`)
- verifies skill v1.0 (decision_tree 16 rules)
- INC-001 / INC-003 / INC-004 / INC-005 / INC-011
- 树莓派 4 Model B 硬件实测 (ssh -i id_rsa_pi youfu@192.168.88.102)