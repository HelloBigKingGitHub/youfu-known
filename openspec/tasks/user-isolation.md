# 数据隔离: KB + 问答历史按用户分开

> **任务编号**: user-isolation  
> **派发对象**: Claude Code (后端)  
> **状态**: ✅ 已完成 (commit `8906ab0`)

## 背景

当前 youfu-known 已经有认证 + RBAC, 但**数据隔离不彻底**:

- **KB 可见性**: 任何登录用户能看所有 KB (除非 `is_public=false` + 自己的)
- **问答历史**: 同 KB 内, 所有用户共享一个 `chat_turns` 列表 (这通常不对 — Alice 问的问题 Bob 不该看到)

本 spec 设计**完整的用户级隔离**:
1. KB 仍可**标记为共享** (供团队/家庭使用)
2. 问答历史**按用户隔离** (私密 + 安全)

## 核心改动

### 1. KB 可见性模型 (扩展)

**当前**:
- `is_public=0`: 私有 (只 owner + admin 看)
- `is_public=1`: 公开 (所有人看)

**新模型** (2 选 1):
- **A. 简单方案 (推荐)**: KB 默认私有, **owner 可标记 shared** = 任何登录用户能看 + 聊天
- **B. 显式分享**: KB 默认私有, owner 可选**特定用户**分享

**选 A** (简单, 满足大部分用例):
- KB 有 `is_shared` 字段 (0/1), 默认 0
- 用户可见规则: `(owner_id = me) OR (is_shared = 1) OR (admin)`
- 写入规则: `(owner_id = me) OR (admin)` (不能改 is_shared 除非 owner)

### 2. 聊天历史隔离

**当前**: 同一 KB 共享一个 `chat_turns` 列表

**新模型**:
- **同一 KB 多个用户**: 每人自己单独的聊天流
- API: `GET /api/kbs/{id}/chats` 只返回**当前 user** 的聊天
- **但 RAG 检索用 KB 共享** (任何用户能 query KB 内容, 只是 query 历史隔离)

**实现**:
- `chat_turns` 表加 `user_id` (已有, 但当前没 filter)
- 改 `list_chats(kb_id, user_id)`: 加 `WHERE user_id = ?`
- `save_chat_turn()` 自动用当前 user.id
- 改 `chat_turn.user_id NOT NULL` (NOT NULL 约束)

**API 端点**:
```
GET /api/kbs/{id}/chats           → 当前 user 的聊天
GET /api/kbs/{id}/chats/{turn_id} → 必须 user_id == current user (否则 403/404)
DELETE /api/kbs/{id}/chats/{turn_id} → 同上
```

**管理员特权**: admin 能看所有 KB 的所有用户聊天 (用于审计)

### 3. KB owner 概念 (现有)

**保留**:
- KB 仍 `owner_id` (创建者)
- `is_shared` 字段新增 (替代 `is_public`, 重新定义)

**迁移**:
- `is_public=1` → `is_shared=1` (老字段映射)
- `is_public=0` → `is_shared=0`
- **改名**: `is_public` → `is_shared` (更准确)

### 4. 现有数据迁移

**自动迁移** (lifespan 启动时):
```sql
-- 添加 is_shared 字段 (如果不存在)
ALTER TABLE knowledge_bases ADD COLUMN is_shared INTEGER DEFAULT 0;

-- 迁移 is_public → is_shared
UPDATE knowledge_bases SET is_shared = is_public WHERE is_shared = 0 AND is_public = 1;

-- chat_turns 的 user_id 改为 NOT NULL (老的可能 null, 归到 admin)
UPDATE chat_turns SET user_id = (SELECT id FROM users WHERE role='admin' LIMIT 1) WHERE user_id IS NULL OR user_id = '';
```

**API 响应字段**:
- 返回 `is_shared` (替换 `is_public`)
- 后端兼容: `is_public` 也返回 (deprecated, 跟 `is_shared` 同值)

## API 变更

### 1. KB CRUD (有变更)

```
GET /api/kbs
   → 仍返回所有 visible KB (按 is_shared + owner 过滤)
   → 字段: {id, name, description, owner_id, is_shared (替换 is_public), created_at, doc_count, chunk_count}

POST /api/kbs
   → 创建者 = current user (取代之前的 "无 owner")

PATCH /api/kbs/{id}
   → body: {name?, description?, is_shared?}
   → 只能 owner / admin 改

DELETE /api/kbs/{id}
   → 只能 owner / admin
```

### 2. 文档 (无变更, 但 filter)

```
GET /api/kbs/{id}/documents
   → 同 KB 可见性规则 (owner / shared / admin)
```

### 3. Chat (新规则)

```
POST /api/kbs/{id}/chat
   → 当前 user 提问
   → save_chat_turn 自动用 current user.id (不再 None)
   → 返回的 answer + citations 不变

GET /api/kbs/{id}/chats
   → 只返回 current user 的聊天
   → 加 ?user_id=me (强制) 或 admin 可选 ?user_id=xxx

GET /api/kbs/{id}/chats/{turn_id}
   → 必须 user_id == current user (或 admin)
   → 否则 404 (不要 403 防止信息泄漏)

DELETE /api/kbs/{id}/chats/{turn_id}
   → 同上

DELETE /api/kbs/{id}/chats
   → 清空 current user 在该 KB 下的所有聊天 (不是清 KB 内所有人)
```

### 4. 新增 admin 端点 (审计)

```
GET /api/admin/kbs/{id}/chats
   → admin 看 KB 内所有用户的聊天 (带 user_id 字段)
   → 用于审计

GET /api/admin/users/{id}/chats
   → admin 看某用户的所有聊天 (跨 KB)
```

## Schema 变更

```sql
-- 1. KB 加 is_shared 字段
ALTER TABLE knowledge_bases ADD COLUMN is_shared INTEGER DEFAULT 0;

-- 2. 文档的 owner_id (反规范化) 已有
-- (不需要新加)

-- 3. chat_turns 的 user_id NOT NULL
-- 先更新 null → admin
UPDATE chat_turns SET user_id = (SELECT id FROM users WHERE role='admin' LIMIT 1) 
WHERE user_id IS NULL OR user_id = '';
-- 再加 NOT NULL 约束 (SQLite 不支持直接改, 用 CHECK 约束或 trigger)
```

**Pydantic models**:
```python
class KnowledgeBase(BaseModel):
    id: str
    name: str
    description: str = ""
    owner_id: Optional[str] = None
    is_shared: bool = False
    # 兼容字段
    is_public: Optional[bool] = None  # 同 is_shared
    created_at: datetime
    doc_count: int = 0
    chunk_count: int = 0
```

```python
class ChatTurn(BaseModel):
    id: str
    kb_id: str
    user_id: str  # NOT NULL
    question: str
    answer: str = ""
    error: str = ""
    citations: List[Citation]
    status: str
    created_at: datetime
    latency_ms: int = 0
```

## 实现文件

```
app/kb/
├── storage.py        # 改 list_kbs_for_user, list_chats 加 user_id filter
├── service.py        # 改 upload_document (用 current user), create_kb (用 current user)
├── models.py         # 加 is_shared, ChatTurn.user_id NOT NULL

app/api/
├── knowledge_bases.py  # is_shared CRUD
├── chat.py             # save_turn 用 current user
├── chat_history.py     # 所有 endpoint 加 user filter
└── admin.py            # 新增 admin 审计端点

app/auth/
└── deps.py            # get_current_user 已有, 可能加 get_optional_user

tests/
├── test_isolation_kb.py  # KB 隔离测试
├── test_isolation_chat.py  # 聊天隔离测试
└── test_admin_audit.py  # admin 看所有用户的聊天
```

## 验收标准 (主协调会跑)

```bash
# V1: 单元测试
pytest tests/ -v
# 192 + N 全过

# V2: 端到端
# 1. 创 member alice + bob
# 2. alice 创 KB-A (私有)
# 3. bob 创 KB-B (私有)
# 4. alice 看不到 KB-B (404/403)
# 5. bob 看不到 KB-A (404/403)
# 6. alice 把 KB-A 标记 shared
# 7. bob 现在能看到 KB-A
# 8. alice 问 KB-A 一个问题
# 9. bob 问 KB-A 一个问题
# 10. alice GET /chats → 只看到 alice 的
# 11. bob GET /chats → 只看到 bob 的
# 12. admin 看 admin 审计端点 → 都看到 (有 user_id 区分)

# V3: curl 验证
# - POST /api/kbs 不带 owner → 自动用 current user
# - GET /api/kbs/{shared_kb}/chats 返回只有自己
# - GET /api/kbs/{shared_kb}/chats/{other_user_turn} → 404
```

## 不要做

- 不写前端 (Kimi 干)
- 不改路由 path
- 不改认证逻辑
- 不改 LLM client
- 不 push

## 完成后

```bash
pytest tests/ -v  # 必须全过
git add -A
git commit -m "feat(data): user-isolated KB sharing + per-user chat history"
```

## 主协调验收

主协调会:
1. pytest 全过
2. 端到端 12 步
3. 推 Pi (会提示需要重新登录, 因为新逻辑)
4. 提示 Kimi 改前端 (KB 共享切换 UI + 聊天历史按用户分 tab)

START NOW.