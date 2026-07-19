# youfu-known · 个人知识库 RAG 系统规格

> 版本: 0.1 · 状态: 待实现

## 1. 目标

为用户提供本地化、可上传文档、基于 RAG 的问答系统。
所有数据 (上传文件、向量、元信息) 落在本地存储, 仅在调用 MiniMax LLM/Embedding 时走外网。

## 2. 技术栈 (已冻结)

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI 0.139 + Uvicorn | 现有项目已有, async 友好 |
| 向量库 | Chroma 1.0 (PersistentClient) | 本地文件, 零部署, 易替换 |
| LLM (对话) | MiniMax (OpenAI 兼容协议) | 用户指定 |
| Embedding | 阿里云百炼 DashScope (Qwen3-Embedding 系列, text-embedding-v3) | MiniMax 无 embed, Qwen3 中文最强 |
| 文档解析 | pypdf (PDF), python-docx (Word), markdown+bs4 (MD/HTML) | 官方包 |
| HTTP | httpx | 异步, 兼容 OpenAI SDK |
| 元信息存储 | SQLite3 (内置 sqlite3 模块) | 知识库/文档元信息 |
| 前端 | Vite + React 18 + Chakra UI | 用户指定完整 SPA |
| 不引 | LangChain / LlamaIndex | 重, 直接拼装更可控 |

## 3. 项目结构

```
youfu-known/
├── config.yaml                    # 全局配置
├── .env.example                   # 凭据模板
├── requirements.txt
├── main.py                        # FastAPI 入口 (新增 lifespan)
├── app/
│   ├── __init__.py
│   ├── config.py                  # 加载 config.yaml + .env
│   ├── deps.py                    # FastAPI Depends: 单例 client / kb_service
- `app/llm/`
│   │   ├── __init__.py
│   │   ├── minimax_client.py      # 封装 MiniMax chat (对话)
│   │   ├── embedding_client.py    # 封装 DashScope embedding (Qwen3-Embedding)
│   │   └── base.py                # 公共接口协议 (抽象类)
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── loader.py              # 按扩展名分发到不同 parser
│   │   ├── parser_pdf.py
│   │   ├── parser_docx.py
│   │   ├── parser_md.py
│   │   ├── parser_html.py
│   │   ├── parser_txt.py
│   │   ├── chunker.py             # 递归字符切块
│   │   ├── embedder.py            # 调 DashScope embedding (内部用 EmbeddingClient)
│   │   ├── vectorstore.py         # Chroma PersistentClient 封装
│   │   └── retriever.py           # 召回 + 拼 prompt + 调 chat
│   ├── kb/
│   │   ├── __init__.py
│   │   ├── models.py              # Pydantic 模型 (KnowledgeBase, Document, ...)
│   │   ├── service.py             # KB 增删查, 文档上传/处理, 状态查询
│   │   └── storage.py             # SQLite 元信息读写
│   ├── api/
│   │   ├── __init__.py
│   │   ├── knowledge_bases.py     # /api/kbs ...
│   │   ├── documents.py           # /api/kbs/{id}/documents ...
│   │   └── chat.py                # /api/kbs/{id}/chat ...
│   └── jobs/
│       ├── __init__.py
│       └── ingest.py              # 异步 ingest 任务 (asyncio.create_task)
├── web/                           # Vite + React 前端
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api.ts                 # 封装 fetch
│       ├── theme.ts
│       └── components/
│           ├── KnowledgeBaseSidebar.tsx
│           ├── DocumentList.tsx
│           ├── Uploader.tsx
│           ├── ChatPanel.tsx
│           └── CitationPanel.tsx
├── storage/                       # 运行时生成
│   ├── uploads/{kb_id}/{doc_id}.{ext}
│   ├── chroma/                    # chroma 持久化
│   └── knowledge_base.sqlite3
├── tests/
│   ├── test_loader.py
│   ├── test_chunker.py
│   └── test_api.py
└── openspec/spec.md
```

## 4. 数据模型

### 4.1 SQLite 表

```sql
-- 知识库
CREATE TABLE knowledge_bases (
    id           TEXT PRIMARY KEY,          -- uuid4 hex
    name         TEXT NOT NULL UNIQUE,
    description  TEXT DEFAULT '',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    doc_count    INTEGER DEFAULT 0,
    chunk_count  INTEGER DEFAULT 0
);

-- 文档
CREATE TABLE documents (
    id           TEXT PRIMARY KEY,
    kb_id        TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,             -- 原始文件名
    ext          TEXT NOT NULL,             -- .pdf / .docx / ...
    size_bytes   INTEGER NOT NULL,
    storage_path TEXT NOT NULL,             -- ./storage/uploads/{kb_id}/{id}.{ext}
    status       TEXT NOT NULL,             -- pending | processing | ready | failed
    error        TEXT DEFAULT '',
    chunk_count  INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
CREATE INDEX idx_documents_kb ON documents(kb_id);
```

### 4.2 Chroma Collection

每个知识库 = 一个 Collection:
- name: `kb_<kb_id>`
- metadata: `{"kb_id": "...", "kb_name": "..."}`
- 向量维度: 由 `minimax.embed_dim` 决定 (默认 1024)

每条 Document (Chroma 意义) = 一个 chunk:
- id: `{doc_id}::{chunk_idx}` (便于按文档删除)
- document: chunk 文本
- metadata:
  - `kb_id`
  - `doc_id`
  - `doc_filename`
  - `chunk_idx`
  - `chunk_total`
  - `page` (PDF/Word 有, 其它为 null)
  - `source_offset` (字符偏移)

## 5. REST API

所有响应统一 `{ "code": 0, "data": ... }`, 错误 `{ "code": <int>, "message": "..." }`。

### 5.1 知识库

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/kbs` | 列出所有 KB |
| POST | `/api/kbs` | 创建 KB `{name, description?}` |
| GET | `/api/kbs/{kb_id}` | KB 详情 + 文档列表 + 统计 |
| PATCH | `/api/kbs/{kb_id}` | 改名 / 改描述 |
| DELETE | `/api/kbs/{kb_id}` | 删除 KB (级联删文档 + Chroma collection) |

### 5.2 文档

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/kbs/{kb_id}/documents` | multipart 上传 (支持多个文件), 异步处理 |
| GET | `/api/kbs/{kb_id}/documents` | 列出 KB 下所有文档 |
| GET | `/api/kbs/{kb_id}/documents/{doc_id}` | 单文档详情 |
| DELETE | `/api/kbs/{kb_id}/documents/{doc_id}` | 删除文档 + Chroma 关联 chunks |
| GET | `/api/kbs/{kb_id}/documents/{doc_id}/status` | 轮询处理状态 |

上传返回示例:
```json
{ "code": 0, "data": { "uploaded": [{"doc_id": "...", "filename": "a.pdf", "status": "pending"}] } }
```

### 5.3 问答

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/kbs/{kb_id}/chat` | `{question, top_k?, stream?}` |

请求:
```json
{
  "question": "MiniMax Embedding 接口地址是?",
  "top_k": 6,
  "stream": false
}
```

非流式响应:
```json
{
  "code": 0,
  "data": {
    "answer": "根据资料, MiniMax Embedding 接口地址为 https://api.MiniMax.chat/v1/embeddings [1]。",
    "citations": [
      {
        "n": 1,
        "doc_id": "...",
        "doc_filename": "minimax_docs.md",
        "chunk_idx": 3,
        "score": 0.82,
        "text": "MiniMax Embedding 接口地址为 https://api.MiniMax.chat/v1/embeddings ..."
      }
    ]
  }
}
```

流式响应: `text/event-stream`, 每帧 `data: <delta json>\n\n`, 最后一帧 `data: [DONE]`。

### 5.4 健康检查

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/health` | 返回 `{status, version}` |
| GET | `/` | 重定向到 SPA (开发时) 或返回 index.html |

## 6. 处理流水线 (上传 -> 入库)

```
[Upload File]
    │
    ▼
[Save to ./storage/uploads/{kb_id}/{doc_id}.{ext}]   status=pending
    │
    ▼  (asyncio.create_task)
[Loader] ── 按 ext 分发 ──> Parser
    │                         │
    │                         ▼
    │                    List[Page / Section] (含 page, text)
    │
    ▼
[Chunker] 递归字符切块, 保留 page 元数据
    │  chunk_size=600, overlap=80, separators 走配置
    ▼
[Embedder] 批量调 DashScope /compatible-mode/v1/embeddings (batch≤25)
    │
    ▼
[VectorStore.upsert] Chroma collection.add (ids, embeddings, documents, metadatas)
    │
    ▼
[Update SQLite] status=ready, chunk_count=N, processed_at=now
    │
    ▼
[Update KB] doc_count++, chunk_count += N
```

失败任一步: status=failed, error=msg, 不影响 KB 其它文档。

## 7. 问答流水线

```
[Question]
    │
    ▼
[Embedder.embed_query]  DashScope /compatible-mode/v1/embeddings (单条)
    │
    ▼
[VectorStore.query]  Chroma collection.query (top_k=6, include=["documents","metadatas","distances"])
    │
    ▼
[Filter]  score >= threshold  (可选)
    │
    ▼
[Format Citations]  编号 1..N, 带 doc_filename + chunk_idx
    │
    ▼
[Build Prompt]  system_prompt + 参考资料 + user question
    │
    ▼
[Chat Completion]  MiniMax /v1/chat/completions
    │                 非流式: collect whole response
    │                 流式: yield deltas
    ▼
[Return] answer + citations
```

## 8. 配置加载

- `app/config.py` 启动时:
  1. 加载 `config.yaml` (yaml.safe_load)
  2. 加载 `.env` (如果存在), 覆盖 `chat.api_key` 和 `embedding.api_key`
- 配置以 dataclass / Pydantic model 形式注入到各模块
- 全局单例 `get_settings()`

## 9. 错误处理

- HTTP 4xx: 参数错误 (kb_id 不存在, 文件超限, 扩展名不允许)
- HTTP 5xx: 内部错误 (LLM/Embedding 调用失败, Chroma IO 错误)
- 所有异常通过 FastAPI exception handler 转 `{code, message}` JSON

## 10. 测试

- `tests/test_loader.py`: 给定样本 PDF/Word/MD/TXT/HTML, 断言 loader 返回非空 list
- `tests/test_chunker.py`: 给定长文本, 断言 chunk 数 >= 1, 每块 <= chunk_size+overlap
- `tests/test_api.py`: 用 TestClient 跑:
  - 创建 KB → 上传文件 → 轮询状态 → 提问 → 期望答案非空 (LLM 调用要 mock)
- LLM / Embedding / Chroma IO 在测试中用 monkeypatch 或 mock,不真打外网

## 11. 前端 (Vite + React + Chakra)

### 页面布局 (单页)

```
┌──────────────┬──────────────────────────────────┐
│  Sidebar     │  主区域 (按 KB 切换)              │
│              │                                   │
│  + 新建 KB   │  ┌─ 上传区 (拖拽 + 按钮) ──────┐  │
│              │  │  drop PDF/Word/MD/TXT/HTML   │  │
│  KB 列表     │  └─────────────────────────────┘  │
│  • 工作笔记  │  ┌─ 文档表格 ─────────────────┐    │
│  • 投研资料  │  │ 文件名 | 大小 | 状态 | 操作 │    │
│  • 技术栈   │  └─────────────────────────────┘    │
│              │  ┌─ 问答区 ─────────────────────┐  │
│              │  │ 历史问答                     │  │
│              │  │ [回答文本]                   │  │
│              │  │ ▸ 引用 [1] 文件.md chunk 3   │  │
│              │  │ ▸ 引用 [2] ...              │  │
│              │  │ [输入框] [发送]              │  │
│              │  └─────────────────────────────┘  │
└──────────────┴──────────────────────────────────┘
```

### 交互要求

- 选中 KB 后, 主区域显示该 KB 的文档 + 问答
- 上传文件: 显示每个文件的处理进度 (状态轮询, 2s 一次, ready/failed 后停)
- 提问: 流式输出答案, 答案下方折叠列表展示引用 (点击展开看原文片段)
- 删除 KB/文档: 二次确认

## 12. 启动 & 开发

```bash
# 后端
source .venv/bin/activate
cp .env.example .env  # 填 API key
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd web
npm install
npm run dev          # 开发, Vite 反代 /api -> 8000

# 构建
npm run build        # 产物在 web/dist/
# 生产: FastAPI mount web/dist/ 为 StaticFiles, 根路由返回 index.html
```

## 13. 验收标准 (DoD)

- [ ] 后端 pytest 全绿
- [ ] 上传一份 PDF → 30s 内 status=ready, chunk_count > 0
- [ ] 提问 → 收到非空 answer, citations 数 >= 1
- [ ] 流式问答 → 浏览器看到逐字输出
- [ ] 删除 KB → Chroma collection 与磁盘文件全清
- [ ] 前端 build 成功, 浏览器访问 SPA 截图正常

## 14. 已知风险

- **DashScope embedding 维度**: 配置默认 `text-embedding-v3` / `1024 维`, 与 Chroma collection 维度一致
- **DashScope 速率限制**: 单次最多 25 条/批, 内部自动分批; 失败重试 3 次 (指数退避)
- **大 PDF**: 单文档超过 100MB 时, 切块可能慢, 默认 max_file_size_mb=50 兜底