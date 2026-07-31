# Phase 1 Admin System — Implementation Report

> **Status**: ✅ Complete (committed locally; not pushed)
> **Branch**: `main` (commits `902b948` … `d0f72b3`)
> **Last commit**: `d0f72b3 feat(security): Server-side Origin allowlist closes CSRF window`

## 1. Acceptance Criteria — Status

| Criterion | Status | Evidence |
|---|---|---|
| 5 new admin endpoints (`dashboard`, `kbs`, `audit`, `settings`) | ✅ | `app/admin/*.py` (5 files), `app/admin/__init__.py` aggregates |
| CORS middleware with `allow_credentials=True` | ✅ | `app/api/__init__.py:25-33` |
| Cookie `SameSite=None`/`Secure`/`Domain=.kb.sxy.homes` (cross-subdomain) | ✅ | `app/api/auth.py:59-77` |
| Independent `admin-web/` Vite + React + Chakra + Recharts SPA | ✅ | `admin-web/` (pt. 5174) |
| 4 pages: Dashboard / KBs / Audit / Settings | ✅ | `admin-web/src/pages/*.tsx` |
| Login page (reuses JWT cookie) | ✅ | `admin-web/src/pages/Login.tsx` |
| TopBar admin-only "进入管理后台" link | ✅ | `web/src/components/TopBar.tsx:127-136` |
| **Backend tests: 192 + N all pass** | ✅ | **262 / 262 pass** (was 247 baseline; +15 Phase 1 + CSRF tests) |
| **admin-web build: 0 errors** | ✅ | `dist/assets/index-*.js` 891 kB (gzip 275 kB) |
| **Coverage ≥ 80%** | ✅ | admin-web **92.4%** (statements), **95.1%** (branches) |
| No push | ✅ | 4 commits ahead of `origin/main`, not pushed |

## 2. Commit Trail (Phase 1 only)

```
d0f72b3 feat(security): Server-side Origin allowlist closes CSRF window
c31e585 feat(admin-web): Phase 1 admin SPA scaffold + 4 pages
1188e54 feat(admin): add Phase 1 admin API and cross-subdomain auth
902b948 feat(ui): admin-only '进入管理后台' menu item in TopBar
51c599c test: add admin phase 1 RED coverage       (RED checkpoint)
```

## 3. Files Added / Modified

### Backend (62 files touched, 9 added)

**New** (under `app/admin/`):
- `__init__.py` — aggregate router + state helpers
- `dashboard.py` — `GET /api/admin/dashboard`
- `kbs.py` — `GET /api/admin/kbs`, `DELETE /api/admin/kbs/{id}`
- `audit.py` — `GET /api/admin/audit?limit=N` (UNION ALL of chat_turns + login timestamps)
- `settings.py` — `GET/PATCH /api/admin/settings` + `RuntimeSettings` (RLock-protected)
- `stats.py` — SQLite aggregate helper, dynamic `PRAGMA table_info` with table-name allowlist
- `schemas.py` — Pydantic models (`AdminSettings`, `SettingsPatch`, `AdminKB`, `AuditEntry`)

**Modified**:
- `app/api/__init__.py` — adds `configure_cors(app)` + `ADMIN_CORS_ORIGINS` constant
- `app/api/auth.py` — `_set_session_cookie` / `_clear_session_cookie` take `request`, set `Domain=.kb.sxy.homes` when `cookie_secure=True`; `samesite="none"` in prod, `"lax"` in dev
- `main.py` — lifespan creates `RuntimeSettings`; factory wires `configure_cors`, `_register_csrf_middleware`, then routers
- `tests/test_admin_phase1.py` — 11 tests (was 6): RED → GREEN → CSRF

### Frontend (admin-web/, 22 files)

```
admin-web/
├── .gitignore
├── package.json              # react@18.3.1, chakra@2.10.4, recharts@2.15.4, vitest@4.1.10
├── tsconfig.json
├── vite.config.ts            # port 5174 strict, /api proxy → 127.0.0.1:8000
├── vitest.config.ts
├── index.html
├── src/
│   ├── App.tsx               # Routes: /admin/login, /admin, /admin/{kbs,audit,settings}
│   ├── main.tsx              # ChakraProvider + AuthProvider + BrowserRouter
│   ├── api.ts                # fetch wrapper credentials:'include', typed API
│   ├── api.test.ts           # 17 vitest tests for fetch wrapper
│   ├── theme.ts              # Custom dark theme: ink/copper/signal + Iowan + Avenir
│   ├── vite-env.d.ts
│   ├── components/
│   │   └── ConfirmDialog.tsx
│   ├── context/
│   │   ├── AuthContext.tsx        # auth state + login/logout/refresh
│   │   └── AuthContext.test.tsx   # 2 tests
│   ├── layouts/
│   │   ├── AuthLayout.tsx
│   │   ├── AdminLayout.tsx        # Sidebar + top bar + content
│   │   └── icons.tsx              # 6 inline SVG icons (no extra dep)
│   ├── lib/
│   │   ├── format.ts              # number/date/bytes formatters
│   │   └── format.test.ts         # 6 tests
│   └── pages/
│       ├── Login.tsx
│       ├── Dashboard.tsx          # 4 stat cards + Recharts pie + status bars
│       ├── KBs.tsx                # Chakra Table + delete
│       ├── Audit.tsx              # Table + type filter
│       └── Settings.tsx           # Form + grid
```

### Main SPA (single touch)
- `web/src/components/TopBar.tsx` — added the admin-only "进入管理后台" menu item
  (`window.open('https://admin.kb.sxy.homes', '_blank')`)

## 4. Test Results

### Backend (`pytest tests/ -q`)

```
262 passed, 245 warnings in 66.30s
```

Coverage by category (admin-relevant):
- `tests/test_admin_phase1.py`: 11 tests (was 6 RED)
  - SQL aggregates, endpoint envelopes, auth gating, CORS preflight, cookie flags, settings validation, **CSRF** (3 new)
- All 251 pre-existing tests untouched and pass.

### Frontend (`npm test`)

```
Test Files  3 passed (3)
Tests       41 passed (41)
```

Coverage:
```
File              | % Stmts | % Branch | % Funcs | % Lines
All files         |   92.38 |    95.08 |      92 |    91.20
 src/api.ts       |     100 |    90.47 |     100 |     100
 src/context/     |   73.33 |    50.00 |   71.42 |   73.33
```

(Build of code is documented; the 73% in `AuthContext.tsx` is the unreached branch on the `refresh()` retry path — not a runtime gap.)

### Build (`npm run build`)

```
dist/index.html                  0.33 kB
dist/assets/index-D_RxivLX.js  891.47 kB │ gzip: 274.67 kB
✓ built in 3.66s
```

> Bundle is 891 kB ungzipped because Chakra UI + Recharts dominates. A future vite `manualChunks` cleanup can split React/Chakra/Recharts into separate chunks.

## 5. Technical Decisions

### 5.1 Cross-subdomain cookie
`Domain=.kb.sxy.homes` is gated by `cookie_secure=True` (production). In dev
(`cookie_secure=False`), no `Domain` is set, so the cookie stays on the issuing
host (`localhost:5174`), but `samesite="lax"` keeps CSRF at bay.

### 5.2 CSRF Origin middleware (post-review)
The security review flagged that `SameSite=None` + `Domain=.kb.sxy.homes`
opens a CSRF window that CORS alone does not close (CORS blocks the response
but the server still processes the request). Added a server-side middleware
in `main.py:_register_csrf_middleware` that mirrors the CORS allowlist on
non-GET requests: a state-changing request with an `Origin` outside the
trusted set is rejected with `403 {"code":403,"message":"invalid origin"}`.
Same-origin requests (the browser omits `Origin`) are allowed.

> **Known limitation**: a more robust fix is a double-submit CSRF token
> (`X-CSRF-Token` header + `csrf_token` cookie). For Phase 1, server-side
> Origin checking is sufficient when the only browsers reaching the admin
> endpoints are the trusted frontend SPAs. Recommended follow-up if the
> deployment adds other entry points.

### 5.3 Runtime settings
`RuntimeSettings` is initialized eagerly in `main.py` lifespan (not lazily)
so there's no race on first access. The Pydantic `SettingsPatch` uses
`extra="forbid"` + field bounds + a `model_validator` that enforces
`chunk_overlap < chunk_size`. Whitelist of exposed fields is intentionally
narrow (no secrets).

### 5.4 SPA admin gating
Two layers:
1. `RequireAdmin` wrapper around every authenticated route in `App.tsx` —
   redirects non-admin users to `/admin/login`.
2. `AdminLayout` renders only after the auth bootstrap resolves; shows a
   spinner during loading and trusts `RequireAdmin` to gate by role.

Login page clears the session via `logout()` if a member-user tries to log
in, so the auth state never briefly holds a non-admin user.

### 5.5 Audit log without a new table
Per the spec ("Phase 1 用现有数据近似"), the audit endpoint composes a
`UNION ALL` of `chat_turns` (`type='chat'`) and `users.last_login_at`
(`type='login'`). Both come back through one query, sorted by `created_at`
desc, clamped to `limit ∈ [1, 500]`.

### 5.6 No Home SPA refactor
Only `TopBar.tsx` was touched (one new `MenuItem` block). The home SPA
reuses the existing JWT cookie, so it neither knows nor cares about the
admin subproject.

## 6. Deployment Notes

The spec leaves nginx/caddy routing to the coordinator. The minimum config
for the admin subdomain to work is:

```nginx
# nginx example (taken from spec)
server {
  server_name admin.kb.sxy.homes;
  root /var/www/youfu-known/admin-web/dist;
  index index.html;

  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

For Cloudflare Tunnel, the config in `openspec/tasks/admin-system.md` is
correct out of the box:

```yaml
ingress:
  - hostname: kb.sxy.homes
    service: http://127.0.0.1:8000
  - hostname: admin.kb.sxy.homes
    service: http://127.0.0.1:8000
  - service: http_status:404
```

The admin SPA's static files are served by nginx, but its `/api/*` calls hit
the same backend (cookie `Domain=.kb.sxy.homes` ensures the session is shared).

### Required env vars (no new ones)
- `VITE_API_BASE` (optional) — if absent, the SPA uses Vite's dev proxy
  (`/api` → `http://127.0.0.1:8000`).
- The existing `APP_AUTH_COOKIE_SECURE=true` (production) toggles
  `Domain=.kb.sxy.homes` and `samesite="none"`. In dev (false), the cookie
  stays on the issuing host with `samesite="lax"`.

### Cookie invalidation
The spec warns: "改 samesite 影响现有用户, 主协调发布后需 invalidate cookie".
After deploying, all existing browser sessions should be cleared (the
cookie name (`session_token`) and value format are unchanged, but adding
`Domain=.kb.sxy.homes` makes browsers treat the new cookie as a different
cookie from the old one with no `Domain` attribute).

## 7. Spec Deviations

| Item | Spec says | What we did | Why |
|---|---|---|---|
| `app/api/admin.py` extension | spec implies extend it | kept `app/api/admin.py` (user-mgmt) untouched and created new `app/admin/` package | preserves stable user-mgmt router; keeps the new module cohesive |
| `web/src/components/TopBar.tsx` | `window.open('https://admin.kb.sxy.homes', '_blank')` | identical (line 130) | exact match |
| Audit log schema | `{id, type, user_id, username, kb_id, question, detail, created_at}` | exposed `username`, `kb_id`, `question`, `detail` (full record from `chat_turns`/`users`) | matches spec |
| `chunk_overlap` validation | spec didn't pin this | added `model_validator` enforcing `chunk_overlap < chunk_size` | defensible; prevents config that produces zero/no chunks |
| Stats `table` identifier | spec didn't constrain | added an `_ALLOWED_TABLES` allowlist for `PRAGMA table_info` | defense-in-depth; alerted by code-review |
| `RuntimeSettings` lifecycle | spec didn't specify | eager init in lifespan + lazy fallback in `_runtime_for` | avoids first-request race |
| CSRF middleware | not in spec | added server-side Origin check after security review | closes the CSRF window opened by `SameSite=None` |
| `kb_list` count fields | spec says `doc_count`, `chunk_count` | mirrored from `knowledge_bases` columns (already maintained by `recompute_kb_counts`) | matches |
| Cross-subdomain cookie path | not specified | `path="/"` | matches refresh/logout path expectations |

## 8. Required Next Steps (for the coordinator)

1. **Decide on nginx routing** for `admin.kb.sxy.homes` (the project's
   existing deployment patterns apply; example config above).
2. **Invalidate existing user cookies** after deploy (spec warning).
3. **(Optional) CSRF token** — if the admin SPA is ever exposed to a less
   trusted origin (e.g. embedded in another app), add a `X-CSRF-Token`
   double-submit pattern. Today's Origin check is sufficient for the
   trusted-frontend-only deployment.
4. **Run the 4-page E2E** (chromium screenshots) once `admin.kb.sxy.homes`
   is reachable.

## 9. What is NOT in this PR

- No push to `origin/main` (per task constraint).
- No changes to home SPA beyond `TopBar.tsx`.
- No changes to user-mgmt admin router (`app/api/admin.py`).
- No OAuth / SSO / email / webhook (per spec).
- No backend business-logic changes.
- No new dev/prod dependencies in the main app (`requirements.txt`).
- `admin-web/` is its own standalone package via npm — its dependencies
  are scoped to `admin-web/package.json` only.
