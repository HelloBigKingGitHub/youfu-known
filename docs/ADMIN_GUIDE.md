# youfu-known · 后台管理端 操作手册

单管理员 + 多访客场景的后台管理操作手册（admin console）。
本文档配套 `docs/deploy.md`（部署 / 运维 / 故障排查）使用。

## 目录

0. [简介](#0-简介)
1. [快速开始](#1-快速开始)
2. [用户管理（AdminUsersPage）](#2-用户管理adminuserspage)
3. [API 完整列表](#3-api-完整列表-3-endpoints)
4. [常见错误](#4-常见错误)
5. [故障排查](#5-故障排查)
6. [测试](#6-测试)
7. [部署 URL](#7-部署-url)

---

## 0. 简介

后台管理端（admin console）面向 **单管理员** + **多访客** 场景：管理员可注册时自动成为 `admin`，
访客通过 `POST /api/auth/register` 注册后进入"待批准"状态，需管理员在 `/admin/users` 页面审批。

**当前覆盖范围**（基于 commit `3248495`）：

| 测试套件 | 数量 | 覆盖范围 |
|---|---|---|
| pytest 单元 | 219 passed | 全部 backend 含 `tests/test_admin_api.py` (8) |
| pytest 集成 | 1 passed | `tests/integration/test_admin_lifespan.py`（端到端 + Round 2 抓 P5b/P8a） |
| vitest 单元 | 13 passed | 含 `AdminUsersPage.test.tsx` (5) + `apiErrors.test.ts` (8) |
| Playwright e2e | 2 passed + 1 skipped | `web/tests/e2e/admin.spec.ts` |

**当前生产部署**：<https://kb.sxy.homes/admin/users>

---

## 1. 快速开始

### 1.1 后端：admin 账号初始化（lifespan bootstrap）

后端启动时（`main.py` lifespan → `auth_service.bootstrap_admin_if_empty()`）会自动判断是否需要创建初始 admin：

| 启动时状态 | 行为 |
|---|---|
| `users` 表空 + `YOUFU_ADMIN_USERNAME` / `YOUFU_ADMIN_PASSWORD` 都设了 | 创建 admin（`role=admin`, `is_approved=true`, `is_active=true`） |
| `users` 表空 + env var 缺失 | 打 warning 日志，**不**创建（须手动设 env 后重启） |
| `users` 表已有 admin | 跳过（idempotent，**不**重复创建） |

#### 环境变量（`.env` 或部署 env var）

```bash
# JWT 签名密钥 (生产请用: openssl rand -hex 32)
YOUFU_JWT_SECRET=<random-32-byte-hex>

# 启动时自动创建的初始 admin 账号
YOUFU_ADMIN_USERNAME=admin            # 默认 admin
YOUFU_ADMIN_PASSWORD=<strong-pw>      # 必设，无 default

# Cookie Secure flag: 生产 (HTTPS) = true; 本地 HTTP dev = false
YOUFU_COOKIE_SECURE=false

# Access / Refresh token 有效期
YOUFU_SESSION_HOURS=24
YOUFU_REFRESH_DAYS=30

# bcrypt cost factor (默认 12，不要低于 10)
YOUFU_BCRYPT_ROUNDS=12
```

⚠️ **`YOUFU_JWT_SECRET` 没设时**：admin login 会失败（JWT 签发 / 验证都失败）。
首次启后端必须**同时**设 `YOUFU_ADMIN_PASSWORD` 和 `YOUFU_JWT_SECRET`。

⚠️ **`YOUFU_ADMIN_PASSWORD` 没设但 `YOUFU_ADMIN_USERNAME=admin`**：lifespan 打 warning 跳过，
新部署需要停服 → 设 env → 删 `storage/users.db` 重建（或手动 SQL 改 role）。

### 1.2 前端：访问入口

**管理员入口**：右上角 user menu（avatar + username "admin"）→ `用户管理`。
仅当 `user.role === 'admin'` 时渲染（`TopBar.tsx` 第 119 行条件）。

| 部署 | URL |
|---|---|
| 本地（Vite dev） | <http://localhost:5173/admin/users> |
| 生产（Cloudflare Tunnel） | <https://kb.sxy.homes/admin/users> |

`/admin/users` 路由由 `web/src/App.tsx` 挂载（仅 admin 可见），
组件 `AdminUsersPage.tsx` 渲染时自动调 `GET /api/admin/users`。

### 1.3 第一次登录流程（本地）

```bash
# 1. 启后端 (uvicorn 在 8765)
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8765

# 2. 启前端 (Vite dev 反代 8765)
cd web && npm run dev    # 默认 http://localhost:5173

# 3. 浏览器访问 /login, 用 .env 配的 YOUFU_ADMIN_USERNAME / YOUFU_ADMIN_PASSWORD 登录
# 4. 右上角 user menu → "用户管理"  → /admin/users
```

---

## 2. 用户管理（AdminUsersPage）

UI 实现：`web/src/components/AdminUsersPage.tsx`（263 行，Chakra UI）。
数据来源：`GET /api/admin/users`（一次性 fetch，**前端** filter / 操作）。

### 2.1 表格列（真实渲染）

| 列 | 内容 | 来源字段 |
|---|---|---|
| 用户名 | username | `User.username` |
| 邮箱 | email（空 → `-`） | `User.email` |
| 角色 | Badge（admin=紫色 / member=灰色） | `User.role` |
| 状态 | 1~2 个 Badge 组合（见下表） | `User.is_approved` + `User.is_active` |
| 操作 | 4 个 Button（见 §2.3-2.6） | — |

**状态 Badge 颜色（实测 `AdminUsersPage.tsx` 第 202-211 行）**：

| 条件 | Badge 文字 | 颜色 |
|---|---|---|
| `is_approved === true` | `已批准` | green |
| `is_approved === false` | `待批准` | yellow |
| `!is_active`（叠加） | `已禁用` | red |

> 注：操作按钮的"启用/禁用"在 `isSelf(u) === true` 时强制 disabled（即 admin 不能禁自己）。
> 同样，"降为 member" 与 "删除" 也对 self 禁用（双重防御：UI + 后端 `CannotDemoteSelfError`）。

### 2.2 搜索（前端 filter，不调后端）

```tsx
// AdminUsersPage.tsx 第 62-66 行
const filtered = users.filter(
  (u) =>
    u.username.toLowerCase().includes(search.toLowerCase()) ||
    (u.email || '').toLowerCase().includes(search.toLowerCase()),
)
```

- placeholder 文字：`搜索用户名或邮箱`（**前端** 字符串匹配，**不**调 `GET /api/admin/users?search=`）
- 实时 filter，无防抖（数据规模 < 100 时无感知）
- 测试：`AdminUsersPage.test.tsx::test_renders_user_table_with_search`

### 2.3 批准 user（待批准 → 已批准）

仅当 `!u.is_approved` 时渲染该按钮（绿色 `批准`）。

```typescript
await api.adminUpdateUser(userId, { is_approved: true })
```

**前端反馈**（`useToast`）：
- 成功：`{title: "${u.username} 已批准", status: 'success', duration: 2000}`
- 失败：title=批准失败，description=`formatApiError(e, '操作失败')`

### 2.4 改 role（member ↔ admin）

```typescript
await api.adminUpdateUser(userId, { role: 'member' })   // 降
await api.adminUpdateUser(userId, { role: 'admin' })    // 提
```

按钮文字根据当前 role 切换（`降为 member` / `提为 admin`），对 `isSelf(u)` disabled。

### 2.5 启用 / 禁用（toggle is_active）

```typescript
await api.adminUpdateUser(userId, { is_active: !u.is_active })
```

按钮文字根据当前 `is_active` 切换（`禁用` / `启用`），对 `isSelf(u)` disabled。
后端 `is_active=false` 后，用户立即无法登录（`get_current_user` 在 `deps.py:80` 拒绝）。

### 2.6 删除 user（CASCADE，不可逆）

```typescript
// 前端: window.confirm("确定删除用户 X? 不可恢复。") → await api.adminDeleteUser(userId)
await api.adminDeleteUser(userId)
```

**后端 cascade 行为**（`app/api/admin.py:103-140` `delete_user`）：

1. 取出 `kb_service` + `storage` 引用
2. 用 `UserStore.list_kbs_visible_to(user_id, is_admin=True)` 列出 user 名下的 KB
3. 对每个 KB 调 `kb_service.delete_kb(kb_id)`（best-effort，失败仅 logger.exception 不 raise）
4. 调 `svc.delete_user(acting_user_id=admin.id, target_user_id=user_id)`
5. SQLite `users` 行由 `UserStore.delete_user` 删除；FK `ON DELETE CASCADE` 联动 `knowledge_bases` / `documents` / `chats` / `chat_turns` 行

⚠️ **不可逆**。admin 不能删自己（UI disabled + 后端 `CannotDemoteSelfError("cannot delete yourself")`）。

---

## 3. API 完整列表（3 endpoints）

路由定义：`app/api/admin.py`（143 行）。Auth：`require_admin` dependency
（`app/auth/deps.py:117`，`role != admin` → HTTP 403 `admin role required`）。

Envelope（`app/api/__init__.py`）：
- 成功：`{"code": 0, "data": <payload>}`
- 失败：`{"code": <int>, "message": <str>}`（FastAPI `HTTPException(detail=...)` 经全局处理器包成此形）

### 3.1 `GET /api/admin/users`

列所有 user（含 admin / member / 待批准 / 已禁用）。

**Headers**：`Authorization: Bearer <access_token>`（JWT from `/api/auth/login`）
**Required role**：`admin`
**Response 200**：

```json
{
  "code": 0,
  "data": [
    {
      "id": "1b18ac9fd7ad4d43acf67bb554779fc7",
      "username": "admin",
      "email": "",
      "role": "admin",
      "is_active": true,
      "is_approved": true,
      "created_at": "2026-07-24T14:48:45",
      "last_login_at": "2026-07-29T07:42:56"
    }
  ]
}
```

**Errors**：

| Status | Code | Detail |
|---|---|---|
| 401 | `not authenticated` / `invalid or expired session` | 缺 token / JWT 无效 |
| 403 | `admin role required` | 非 admin 调用 |

### 3.2 `PATCH /api/admin/users/{user_id}`

更新 user 字段。所有字段 optional，`None` 表示"不改"。

**Request body**（`UserUpdate` schema）：

```json
{
  "is_approved": true,
  "role": "member",
  "is_active": true,
  "email": "new@x.com"
}
```

**Response 200**：返回更新后的 `User` payload（同 §3.1 列表项 schema）。

**Errors**：

| Status | 触发条件 |
|---|---|
| 404 `UserNotFoundError` | `user_id` 不存在（`app/auth/service.py:51-52`） |
| 400 `CannotDemoteSelfError` (`"cannot remove your own admin role"`) | admin 改自己的 `role != admin` |
| 401 / 403 | 同 §3.1 |

> **注意**：admin **不**能改自己的 `is_active=false`（UI 禁用）+ 后端**没**显式禁止（仅靠前端保险）。
> 真要禁自己，必须先**手动 SQL** 改另一个账号为 admin，再让那个 admin 禁你。

### 3.3 `DELETE /api/admin/users/{user_id}`

Cascade 删除 user + KB + docs + chats（详见 §2.6）。

**Response 200**：

```json
{
  "code": 0,
  "data": {
    "deleted": "1b18ac9fd7ad4d43acf67bb554779fc7",
    "existed": true
  }
}
```

**Errors**：

| Status | 触发条件 |
|---|---|
| 404 `UserNotFoundError` | `user_id` 不存在 |
| 400 `CannotDemoteSelfError` (`"cannot delete yourself"`) | admin 试图删自己 |
| 401 / 403 | 同 §3.1 |

### 3.4 curl 示例

```bash
# 1. admin login 拿 token
TOKEN=$(curl -s -X POST http://127.0.0.1:8765/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' \
  | jq -r '.data.access_token')

# 2. list users
curl -s http://127.0.0.1:8765/api/admin/users \
  -H "Authorization: Bearer $TOKEN" | jq

# 3. approve a pending user
USER_ID=...
curl -s -X PATCH "http://127.0.0.1:8765/api/admin/users/$USER_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_approved": true}' | jq

# 4. delete a user (慎用!)
curl -s -X DELETE "http://127.0.0.1:8765/api/admin/users/$USER_ID" \
  -H "Authorization: Bearer $TOKEN" | jq
```

完整 OpenAPI：`http://127.0.0.1:8765/docs`（Swagger UI）。

---

## 4. 常见错误

### 4.1 `404 UserNotFoundError`

**复现**：`PATCH /api/admin/users/nonexistent`
**报错**：

```json
{"code": 404, "message": "user not found: nonexistent"}
```

**修复**：

1. 调 `GET /api/admin/users` 列出现有 user 拷贝正确 `id`（32-char hex）
2. 检查 user 是否被前一步 `DELETE` 误删
3. 若是从前端报：检查 `u.id` 是否仍是 stale 状态（AdminUsersPage 没刷新表格）

### 4.2 `400 CannotDemoteSelfError`（改 role）

**复现**：admin 用自己的 token `PATCH /api/admin/users/<self_id> {"role":"member"}`
**报错**：

```json
{"code": 400, "message": "cannot remove your own admin role"}
```

**修复**：这是**预期**行为（防误锁）。Workaround：

- 找**另一个** admin（生产环境一般没有，单 admin 设计）
- 或者：用 SQLite 工具手动 `UPDATE users SET role='admin' WHERE username='other_user';` 然后让那个 user 帮你降权

### 4.3 `400 CannotDemoteSelfError`（删自己）

**复现**：admin `DELETE /api/admin/users/<self_id>`
**报错**：

```json
{"code": 400, "message": "cannot delete yourself"}
```

**修复**：用**另一个** admin 操作；或直接停服 → 删 `storage/users.db` 重建。

### 4.4 `403 require_admin`

**复现**：member 用 token `GET /api/admin/users`
**报错**：

```json
{"code": 403, "message": "admin role required"}
```

**修复**：

1. 用 admin 凭证重新 `POST /api/auth/login` 拿新 token
2. 确认 JWT `sub` 对应 user 的 `role === 'admin'`（`UserStore.get_user(id).role`）
3. 确认 token 没过期（`YOUFU_SESSION_HOURS=24`，可查 JWT `exp` claim）

### 4.5 `401 not authenticated`

**复现**：`curl -X GET http://127.0.0.1:8765/api/admin/users`（无 Authorization）
**报错**：

```json
{"code": 401, "message": "not authenticated"}
```

**修复**：先 `POST /api/auth/login` 拿 `access_token`，再加 `Authorization: Bearer <token>` header。
前端 cookie 路径会自动带 `session_token`，浏览器 fetch 默认 OK。

### 4.6 `401 invalid or expired session`

**复现**：用了过期的 access_token（> `YOUFU_SESSION_HOURS`）
**报错**：

```json
{"code": 401, "message": "invalid or expired session"}
```

**修复**：

- 用 `refresh_token` 调 `POST /api/auth/refresh` 换新 access + refresh pair
- 前端 `api.ts` 自动处理 401 refresh 重试（确认 token store 已登出 / 重新登录）

---

## 5. 故障排查

### 5.1 admin login 失败（401 invalid credentials）

**Root cause**：env var 缺失 / 拼错 / bcrypt hash 不一致。
**排查步骤**：

```bash
# 1. 检查后端 env
grep -E "^YOUFU_ADMIN_(USERNAME|PASSWORD)|^YOUFU_JWT_SECRET" /home/youfu/projects/youfu-known/.env

# 2. 检查后端日志 (uvicorn)
sudo journalctl -u youfu-known -n 50 | grep -i "admin\|jwt\|bootstrap"

# 3. 验证后端 alive
curl -s http://127.0.0.1:8765/api/health
# → {"code":0,"data":{"status":"ok",...}}

# 4. 直接 SQL 查 user 表
sqlite3 storage/users.db "SELECT id, username, role, is_active, is_approved FROM users;"
```

**修复**：

- `YOUFU_JWT_SECRET` 没设 → `openssl rand -hex 32` 生成并写入 `.env` → 重启
- `YOUFU_ADMIN_PASSWORD` 改了但 users 表里的 bcrypt hash 还是旧密码 → 重新启 lifespan
  会用**新** password 覆盖 admin（仅当 users 表空的情况，否则跳过）

### 5.2 Vite 反代 `/api/auth/login` 返 404

**Root cause**：`web/vite.config.ts` 的 `YOUFU_VITE_API_TARGET` 配错端口。
**默认**：8000；本地 dev 一般用 8765（uvicorn 显式 `--port 8765`）。

**修复**：

```bash
# web/.env (或 .env.local)
YOUFU_VITE_API_TARGET=http://127.0.0.1:8765

# 重启 vite
cd web && npm run dev
```

**验证**：

```bash
curl -s -X POST http://localhost:5173/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}'
# 应返回 200 + {"code":0,...}
```

### 5.3 admin bootstrap 失败（first start + users 表已有 user）

**场景**：`storage/users.db` 是从**无认证**的旧版本升级而来，已有 user 但都不是 admin。
**行为**：`bootstrap_admin_if_empty()` 看到 `count() > 0` 立即 `return None`，**不**创建新 admin。
**修复**：

```bash
# 选项 A: SQL 手动提权 (找最信赖的 user)
sqlite3 storage/users.db "UPDATE users SET role='admin' WHERE username='your_user';"

# 选项 B: 删 users 表让 bootstrap 重新跑 (慎用! 所有 user / KB 都没了)
sudo systemctl stop youfu-known
rm storage/users.db
sudo systemctl start youfu-known    # 重新创建 admin
```

### 5.4 P5b / P8a lifespan idempotent fail（重复启 crash）

**Root cause**：lifespan 第二次启时，已 enable 的 `LogStore` / `HistoryStore` 再次 enable → `RuntimeError`。
**状态**：已修（commit `3c9f275` + 阶段 4 idempotent fix）。
**验证**：

```bash
.venv/bin/python -m pytest tests/integration/test_admin_lifespan.py -v
# 1 passed
```

测试逻辑（`tests/integration/test_admin_lifespan.py`）：
- Round 1：启 `create_app()` → 调 lifespan → admin login → create member → approve → 关闭
- Round 2：同一 on-disk DB 上**再启一次** → admin login 仍成功 → 验证 P5b/P8a 不复发

### 5.5 误删 admin 账号

**Root cause**：`DELETE /api/admin/users/<admin_id>`（虽然有 self-delete 防护，但若是 admin
通过 SQL 改了 role 就能删自己）。
**修复**：

```bash
sudo systemctl stop youfu-known
sqlite3 storage/users.db "INSERT INTO users (id, username, password_hash, role, is_active, is_approved, created_at) VALUES (lower(hex(randomblob(16))), 'admin', '<bcrypt_hash>', 'admin', 1, 1, datetime('now'));"
sudo systemctl start youfu-known

# 或最简单: 让 bootstrap 重新跑
sudo systemctl stop youfu-known
rm storage/users.db
sudo systemctl start youfu-known    # 需 .env 配 YOUFU_ADMIN_USERNAME/PASSWORD
```

> bcrypt hash 生成：`python -c "from app.auth.security import hash_password; print(hash_password('YOUR_NEW_PASSWORD'))"`

---

## 6. 测试

### 6.1 后端单元测试（pytest）

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/test_admin_api.py` | 8 | GET / PATCH（approve + change role + cannot demote self + 404）/ DELETE（cascade）/ RBAC 403 |

### 6.2 后端集成测试

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/integration/test_admin_lifespan.py` | 1 | 端到端：admin login → create member → approve → **再启 Round 2** 抓 P5b/P8a |

### 6.3 前端单元测试（vitest）

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `web/src/lib/apiErrors.test.ts` | 8 | `formatApiError` / `extractFieldErrors` / `isLoginCredentialError` |
| `web/src/components/AdminUsersPage.test.tsx` | 5 | 加载 / 搜索 / 批准 / 改 role / 删除 |

### 6.4 前端端到端测试（Playwright）

`web/tests/e2e/admin.spec.ts`（3 测试）：

| 测试 | 状态 | 备注 |
|---|---|---|
| `admin login + navigate to /admin/users` | ✅ passed | 登录 → 右上 user menu → `用户管理` |
| `admin search filters user list` | ✅ passed | 输入 `admin` → row 数 ≤ 初始 |
| `admin approve pending user` | ⏭️ skipped | DB 无 pending user（register API 受 Turnstile 拦，无 test data） |

### 6.5 跑全量

```bash
# 后端单元 + 集成
cd /home/youfu/projects/youfu-known
.venv/bin/python -m pytest tests/ -q                  # 219 passed (含 1 integration)

# 前端单元 (vitest)
cd web && npm test                                     # 13 passed

# 前端 e2e (Playwright)
cd web && npx playwright test                          # 2 passed, 1 skipped
```

---

## 7. 部署 URL

| 部署 | URL | 备注 |
|---|---|---|
| 本地（Vite dev） | <http://localhost:5173/admin/users> | 需 `web/.env` 配 `YOUFU_VITE_API_TARGET=http://127.0.0.1:8765` |
| 生产（Cloudflare Tunnel） | <https://kb.sxy.homes/admin/users> | SSH tunnel 才能从本机访问；生产强制 HTTPS |
| 后端（uvicorn） | <http://127.0.0.1:8765> | API 端，**不**直接浏览器访问（用 `/docs` 看 Swagger） |
| 后端 Swagger | <http://127.0.0.1:8765/docs> | OpenAPI UI（生产建议内网访问） |

> **提醒**：每次改完部署 / 域名，**必须**更新本节 URL 表（与 `docs/deploy.md` 同步）。
> 跟 32 commits DDD + verifies skill 一致：URL 漂移是高频技术债。

---

## 关联

- `docs/deploy.md` — 部署 / 运维 / 故障排查（与本文档同款结构）
- `openspec/tasks/auth-rbac.md` — 后台管理核心 spec（状态：✅ 已完成，commit `06f0521`）
- `app/api/admin.py` — 3 endpoints 真实实现（143 行）
- `app/auth/service.py` — `AuthService.bootstrap_admin_if_empty()` / `update_user()` / `delete_user()`
- `app/auth/deps.py` — `require_admin` / `get_current_user` / `require_approved` dependency
- `web/src/components/AdminUsersPage.tsx` — UI 实现（263 行）
- `web/src/components/TopBar.tsx` — admin 入口（`MenuItem "用户管理"` 第 119-126 行）
- `verifies skill v1.0` — `~/.hermes/skills/verifies/`（15 decision tree rules + 10 incident postmortem）

## 变更记录

| 版本 | 日期 | commit | 内容 |
|---|---|---|---|
| v0.7.0-dev | 2026-07-29 | `3248495` | 初版（阶段 6 任务，5 阶段测试收尾后的运维手册） |