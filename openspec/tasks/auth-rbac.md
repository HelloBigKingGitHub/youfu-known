# 用户认证 & 权限模块 Spec

> **任务编号**: auth-rbac
> **派发对象**: Claude Code (后端)
> **状态**: 未开始
> **基于**: 当前 (无认证, 单用户)

## 背景

当前 youfu-known **完全无认证**:
- 任何人访问 https://kb.sxy.homes 直接进 SPA
- API 端点 (`/api/kbs`, `/api/documents` 等) 无任何鉴权
- 数据存储: 所有 KB / 文档 / 问答对所有人都可见可改
- 单用户假设 (你fu 一人用), 但你的反馈是"缺失"

本 spec 设计 **轻量级单用户认证 + RBAC**, 覆盖到能给你基本保护, 不做企业级 SSO。

## 设计目标

### 安全模型

- **单用户**: 系统只有一个管理员账号 (你), 但支持**多个访客账号** (朋友试用)
- **认证**: 用户名 + 密码 (bcrypt 哈希存储)
- **会话**: JWT Token (HttpOnly Cookie, 防 XSS)
- **权限**: 
  - 角色: `admin` (你) / `member` (访客)
  - 资源所有权: KB 有 owner_user_id, 只 owner + admin 能改
  - 文档/问答同理

### 范围 (本次实现)

1. **用户系统**: 注册 / 登录 / 登出 / 修改密码
2. **角色 + 权限**: admin 全权, member 只能看自己 KB + 公共 KB
3. **KB/文档/问答的所有权**
4. **JWT + Cookie 鉴权**
5. **前端登录页 + 鉴权守卫**

### 不在范围 (留作后续)

- 多租户 / 组织
- OAuth (Google/GitHub 登录)
- 2FA / TOTP
- 密码重置邮件
- 操作审计日志 (虽然 spec 提到, 但属于数据层 spec 范围)

## 数据模型

### 1. `users` 表

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    email           TEXT,
    password_hash   TEXT NOT NULL,            -- bcrypt $2b$12$...
    role            TEXT NOT NULL DEFAULT 'member',  -- 'admin' | 'member'
    is_active       BOOLEAN DEFAULT 1,
    is_approved     BOOLEAN DEFAULT 0,        -- admin 创建 member 默认 False, 需 admin 批准
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at   TIMESTAMP
);

CREATE INDEX idx_users_username ON users(username);
```

**重要**:
- `is_approved` 控制 member 是否能登录 (admin 自动 True)
- 初始 admin 账号通过环境变量 `YOUFU_ADMIN_USERNAME` + `YOUFU_ADMIN_PASSWORD` 创建

### 2. `sessions` 表 (可选)

- 如果用 JWT + cookie, **不需要** sessions 表 (token stateless)
- 用 JWT 时, 撤销 token 需要黑名单 (Redis 或 SQLite 表)
- 本次简化: **不存 sessions, JWT 24h 过期 + refresh token 30 天**

### 3. 现有表加 owner

```sql
ALTER TABLE knowledge_bases ADD COLUMN owner_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE knowledge_bases ADD COLUMN is_public BOOLEAN DEFAULT 0;  -- 公共 KB, 所有登录用户可见
ALTER TABLE documents ADD COLUMN owner_id TEXT;  -- 反规范化
ALTER TABLE chat_turns ADD COLUMN user_id TEXT;  -- 哪个人问的问题
```

## API 设计

### 认证 API (`app/api/auth.py`)

```
POST /api/auth/register
    Body: {username, email, password}
    → 创建 member 账号, is_approved=False (需要 admin 批准)
    → 201 {user: {id, username, role: 'member', is_approved: false}}
    → 不自动登录

POST /api/auth/login
    Body: {username, password}
    → 验证, 设置 HttpOnly Cookie 'session_token' (JWT, 24h)
    → 200 {user: {...}, expires_at: "..."}
    → 401 if invalid

POST /api/auth/logout
    → 清除 cookie
    → 204

GET /api/auth/me
    → 当前登录用户
    → 200 {user} or 401

POST /api/auth/change-password
    Body: {old_password, new_password}
    → 验证旧密码, 更新 hash
    → 204

POST /api/auth/refresh
    → 用 refresh token 换新 access token
    → 200 {expires_at}
```

### Admin API (`app/api/admin.py`)

需要 admin role。

```
GET /api/admin/users
    → 列出所有用户

PATCH /api/admin/users/{user_id}
    Body: {is_approved?, role?, is_active?}
    → 更新用户
    → 200 {user}

DELETE /api/admin/users/{user_id}
    → 删除用户 (级联删除其 KB / 文档 / 问答)
    → 204
```

### 修改现有 API

所有现有 API (`/api/kbs`, `/api/documents`, `/api/chats`) 加:
1. **必须登录** (从 cookie 读 JWT)
2. **owner 校验**:
   - admin: 看所有
   - member: 看自己的 KB + is_public=True 的 KB
3. **写操作** (POST/PATCH/DELETE) 必须 owner 或 admin

## 安全机制

### 密码哈希

```python
# 使用 passlib + bcrypt
from passlib.hash import bcrypt

def hash_password(plain: str) -> str:
    return bcrypt.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.verify(plain, hashed)
```

### JWT Token

```python
import jwt
from datetime import datetime, timedelta

SECRET_KEY = settings.jwt_secret  # 从 .env 读
ALGORITHM = 'HS256'

def create_token(user_id: str, role: str, exp_hours: int = 24) -> str:
    payload = {
        'sub': user_id,
        'role': role,
        'exp': datetime.utcnow() + timedelta(hours=exp_hours),
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
```

### Cookie 配置

```python
response.set_cookie(
    key='session_token',
    value=jwt_token,
    httponly=True,         # JS 无法读取, 防 XSS
    secure=True,            # 仅 HTTPS (Cloudflare Tunnel 已配)
    samesite='lax',         # 防 CSRF (基本)
    max_age=86400,          # 24h
    path='/',
)
```

### 初始 Admin 账号

通过环境变量或 CLI 工具创建:

```bash
# scripts/create_admin.sh
#!/usr/bin/env bash
# 读取 .env 的 YOUFU_ADMIN_USERNAME/PASSWORD 创建 admin
# 如果已存在则跳过
```

应用启动时 (在 lifespan 里) 检查: 
- 如果 `users` 表为空 → 自动创建 admin (用 .env)
- 如果 .env 没设 → 打印警告, 启动失败

### CSRF 保护

- SameSite=Lax cookie 防大多数 CSRF
- 写操作 (POST/PATCH/DELETE) 加 X-CSRF-Token header 验证 (token 来自 GET 响应)
- 或: 双 cookie 模式 (CSRF token in non-HttpOnly cookie + header)

本次简化: SameSite=Lax 即可, 后续按需升级。

## 依赖

加 `passlib[bcrypt]` + `python-jose[cryptography]` (或 `PyJWT`):

```toml
# requirements.txt 新增
passlib[bcrypt]==1.7.4
PyJWT==2.9.0
```

## 实现文件

```
app/auth/
├── __init__.py
├── models.py         # User, UserRole enum
├── security.py       # hash_password, verify_password, create_token, decode_token
├── storage.py        # UserStore (类似 SQLiteStorage)
├── deps.py           # FastAPI Depends: get_current_user, require_admin
└── service.py        # AuthService (业务逻辑: register, login, etc.)

app/api/auth.py       # 登录/注册/登出 endpoints
app/api/admin.py      # admin 用户管理 endpoints

scripts/
└── create_admin.sh   # 初始 admin 创建

tests/
├── test_auth.py      # 登录/注册/密码/Token 测试
├── test_rbac.py       # 权限/所有权 测试
└── test_api.py        # 现有 (更新以适应认证)
```

## Pydantic Models

```python
class UserRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"

class User(BaseModel):
    id: str
    username: str
    email: str = ""
    role: UserRole
    is_active: bool = True
    is_approved: bool = False
    created_at: datetime
    last_login_at: Optional[datetime] = None

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r'^[a-zA-Z0-9_-]+$')
    email: str = Field(default="", pattern=r'^$|^[\w.+-]+@[\w-]+\.[\w.-]+$')
    password: str = Field(min_length=8)

class UserLogin(BaseModel):
    username: str
    password: str

class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)

class UserUpdate(BaseModel):
    is_approved: Optional[bool] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
```

## 前端集成 (后续 spec, 不在范围)

仅说明, 后续派前端 agent:

- 新页面 `/login`
- Axios/Fetch 加 `credentials: 'include'` 带 cookie
- React Router 加 `<RequireAuth>` 守卫
- 侧栏顶部加用户菜单 (登出)

## 验收标准 (主协调会跑)

```bash
# V1: 单元测试
pytest tests/test_auth.py tests/test_rbac.py -v
# 必须全过

# V2: e2e 流程
# 1. 用 .env 里的 admin 登录 → 200, cookie 设置
# 2. 创建一个新 member → is_approved=false
# 3. 用未批准 member 登录 → 401
# 4. admin 批准该 member
# 5. member 重新登录 → 200
# 6. member 创建 KB → 201
# 7. member 看 admin 的 KB → 403 (admin 默认 KB is_public=False)
# 8. admin 把 KB 设 is_public → member 能看

# V3: 现有 71 测试
# 全部适配认证 (测试里 mock 登录)

# V4: curl 验证 API
curl -X POST -d '{"username":"admin","password":"***"}' /api/auth/login -c cookie.txt
curl /api/kbs -b cookie.txt  # 200
curl /api/kbs  # 401

# V5: build (前端无改动, 不需要)
```

## 配置更新

`.env.example`:

```bash
# 新增
YOUFU_JWT_SECRET=*** # openssl rand -hex 32)
YOUFU_ADMIN_USERNAME=admin
YOUFU_ADMIN_PASSWORD=***  # 启动时自动创建 admin 账号
YOUFU_COOKIE_SECURE=true   # 生产环境 true (HTTPS), dev false
YOUFU_SESSION_HOURS=24
```

`config.yaml`:

```yaml
auth:
  jwt_secret_env: YOUFU_JWT_SECRET
  admin_username_env: YOUFU_ADMIN_USERNAME
  admin_password_env: YOUFU_ADMIN_PASSWORD
  cookie_secure_env: YOUFU_COOKIE_SECURE
  session_hours: 24
  bcrypt_rounds: 12
```

## 不要做

- ❌ 不写前端代码 (登录页派给前端)
- ❌ 不做 SSO / OAuth
- ❌ 不做 2FA
- ❌ 不做邮件密码重置
- ❌ 不加企业级审计

## 完成后

```bash
pytest tests/ -v  # 必须全过 (71 旧 + N 新)
git add -A
git commit -m "feat(auth): 用户认证 + RBAC (admin/member) + JWT cookie"
```

## 主协调验收

主协调会:
1. pytest 71+N 全过
2. e2e 流程 (8 步)
3. curl API 测试 (401/403/200)
4. 不通过 → 重派 / 通过 → 推 Pi (会提醒你设 .env 新变量)

START NOW.