# 数据层增强 Spec

> **任务编号**: data-layer-enhancement
> **派发对象**: Claude Code (后端)
> **状态**: ✅ 已完成 (commits `ba7cb10` + `c10f02a`)
> **基于**: 当前 `app/kb/storage.py` + `app/kb/models.py`

## 背景

当前数据层 (`app/kb/storage.py`) 只覆盖了 KB + Document 两张表的 CRUD，**核心问答历史不持久化** (`ChatPanel.tsx` 的 `useState` 一刷新就丢)。同时缺用户/审计/备份等基础设施。

本次 spec 聚焦于 **可立即落地** 的 3 个增强, 不做大重构。

## 目标 1: 问答历史持久化 (核心)

### 现状问题

- `web/src/components/ChatPanel.tsx` 用 `useState<ChatTurn[]>([])` 内存保存问答
- 用户刷新页面 = 历史全丢
- 用户切 KB = 历史不会丢失 (组件不卸载), 但用户希望 **同一 KB 下历史永远保留**
- API `POST /api/kbs/{kb_id}/chat` 返回 answer + citations, 但**不保存**

### 设计

#### 1.1 新增表: `chat_turns`

```sql
CREATE TABLE chat_turns (
    id              TEXT PRIMARY KEY,           -- UUID hex
    kb_id           TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,              -- 空字符串 if failed
    error           TEXT DEFAULT '',            -- 错误信息 if status='failed'
    citations_json  TEXT NOT NULL,              -- JSON 序列化 List[Citation]
    status          TEXT NOT NULL DEFAULT 'ready',  -- 'ready' | 'failed'
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    latency_ms      INTEGER DEFAULT 0           -- LLM 耗时
);

CREATE INDEX idx_chat_turns_kb_time ON chat_turns(kb_id, created_at DESC);
```

#### 1.2 新增 Pydantic model

`app/kb/models.py`:

```python
class ChatTurn(BaseModel):
    id: str
    kb_id: str
    question: str
    answer: str = ""
    error: str = ""
    citations: List[Citation] = Field(default_factory=list)
    status: str  # "ready" | "failed"
    created_at: datetime
    latency_ms: int = 0

    model_config = ConfigDict(from_attributes=True)
```

#### 1.3 新增 API endpoints

`app/api/chat.py` 或新文件 `app/api/chat_history.py`:

```
GET    /api/kbs/{kb_id}/chats
       → 返回 List[ChatTurn] (按 created_at DESC, 默认 limit=50, 可选 ?limit=N)
       → 不返回 question/answer 之外的元数据

GET    /api/kbs/{kb_id}/chats/{turn_id}
       → 返回单个 ChatTurn (含完整 answer + citations)

DELETE /api/kbs/{kb_id}/chats/{turn_id}
       → 删除单条问答

DELETE /api/kbs/{kb_id}/chats
       → 清空某 KB 的所有问答 (ChatPanel 的 "清空" 按钮用)
```

#### 1.4 修改 chat endpoint 行为

`POST /api/kbs/{kb_id}/chat`:

```python
async def chat(kb_id, body):
    start = time.monotonic()
    try:
        resp = api.chat(...)  # 现有 LLM 调用
        latency = int((time.monotonic() - start) * 1000)
        storage.save_chat_turn(ChatTurn(
            id=uuid4().hex,
            kb_id=kb_id,
            question=body.question,
            answer=resp.answer,
            citations=resp.citations,
            status="ready",
            latency_ms=latency,
        ))
        return resp
    except Exception as e:
        storage.save_chat_turn(ChatTurn(
            id=uuid4().hex,
            kb_id=kb_id,
            question=body.question,
            answer="",
            error=str(e),
            status="failed",
        ))
        raise
```

#### 1.5 前端改造 (后续 spec, 本次不在范围)

本次只改后端。前端 ChatPanel 之后改成:
- mount 时拉 `GET /api/kbs/:kbId/chats?limit=50`
- 发送时调用 `POST /api/kbs/:kbId/chat`
- 清空按钮调用 `DELETE /api/kbs/:kbId/chats`

(前端改造派给前端 agent)

## 目标 2: 文档分块元数据持久化

### 现状问题

- `KBService.ingest_document()` 把 chunks upsert 到 Chroma, **不存每个 chunk 的元数据**
- `Document.chunk_count` 只是计数
- 调试 / 重索引 / 引用追溯时, 不知道 chunks 的具体分布 (长度、来源段落)

### 设计

#### 2.1 新增表: `chunks`

```sql
CREATE TABLE chunks (
    id              TEXT PRIMARY KEY,    -- 同 Chroma id, 格式 "{doc_id}::{chunk_idx}"
    doc_id          TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kb_id           TEXT NOT NULL,       -- 反规范化加速查询
    chunk_idx       INTEGER NOT NULL,
    content         TEXT NOT NULL,       -- 完整 chunk 内容 (用于引用预览, 不嵌入)
    char_count      INTEGER NOT NULL,
    token_estimate  INTEGER DEFAULT 0,
    start_offset    INTEGER DEFAULT 0,   -- 在原文档中的字符偏移
    end_offset      INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(doc_id, chunk_idx)
);

CREATE INDEX idx_chunks_doc ON chunks(doc_id);
CREATE INDEX idx_chunks_kb ON chunks(kb_id);
```

#### 2.2 Pydantic model

```python
class ChunkMeta(BaseModel):
    id: str
    doc_id: str
    kb_id: str
    chunk_idx: int
    content: str
    char_count: int
    token_estimate: int = 0
    start_offset: int = 0
    end_offset: int = 0
    created_at: datetime
```

#### 2.3 ingestion 时双写

在 `app/jobs/ingest.py` 的 `process_document()` 中, 现有 chunk → embed → upsert 到 Chroma 之后, 同时批量 insert 到 chunks 表。

```python
# 现有代码
embeddings = embedder.embed(texts)
vectorstore.upsert(kb_id, ids, embeddings, documents, metadatas)

# 新增
storage.save_chunks_batch([
    ChunkMeta(
        id=cid, doc_id=doc_id, kb_id=kb_id,
        chunk_idx=i, content=text, char_count=len(text),
        start_offset=meta.get("start_offset", 0),
        end_offset=meta.get("end_offset", 0),
    )
    for i, (cid, text) in enumerate(zip(ids, texts))
])
```

注意: 用 `INSERT OR REPLACE` 以支持**重索引**: 同一文档重 ingest 时, 旧 chunks 被覆盖, Chroma 和 chunks 表保持一致。

#### 2.4 API: 查文档 chunks 详情 (调试用)

```
GET /api/documents/{doc_id}/chunks
   → 返回 List[ChunkMeta] (按 chunk_idx 排序)
   → 默认 limit=100, ?offset=N 分页

GET /api/documents/{doc_id}/chunks/{chunk_id}
   → 返回单个 ChunkMeta (含完整 content)
```

#### 2.5 引用增强 (可选)

现有 Citation 用 `chunk_idx` 找原文 (要查 chunks 表), 增加 `chunk_id` 字段方便直接定位:

```python
class Citation(BaseModel):
    n: int
    doc_id: str
    doc_filename: str
    chunk_idx: int
    chunk_id: str          # 新增: "{doc_id}::{chunk_idx}"
    score: float
    text: str
```

retriever 改: 不仅返回 chunk_idx, 还返回 chunk_id (用 doc_id::chunk_idx 拼接)。

## 目标 3: 自动备份脚本

### 现状

- `storage/knowledge_base.sqlite3` 是核心数据
- Chroma 文件夹是核心数据
- 用户/上传文件 (`storage/uploads/`) 是核心数据
- **无任何备份**, 误删 / 磁盘故障 = 数据丢失

### 设计

新增 `scripts/backup.sh`, 自动备份 `storage/` 到 `backups/` 目录, 保留最近 7 天 + 最近 4 个周日。

#### 3.1 脚本设计

```bash
#!/usr/bin/env bash
# scripts/backup.sh
# 备份 storage/ 到 backups/, 保留 7 天 + 4 个周日
#
# 用法: bash scripts/backup.sh
# 输出: backups/backup-YYYYMMDD-HHMMSS.tar.gz

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# 配置
INSTALL_DIR="${YOUFU_INSTALL_DIR:-/home/youfu/youfu-known}"
BACKUP_DIR="${YOUFU_BACKUP_DIR:-/home/youfu/youfu-known/backups}"
KEEP_DAILY=7
KEEP_WEEKLY=4

mkdir -p "${BACKUP_DIR}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup-${TIMESTAMP}.tar.gz"

# 备份 (排除临时文件)
tar -czf "${BACKUP_FILE}" \
    -C "${INSTALL_DIR}" \
    --exclude='storage/chroma-tmp' \
    storage/

# 清理旧备份
log_info "保留最近 ${KEEP_DAILY} 天 + ${KEEP_WEEKLY} 个周日"
find "${BACKUP_DIR}" -name 'backup-*.tar.gz' -type f | sort | head -n -${KEEP_DAILY} | while read -r f; do
    # 周日备份额外保留
    if [[ "${f}" =~ backup-([0-9]{4})([0-9]{2})([0-9]{2}) ]]; then
        date_str="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
        weekday=$(date -d "${date_str}" +%u 2>/dev/null || echo 8)
        if [[ "${weekday}" -eq 7 ]]; then
            # 周日, 检查是否是最近 4 个周日
            weekly_count=$(find "${BACKUP_DIR}" -name 'backup-*' -type f -newermt "${date_str}" -printf '%T@\n' | wc -l)
            if [[ "${weekly_count}" -gt ${KEEP_WEEKLY} ]]; then
                log_info "删除旧周日备份: $(basename ${f})"
                rm "${f}"
            fi
            continue
        fi
    fi
    log_info "删除旧备份: $(basename ${f})"
    rm "${f}"
done

log_ok "备份完成: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"
```

#### 3.2 systemd timer (可选)

`scripts/backup.timer` + `scripts/backup.service`:

```ini
# backup.service
[Unit]
Description=youfu-known data backup

[Service]
Type=oneshot
ExecStart=/home/youfu/youfu-known/scripts/backup.sh
```

```ini
# backup.timer
[Unit]
Description=Daily backup of youfu-known

[Timer]
OnCalendar=daily
OnCalendar=Sun 03:00
Persistent=true

[Install]
WantedBy=timers.target
```

#### 3.3 恢复命令

```bash
# scripts/restore.sh (简单版)
tar -xzf backups/backup-20260101-030000.tar.gz -C /home/youfu/youfu-known/
sudo systemctl restart youfu-known
```

## 验收标准 (主协调会跑)

```bash
# V1: 启服务
bash scripts/start.sh

# V2: 跑核心场景
# - 创建 KB
# - 上传 docx
# - 等 ready
# - 问问题
# - 重启服务 (kill + start)
# - 看 chat 历史还在不在

# V3: API 测试
curl http://127.0.0.1:8000/api/kbs/{id}/chats | jq .
curl http://127.0.0.1:8000/api/documents/{id}/chunks | jq .

# V4: 备份测试
bash scripts/backup.sh
ls -la backups/

# V5: pytest 全过
pytest tests/ -v

# V6: build (前端没改, 不需要)
```

## 不要做

- ❌ 不写前端代码 (ChatPanel 改造派给前端 agent)
- ❌ 不改 Chroma schema
- ❌ 不改 LLM client
- ❌ 不加新依赖

## 完成后

```bash
pytest tests/ -v  # 必须全过
git add -A
git commit -m "feat(data): 问答历史持久化 + chunks 元数据表 + 备份脚本"
```

## 主协调验收

主协调会:
1. 跑 pytest (71+ 个新测试)
2. 跑端到端 (上传→问答→重启→历史保留)
3. 跑备份恢复 (模拟故障)
4. 不通过 → 重派 / 通过 → 推 Pi

START NOW.