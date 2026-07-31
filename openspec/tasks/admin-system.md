# 后台管理系统 Phase 1

> **任务编号**: admin-system-phase-1  
> **派发对象**: Claude Code (后端 + 兼任前端 admin-web)  
> **状态**: ✅ 已完成 (Phase 1: 11 commits + Phase 1.5: 1 commit, 前台 AdminUsersPage 已删, 整合到 admin.sxy.homes /admin/users)  
> **依据**: 你 (主协调) 拍板的 4 个决策  
> **基于**: 当前 main 分支

## 决策回顾

1. **B 独立后台 SPA** → 实现: `admin-web/` Vite + React 子项目
2. **按建议来** → Phase 1: Dashboard + KBs + Audit + Settings
3. **加 Recharts** (新依赖, 用于统计图表)
4. **拆子路由**: `/admin/login`, `/admin/dashboard`, `/admin/kbs`, `/admin/audit`, `/admin/settings`

**域名**: `admin.kb.sxy.homes` (你要的)

## 工程目录

新增 `admin-web/` 子项目在仓库根:
```
admin-web/
├── src/
│   ├── App.tsx
│   ├── main.tsx
│   ├── api.ts                    # fetch wrapper with credentials: 'include'
│   ├── layouts/
│   │   ├── AdminLayout.tsx       # 左导航 (4 菜单) + 顶部 admin user + 登出
│   │   └── AuthLayout.tsx
│   ├── lib/
│   │   └── format.ts             # 数字/日期格式化
│   ├── pages/
│   │   ├── Login.tsx             # admin 登录 (复用 JWT cookie)
│   │   ├── Dashboard.tsx         # 4-6 张 stat card + Recharts 图
│   │   ├── KBs.tsx               # Chakra Table, owner 列, 删除按钮
│   │   ├── Audit.tsx             # Table + filter (type/user/date)
│   │   └── Settings.tsx          # 表单 (env 字段)
├── package.json
├── vite.config.ts                # dev :5174, proxy /api → :8000
├── tsconfig.json
├── index.html
└── .env                          # (可选) VITE_API_TARGET
```

## Phase 1 后端 (app/admin/)

```
app/admin/
├── __init__.py
├── dashboard.py     # GET /api/admin/dashboard
├── kbs.py           # GET /api/admin/kbs, DELETE /api/admin/kbs/{id}
├── audit.py         # GET /api/admin/audit?limit=N
├── settings.py      # GET / PATCH /api/admin/settings
└── stats.py         # 统计工具函数

main.py: 注册 4 个新 router
```

## Phase 1 后端 API

### 1. GET /api/admin/dashboard

返回系统统计:
```json
{
  "code": 0,
  "data": {
    "kbs": {"total": 1, "shared": 0, "private": 1},
    "users": {"total": 1, "approved": 1, "pending": 0},
    "documents": {"total": 2, "by_status": {"ready": 2, "processing": 0, "failed": 0}},
    "chunks": 7115,
    "chat_turns_24h": 3,
    "storage_bytes": 12345678,
    "llm_calls_24h": 3,
    "uploaded_24h": 0
  }
}
```

**实现**: SQL aggregate + count + last 24h filter

### 2. GET /api/admin/kbs

返回所有 KB (跨用户), 含 owner + 统计:

```sql
SELECT kb.*, u.username as owner_username
FROM knowledge_bases kb
LEFT JOIN users u ON kb.owner_id = u.id
ORDER BY kb.created_at DESC
```

返回 `[{id, name, owner_id, owner_username, is_shared, is_public, doc_count, chunk_count, created_at}]`

### 3. DELETE /api/admin/kbs/{id}

admin 强制删除 (跨用户), 含 FK CASCADE (already)

### 4. GET /api/admin/audit?limit=N

最近 N 条操作日志 (登录/上传/聊天/删除/失败), 简化版:
```json
{
  "data": [
    {"id": "...", "type": "login", "user_id": "...", "username": "admin", "detail": {"ip": "1.2.3.4"}, "created_at": "..."},
    {"id": "...", "type": "chat", "user_id": "...", "kb_id": "...", "question": "...", "created_at": "..."},
    ...
  ]
}
```

**来源**: 直接从 chat_turns 表 + auth 登录日志 (加新的 audit_log 表为佳, 但 Phase 1 用现有数据近似)

### 5. GET / PATCH /api/admin/settings

GET: 返回当前 settings (脱敏 - 不返回 secrets)
PATCH: 修改 runtime config 字段 (改内存, 重启失效 - Phase 1 不持久化)

支持字段:
- `model_name`: LLM 模型 (默认 `MiniMax-Text-01`)
- `embedding_batch_size` (默认 10)
- `chunk_size` (默认 1000)
- `chunk_overlap` (默认 200)
- `max_upload_size_mb` (默认 50)

## 后端 CORS (跨子域必需)

`app/api/__init__.py` 加:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kb.sxy.homes",        # 主页
        "https://admin.kb.sxy.homes",   # 后台
        "http://localhost:5174",        # 本机 admin dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

注意: `allow_credentials=True` + `allow_origins=["*"]` 不行, 必须白名单。

## Cookie 改成可跨子域

`app/auth/security.py`:
```python
response.set_cookie(
    ...,
    samesite='none' if secure else 'lax',  # 跨子域必须 None
    secure=True,                            # HTTPS 必须
)
```

**警告**: 改 samesite 影响现有用户, 主协调发布后需 invalidate cookie。Phase 1 完成时一并换。

## 主页 SPA 跳转链接

`web/src/components/TopBar.tsx` 用户菜单 (admin role only):
```tsx
{user.role === 'admin' && (
  <>
    <MenuDivider />
    <MenuItem
      icon={<ExternalLinkIcon />}
      onClick={() => window.open('https://admin.kb.sxy.homes', '_blank')}
    >
      进入管理后台
    </MenuItem>
  </>
)}
```

## Cloudflare Tunnel 配置

`~/.cloudflared/config.yml` 改:
```yaml
tunnel: youfu-tunnel-id
credentials-file: /home/youfu/.cloudflared/<id>.json

ingress:
  - hostname: kb.sxy.homes
    service: http://127.0.0.1:8000
  - hostname: admin.kb.sxy.homes
    service: http://127.0.0.1:8000  # 同一后端, CORS 路由
  - service: http_status:404
```

**主页 SPA + 后台都路由到同一后端 8000**。CORS 让 admin.kb.sxy.homes 浏览器能调 kb.sxy.homes 的 cookie (反之亦然)。

## admin-web Vite 配置

`admin-web/vite.config.ts`:
```ts
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,  # dev 用
      },
    },
  },
})
```

**dev**:
- 你fu-known 主页 SPA 跑 5173
- admin-web 跑 5174
- 都 proxy 到 Pi 8000 (or 本机 8000)

**生产**:
- `npm run build` → `admin-web/dist/`
- Pi 上 `nginx` 或 `caddy` 反代:
  - `admin.sxy.homes` (实际) → `/admin-web/dist/index.html`
  - `/api/*` (admin 子域) → backend 8000
- 或更简单: 主页 SPA build 时注入一个 `<iframe>` 标签, 但你说 B (独立) 就用 nginx/caddy

## Phase 1 必须有

| 项 | 后端 | 前端 |
|---|---|---|
| Dashboard | stats.py (SQL 聚合) | Recharts (4-6 张图) |
| KBs | kbs.py (跨用户查询) | Chakra Table (含删除) |
| Audit | audit.py (chat + login 日志) | Chakra Table (filter) |
| Settings | settings.py (Pydantic) | 表单 (env 字段) |

## 实施步骤

1. 看现状 (`app/api/admin.py` 现有, `main.py` 注册)
2. **后端**:
   - 改 app/api/admin.py + 新 stats.py 等
   - app/api/__init__.py 加 CORS
   - main.py 注册新 router + CORS middleware
   - app/auth/security.py 改 cookie samesite
3. **新建 admin-web/**: Vite + React + Chakra + Recharts
4. **接**: 主页 TopBar admin-only 加跳转链接
5. cd admin-web && npm install && npm run build (0 错误)
6. 跑 4 个页面的 e2e (curl + chromium screenshot)

## 验收标准

```bash
# 1. 后端
pytest tests/ -v
# 192 + N 全过

# 2. 后台构建
cd admin-web && npm run build  # 0 错误

# 3. e2e: 看 Chrome
# 访问 https://admin.kb.sxy.homes → admin 登录页
# 登录 → Dashboard 显示统计 (4 个 KB + 2 用户)
# KBs 列表显示全部, admin 能删任意 KB
# Audit 显示最近活动
# Settings 改 model_name → 重启生效

# 4. 主页 admin 登录 → 看到"进入管理后台" 菜单项
```

## 硬约束

1. **不破坏主页** — 主页 5173 / kb.sxy.homes 不变形
2. **复用 cookie** — admin-web 用 jwt cookie, 不重新登录
3. **后端代码不能破坏** — 192 个旧测试全过
4. **新依赖**: admin-web 可以加 Recharts (admin-web 独立 package.json)
5. **主页 SPA 不加新依赖** — 主页只加跳转菜单项

## 不准做

- ❌ 不重构主页代码 (只加跳转链接)
- ❌ 不加 OAuth / SSO (Phase 1 只支持 admin 登录)
- ❌ 不加邮件通知 / webhook
- ❌ 不改后端业务逻辑
- ❌ 不 push 主页 main 到 Cloudflare (那个是用户自己操作)

## 完成后

```bash
# admin-web/ 不需要 build push (独立 SPA)
git add admin-web/ openspec/tasks/admin-system.md
git commit -m "feat(admin): Phase 1 admin system (Dashboard + KBs + Audit + Settings)"
git push origin main
```

但 **admin-web/ 不能直接 push 到 GitHub Pages** — 它需要单独部署 (Pi nginx 或 Claude Tunnel 升级)。

主协调 (我) 会:
1. 跑 V1-V5 验收
2. rsync admin-web/dist/ 到 Pi nginx 路径
3. 启动 nginx (主协调后续)
4. 验证 https://admin.kb.sxy.homes 通

## 主协调验收

主协调 (我) 会:
1. 后端 pytest 全过
2. admin-web build 0 错误
3. chromium 截 4 个页面
4. Curl 触发每个 endpoint
5. 推 Pi 后 nginx
6. 通知用户

START NOW.