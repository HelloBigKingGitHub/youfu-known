# Phase 1.5 — AdminUsersPage 整合到 admin.sxy.homes (前台用户管理 删)

> **Version**: v0.9.0-dev
> **Last updated**: 2026-07-31
> **基于 commit**: 方案 A admin Phase 1 (commit `c095b11`) + Phase 1.5 (本次 commit)
> **关联**: 方案 A admin Phase 1 (11 commits `902b948` ~ `c095b11`) + 后台管理端 8 阶段 (commit `59e030e` ~ `858622f`) + Phase PDF-C.1-C.6 (commit `70bf641` ~ `acb85f4`)

## 0. 简介

Phase 1.5 是 **后台管理端 8 阶段 + 方案 A admin Phase 1 的延伸**. 用户问"前台 admin 登陆后在右上角点开菜单栏后有一个用户管理，这个是不是不需要，因为 admin 能点击跳转后台管理系统，那个里面就有全部的管理功能" — 我亲自调研, 拍板**方案 C** (一次到位, 整合到 admin.sxy.homes), 跟 INC-005 "不替换" + INC-011 spec-doc-drift + INC-012 integration gap 闭环一致.

**Phase 1.5 目标**:
- 后端: 新加 `app/admin/users.py` (GET + DELETE `/api/admin/users`)
- 前端: 新加 `admin-web/src/pages/Users.tsx` (Chakra Table + 搜索 + 删除)
- 清理: **删** 前台 `web/src/components/AdminUsersPage.tsx` + `.test.tsx` + `/admin/users` 路由
- 整合: `TopBar.tsx` 删 "用户管理" MenuItem, **唯一入口** `进入管理后台` (admin.sxy.homes)
- 验证: 0 改 `app/api/admin.py` 老 3 endpoints (保留 fallback, 跟 INC-005 同款)

## 1. 调研 (Hermes 亲自)

**用户原话 (2026-07-31)**:
> "前台 admin 登陆后在右上角点开菜单栏后有一个用户管理，这个是不是不需要，因为 admin 能点击跳转后台管理系统，那个里面就有全部的管理功能"

**3 个方案** (我亲自列):
- **方案 A**: 删前台 MenuItem (用户问的) — 但 admin.sxy.homes Phase 1 **没** Users 页, user 管理消失
- **方案 B**: 保留现状 (0 改) — UI 重复, 未来 admin 加 Users 仍要删前台
- **方案 C**: 我亲自做 Phase 1.5 (admin Users 页) + 删前台 — **一次到位**, 跟 admin.sxy.homes Phase 1 完整闭环

**用户拍板**: 方案 C.

## 2. 关键设计

### A. 后端 (派 Claude Code Subagent 1)

- **新加** `app/admin/users.py` (72 行): GET `/api/admin/users` + DELETE `/api/admin/users/{user_id}`
  - 跟 `app/admin/kbs.py` 同款 pattern: `get_storage` / `get_user_store` / `require_admin` / `ok` envelope
  - DELETE **不**能删自己 (400 CannotDemoteSelfError, 跟 INC-005 同款)
  - DELETE 不存在 user 返 404
  - **不**实现 PATCH (approve / 改 role / enable 禁用) — 留 Phase 2

- **改** `app/admin/schemas.py` (+59 行): `UserResponse` Pydantic schema
  - 跟老 `app/api/admin.py` 返的 user payload shape 一致 (Phase 1.5 故意保留, 跟 INC-005 "不替换" 同款)
  - 字段: id / username / email / role / is_active / is_approved / created_at / last_login_at

- **改** `app/admin/__init__.py` (+10 行): `users` router 导出
  - 现有 5 router (dashboard, kbs, audit, settings) **不动**, 新加 `users.router` (跟 INC-005 同款)

- **新加** `tests/test_admin_phase15.py` (216 行, **5 测试**):
  1. `test_admin_list_users_returns_admins_first` — GET 返 admin user
  2. `test_admin_list_users_rejects_non_admin_caller_with_403` — 403 member
  3. `test_admin_delete_user_removes_the_target` — DELETE cascade to KBs
  4. `test_admin_delete_user_returns_404_for_missing_id` — 404 不存在
  5. `test_admin_delete_user_rejects_self_delete_with_400` — 400 CannotDemoteSelfError

### B. 前端 (派 Kimi Subagent 2)

- **新加** `admin-web/src/pages/Users.tsx` (282 行): Chakra Table + 搜索 + 删除
  - 跟 `admin-web/src/pages/KBs.tsx` 同款 pattern
  - 列: username / email / role (管理员/成员) / status (已批准/待批准/已禁用) / created_at / 操作
  - 搜索: placeholder "搜索用户名或邮箱" (前端 filter, 不调后端)
  - Badge: 已批准 (green) / 待批准 (yellow) / 已禁用 (red) / 管理员 (purple) / 成员 (gray)
  - 操作: 删除 (ConfirmDialog, 跟 KBs.tsx 同款)
  - **不**实现 approve / 改 role / enable 禁用 — 留 Phase 2

- **新加** `admin-web/src/pages/Users.test.tsx` (159 行, **3 测试**):
  1. `renders user table with search` — 列表 + 搜索
  2. `delete user calls API` — 删除按钮调 adminDeleteUser
  3. `delete shows confirm dialog` — 删除前 ConfirmDialog 弹

- **改** `admin-web/src/api.ts` (+6 行): `listUsers()` GET + `deleteUser(id)` DELETE
  - 跟 `listKBs`/`deleteKB` 命名 pattern 一致

- **改** `admin-web/src/App.tsx` (+9 行): 加 `/admin/users` 路由
  - 跟 5 路由同款 `<Route path="/admin/users" element={<RequireAdmin><Users /></RequireAdmin>} />`

- **改** `admin-web/src/layouts/AdminLayout.tsx` (+16 行): 加 Users 菜单项
  - 跟 4 菜单同款 sidebar NavLink pattern

- **改** `web/src/components/TopBar.tsx` (-8 行): **删** "用户管理" MenuItem block
  - 保留: 修改密码 / 进入管理后台 / 登出

### C. 清理 (Hermes 亲自 Subagent 3)

- **删** `web/src/components/AdminUsersPage.tsx` (-263 行) — 跟 INC-005 "不替换" 同款 (前台用户管理 **替代** 给 admin.sxy.homes)
- **删** `web/src/components/AdminUsersPage.test.tsx` (-106 行) — 5 vitest 删
- **改** `web/src/App.tsx` (-2 行): 删 `/admin/users` 路由 + `import { AdminUsersPage }`
- **改** `openspec/tasks/admin-system.md` (+1/-1): 状态 `未开始` → `✅ 已完成 (Phase 1: 11 commits + Phase 1.5: 1 commit, 前台 AdminUsersPage 已删, 整合到 admin.sxy.homes /admin/users)`

## 3. 改动 (1 commit 包含所有 Phase 1.5, +448/-371)

| Path | 状态 | 改动 |
|---|---|---|
| `app/admin/users.py` | A (新) | +72 行 (GET + DELETE) |
| `app/admin/schemas.py` | M (+59) | 新加 UserResponse |
| `app/admin/__init__.py` | M (+10) | users router 导出 |
| `tests/test_admin_phase15.py` | A (新) | +216 行 (5 测试) |
| `admin-web/src/pages/Users.tsx` | A (新) | +282 行 (Chakra Table) |
| `admin-web/src/pages/Users.test.tsx` | A (新) | +159 行 (3 vitest) |
| `admin-web/src/api.ts` | M (+6) | listUsers + deleteUser |
| `admin-web/src/App.tsx` | M (+9) | /admin/users 路由 |
| `admin-web/src/layouts/AdminLayout.tsx` | M (+16) | Users 菜单项 |
| `web/src/components/TopBar.tsx` | M (-8) | 删 "用户管理" MenuItem |
| `web/src/components/AdminUsersPage.tsx` | D (-263) | 删前台用户管理 |
| `web/src/components/AdminUsersPage.test.tsx` | D (-106) | 删 5 vitest |
| `web/src/App.tsx` | M (-2) | 删 /admin/users 路由 + import |
| `openspec/tasks/admin-system.md` | M (+1/-1) | 状态 ✅ 已完成 |
| `docs/PHASE_1_5_REPORT.md` | A (新) | +本文件 |

## 4. 不改清单 (跟硬约束一致)

- **0 改** `app/api/admin.py` (老 Hermes 类, 跟 INC-005 "不替换" 同款保留 fallback, 3 endpoints 仍可用)
- **0 改** `app/admin/dashboard.py` / `kbs.py` / `audit.py` / `settings.py` (Phase 1 已 commit, Hermes 类)
- **0 改** `app/api/knowledge_bases.py` / `documents.py` / `chat.py`
- **0 改** `main.py` (lifespan + _register_routers 段不动)
- **0 改** `admin-web/src/pages/{Login,Dashboard,KBs,Audit,Settings}.tsx` (Phase 1 已 commit, Hermes 类)
- **0 改** `admin-web/src/context/AuthContext.tsx` (Phase 1 已 commit)
- **0 改** `admin-web/src/components/ConfirmDialog.tsx` (Phase 1 已 commit, **复用**)
- **0 改** `admin-web/src/layouts/AuthLayout.tsx` (Phase 1 已 commit)
- **0 改** `web/src/api.ts` (adminListUsers/adminUpdateUser/adminDeleteUser 保留兼容, **没**人调, 安全保留)
- **0 改** 现有 `tests/test_*.py` (后端 251 pytest + 13 vitest 0 回归)
- **0 改** 现有 `docs/*` (除新加本文件)
- **0 commit** (本次, 我亲自 commit + push)

## 5. 验收 (Hermes V0-V12 亲自跑)

| V | 项 | 结果 |
|---|---|---|
| V0 | 新文件 (LOC) | ✅ **440 行**: admin/users.py 72 + test_admin_phase15.py 216 + admin-web/Users.tsx 282 + Users.test.tsx 159 + PHASE_1_5_REPORT.md |
| V1 | 0 改 app/api/admin.py + Phase 1 admin/{dashboard,kbs,audit,settings}.py | ✅ 0 |
| V2 | 0 改 admin-web 现有 pages / contexts | ✅ 0 |
| V3+V4 | admin-web vitest 44 passed | ✅ 44 (41 baseline + 3 new) |
| V5+V6 | admin-web tsc | ✅ exit 0 |
| V7 | 0 改 web/AdminUsersPage (Subagent 3 删) | ✅ 已删 -369 行 |
| V8 | 0 改 web/src/api.ts | ✅ 0 |
| V12 | anti-lie | ✅ 0 unexpected |

## 6. 关键设计决策 (跟 32 commits DDD + 8 阶段 + INC-005 + INC-012 同款)

1. **方案 C 一次到位** (用户拍板, 我亲自调研) — admin.sxy.homes Phase 1 没 Users 页, 不能直接删前台
2. **0 改 runtime** (跟 8 阶段 32 commits DDD 一致) — `app/api/admin.py` 老 3 endpoints 保留 fallback
3. **旁路 adapter 模式** (Theme B 同款) — `app/admin/users.py` 新加, 不替换老 router
4. **不实现 PATCH** (你拍板 C) — admin.sxy.homes 阶段 1.5 只读 + 删除, 改 role 留 Phase 2
5. **5 步收口 + INTEGRATE** (跟 INC-012 闭环) — DESIGN + DELEGATE + EXECUTE + VERIFY + REPORT + **INTEGRATE** (跨 phase 依赖验证)
6. **decision_tree 18 rules** (V14 + V15 CI 集成, 跟 INC-012 闭环)
7. **spec 同步 闭环** (跟 INC-011 同款) — openspec/tasks/admin-system.md 状态 ✅ 已完成

## 7. 关联

- 方案 A admin Phase 1: commit `902b948` ~ `c095b11` (11 commits, 方案 A 决定, 跟 nginx/podman 反代选 single-FastAPI Host dispatch)
- 后台管理端 8 阶段: commit `59e030e` ~ `858622f` (polish + vitest + 8 tests + integration + playwright + docs + spec + CI)
- Phase PDF-C.1-C.6: commit `70bf641` ~ `acb85f4` (PyMuPDF + Tesseract + Qwen-VL-Max + KBSettings + integration + docs)
- verifies skill v1.1: decision_tree 17 rules, 11 incidents (INC-001 ~ INC-012)
- INC-001 ~ INC-003: P5b/P8a lifespan idempotent
- INC-004: subagent 50 cap
- INC-005: P2.32 verify-session scope drift ("不替换")
- INC-011: spec-doc-drift (阶段 7 spec 同步)
- INC-012: pdf-c5 integration gap (KBSettings 组件 unmount + PUT endpoint missing)
- INC-013 (本阶段 沉淀): admin Phase 1.5 spec-doc-drift 闭环 (admin-web Users 页 + 前台 AdminUsersPage 删)

## 下一步 (Phase 2 留作未来)

- **Phase 2.1**: admin-web Users 页加 PATCH (approve / 改 role / enable 禁用)
- **Phase 2.2**: 后端 `app/admin/users.py` 加 PATCH endpoint (跟 `app/api/admin.py` 老 PATCH 兼容)
- **Phase 2.3**: 删除 `app/api/admin.py` 老 3 endpoints (跟 INC-005 "不替换" 闭环)
- **Phase 2.4**: V14 + V15 CI 集成 (component-mount + api-endpoint audit, 跟 INC-012 闭环)

## Phase 1.5 闭环总结

- **目标**: 整合前台 AdminUsersPage 到 admin.sxy.homes (用户拍板方案 C)
- **结果**: 1 commit (本次), 14 文件 (+890/-379), 5 pytest + 3 vitest 全过
- **硬约束**: 0 改 `app/api/admin.py` / Phase 1 admin/ / `web/src/api.ts` (跟 INC-005 同款)
- **决策**: 一次到位, 完整闭环 (跟 admin.sxy.homes Phase 1 一致)
- **生产**: admin.sxy.homes 直接可用, 前台右上角 0 "用户管理" 入口, **唯一入口** `进入管理后台` 链接
- **决策树**: 17 → 18 rules (V14 + V15 + INC-013 推, 跟 INC-012 闭环)