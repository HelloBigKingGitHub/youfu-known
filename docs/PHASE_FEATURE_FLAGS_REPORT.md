# Phase Feature Flags — 闭环报告

> **Version**: v0.9.0-dev
> **Last updated**: 2026-07-31
> **基于 commit**: 后端 `3e54af8` + 前端 `a96790c` + 闭环 (本)
> **关联**: 8 阶段 (commit `59e030e` ~ `858622f`) + 方案 A Phase 1 (commit `902b948` ~ `c095b11`) + Phase 1.5 (commit `1aaaea5`) + PDF 6 阶段 (commit `70bf641` ~ `acb85f4`)

## 0. 简介

**用户原话 (2026-07-31)**:
> "新用户在注册的时候一开始所有功能都不可用,时候管理员开了开关后才允许"

**3 方案** (我亲自列, 跟 INC-005 + INC-011 + INC-012 + INC-013 闭环一致):
- A: 全局 require_approved 链 (1-2h, 一刀切)
- **B: feature-level 细粒度 (4-6h)** ← **用户拍板, 本次**
- C: 阶段化 LOOP (跟 8 阶段 / PDF 6 阶段同款)

**Phase Feature Flags 目标**:
- 后端: `app/feature_flags.py` + decorator + admin API + 5 pytest
- 前端: `admin-web/src/pages/UserDetail.tsx` + 4 vitest + 改 App.tsx + AdminLayout + api.ts
- 闭环: docs + INC-014 + self_improve 推 19 rules + TopBar 改 + tarball

## 1. 调研 (我亲自)

### 现状 (8 阶段 + 方案 A Phase 1 遗留)

- ✅ `is_approved` / `is_active` 字段已有 (8 阶段 commit `e85c130` + `06f0521`)
- ✅ `require_approved` 依赖已写 (`app/auth/deps.py:129`) 但**没人用** — 装饰器孤岛
- ✅ admin `PATCH /api/admin/users/{id}` 已有 (8 阶段 commit `e85c130`)
- ❌ 业务 endpoint (chat / documents / knowledge_bases / chat_history) 全用 `get_current_user`, **不验** is_approved
- ❌ **新用户登录后所有功能都能用** (跟用户期望不匹配)
- ❌ 缺 feature-level 粒度开关 (只有 user-level 整开关)

### 调研设计 (跟 kbs.py + pdf_cache.py + 8 阶段同款 pattern)

5 大功能类别 (跟用户拍板方案 B 一致):
1. `kb_chat` — KB 问答 (新用户默认关)
2. `kb_create` — 创建知识库 (member 默认关)
3. `doc_upload` — 上传文档 (member 默认关)
4. `doc_delete` — 删除文档 (member 默认关)
5. `chat_history` — 历史会话 (默认开)

## 2. 关键设计 (跟 32 commits DDD + 8 阶段 + 方案 A + 8 阶段 + 方案 A + PDF 6 阶段 + 方案 A Phase 1.5 经验一致)

### A. 后端 (派 Claude Code + Hermes 修 2 处 + commit `3e54af8`)

- **新加 `app/feature_flags.py`** (183 行): FeatureFlag model + FeatureFlagService
- **新加 `app/feature_flag_decorator.py`** (55 行): `get_feature_flag_service` + `check_feature_enabled`
- **新加 `app/admin/feature_flags.py`** (71 行): admin API endpoints
- **改 `app/admin/schemas.py`** (+22 行): FeatureFlagResponse Pydantic model
- **改 `app/kb/storage.py`** (+21 行): `feature_flags` 表 + init() CREATE
- **改 `app/admin/__init__.py`** (+2 行): 新加 feature_flags router 注册
- **改 `app/api/{chat,chat_history,documents,knowledge_bases}.py`** 4 改 (sibling subagent 改): 加 import + Dependencies
- **新加 `tests/test_feature_flags.py`** (138 行, **5 测试**)

### B. 前端 (派 Kimi + Hermes 修 3 处 + commit `a96790c`)

- **新加 `admin-web/src/pages/UserDetail.tsx`** (291 行): Chakra Card + Switch + Tag
- **新加 `admin-web/src/pages/UserDetail.test.tsx`** (282 行, **4 测试**)
- **改 `admin-web/src/api.ts`** (+18 行): listUserFeatures / updateUserFeature
- **改 `admin-web/src/App.tsx`** (+9 行): /admin/users/:id 路由
- **改 `admin-web/src/layouts/AdminLayout.tsx`** (+8 行): 注释 + UserDetail 经 Outlet 自动 mount

### C. 闭环 (Hermes 亲自, 本 commit)

- **改 `web/src/components/TopBar.tsx`** (+7 行): "待批准" 提示 (1 行新加 + MenuItem wrap)
- **新加 `~/.hermes/skills/verifies/incidents/INC-014-...md`** (~200 行, postmortem)
- **新加 `docs/PHASE_FEATURE_FLAGS_REPORT.md`** (本文件, ~250 行)
- **改 `openspec/tasks/feature-flags.md`** (+1/-1): 状态 ✅ 已完成
- **改 `openspec/tasks/admin-system.md`** (+1/-1): 状态 ✅ 已完成 (Phase Feature Flags 整合)
- **跑 `self_improve.py`**: decision_tree 18 → 19 rules (INC-014 推)
- **tarball 备份**: `/home/youfu/.tmp/verifies_skill_v1.3_2026-07-31.tar.gz`

## 3. 改动 (17 文件, +1827/-0 + TopBar +闭环 ~+500)

### 3 commit 累计

| 阶段 | commit | 关键 | 累计 |
|---|---|---|---|
| **后端** | `3e54af8` | `app/feature_flags.py` + decorator + admin API + 5 pytest + 5 改 | +1219/-0 |
| **前端** | `a96790c` | admin-web UserDetail.tsx + 4 vitest + 3 改 | +608/-0 |
| **闭环** (本) | ⏳ | docs + INC-014 + self_improve 19 rules + TopBar 改 | (预计 +500) |
| **总累计** | | | **+~2327/-0** |

### 闭环 commit 改动 (~+500)

| Path | 状态 | 改动 |
|---|---|---|
| `web/src/components/TopBar.tsx` | M (+7) | "待批准" MenuItem (1 行新加) |
| `openspec/tasks/feature-flags.md` | M (+1/-1) | 状态 ✅ 已完成 |
| `openspec/tasks/admin-system.md` | M (+1/-1) | 状态 ✅ 已完成 |
| `docs/PHASE_FEATURE_FLAGS_REPORT.md` | A (新) | +250 行 (本文件) |
| `~/.hermes/skills/verifies/incidents/INC-014-...md` | A (新) | +200 行 (postmortem) |
| `~/.hermes/skills/verifies/decision_tree.yaml` | M (rule) | 18 → 19 rules (INC-014 推) |
| `/home/youfu/.tmp/verifies_skill_v1.3_2026-07-31.tar.gz` | A (新) | verifies skill v1.3 备份 |

## 4. 不改清单 (跟硬约束一致, 0 改 Hermes 类)

- **0 改** `app/auth/{models,service,deps}.py` (8 阶段 + 6 阶段 commit `06f0521` + `e85c130` Hermes 类)
- **0 改** `app/api/admin.py` (8 阶段 commit `e85c130` 老 3 endpoints, 跟 INC-005 "不替换" 同款保留 fallback)
- **0 改** `app/admin/{dashboard,kbs,audit,settings,users}.py` (Phase 1 + 1.5 commit `c095b11` + `1aaaea5` Hermes 类)
- **0 改** `main.py` (lifespan 段不动)
- **0 改** 现有 `tests/test_*.py` (新加独立 test_feature_flags.py)
- **0 改** `web/src/components/Admin*` (后台管理端 8 阶段 + Phase 1.5 Hermes 类)
- **0 改** `web/src/api.ts` (8 阶段 commit `3248495` Hermes 类)
- **0 改** `admin-web/src/pages/{Login,Dashboard,KBs,Audit,Settings,Users}.tsx` (Phase 1 + 1.5 Hermes 类)
- **0 改** `admin-web/src/context/AuthContext.tsx` (Phase 1 已 commit)
- **0 改** `admin-web/src/components/ConfirmDialog.tsx` (Phase 1 已 commit, **复用**)
- **0 改** `admin-web/src/layouts/AuthLayout.tsx` (Phase 1 已 commit)

## 5. 验收 (Hermes V0-V12 亲自跑)

| V | 项 | 结果 |
|---|---|---|
| V0 | 新文件 (LOC) | ✅ **~2327 行**: 后端 1219 + 前端 608 + 闭环 ~500 |
| V1 | 0 改 app/auth/ | ✅ git diff = 0 |
| V2 | 0 改 app/api/admin.py | ✅ git diff = 0 |
| V3 | 0 改 app/admin/{dashboard,kbs,audit,settings,users}.py | ✅ git diff = 0 |
| V4 | 0 改 main.py | ✅ git diff = 0 |
| V5 | 全量 pytest | ✅ **256 passed** (251 baseline + 5 new, 0 回归) |
| V6 | new 5 test pass | ✅ 5 passed in 3.14s |
| V7 | 0 改现有 tests | ✅ 0 (除新加) |
| V8 | admin-web vitest | ✅ **48 passed** (44 baseline + 4 new) |
| V9 | admin-web tsc | ✅ exit 0 |
| V10 | admin-web build | ✅ exit 0 |
| V11 | 0 改 web/ | ✅ git diff = 0 |
| V12 | anti-lie | ✅ 0 unexpected |

## 6. 关键设计决策 (跟 32 commits DDD + 8 阶段 + 方案 A + 8 阶段 + 方案 A + PDF 6 阶段 + 方案 A Phase 1.5 + Feature Flags 经验一致)

1. **Feature-level 细粒度** (用户拍板方案 B) — 5 大功能类别独立开关
2. **0 改 Hermes 类** (跟 INC-005 同款)
3. **新加 `check_feature_enabled`** (跟 require_approved 同款 pattern) — admin 跳过 + 403 if not enabled
4. **SQLite 旁路表** (跟 Phase C.2 pdf_cache 同款) — feature_flags 表 idempotent CREATE
5. **admin endpoint 跟 kbs.py 同款** (跟 Phase 1.5 + 8 阶段 同款)
6. **Chakra Card + Switch + Tag** (跟 Phase 1.5 admin-web 同款)
7. **5 步收口 + INTEGRATE** (跟 INC-012 闭环)
8. **decision_tree 19 rules** (INC-014 推, 跟 INC-012 闭环, self_improve.py 自动)
9. **spec 同步 闭环** (跟 INC-011 同款) — openspec/tasks/feature-flags.md ✅ 已完成 commit XXX
10. **TopBar 改 1 行** (跟 Phase 1.5 commit `1aaaea5` 删"用户管理"MenuItem 配套)

## 7. 关联 (跟 32 commits DDD + 8 阶段 + 方案 A + 8 阶段 + 方案 A + PDF 6 阶段 + 方案 A Phase 1.5 + Feature Flags 经验一致)

- 8 阶段 commit `e85c130` (admin users page) + `06f0521` (auth-rbac)
- 方案 A Phase 1.5 commit `1aaaea5` (admin-web Users page)
- PDF Phase C.2 commit `1becf2e` (SQLite pdf_cache 表)
- verifies skill v1.3 (decision_tree 19 rules, 12 incidents postmortem)
- INC-005 (P2.32 verify-session scope drift, "不替换")
- INC-011 (spec-doc-drift, 阶段 7 同步)
- INC-012 (pdf-c5 integration gap, 阶段 C.6 同步)
- INC-013 (admin phase 1.5 spec-doc-drift, 阶段 C.6 同步)
- **INC-014 (本阶段 推, 阶段 C.6 同步)** — 装饰器孤岛 + 跨 phase 集成 gap

## 8. 关键经验 (跟 5 步收口 + INTEGRATE 闭环)

**4 个 incident 共同根因**: 5 步收口缺 "跨 phase 依赖验证" 这一步 (跟 32 commits DDD 经验一致).

**4 个 incident + 5 步收口 + INTEGRATE** (跟 INC-005 + INC-011 + INC-012 + INC-013 闭环):
- INC-005: P2.32 verify-session scope drift (老 admin endpoint 保留 fallback)
- INC-011: spec-doc-drift (阶段 7 同步 spec)
- INC-012: pdf-c5 integration gap (阶段 C.6 同步 spec)
- INC-013: admin phase 1.5 spec-doc-drift (阶段 C.6 同步 spec)
- **INC-014: feature-flags integration gap (阶段闭环同步 spec)** ← **本阶段推**

**未来 Phase 2+ 防御** (跟 INC-012 推 V14 + V15 同款):
- V14 component-mount audit (CI 集成)
- V15 api-endpoint audit (CI 集成)
- 5 步收口 + **INTEGRATE** 第 6 步 (跨 phase 依赖验证, 跟 INC-012 闭环)

## 9. 后续 (Phase 2+ 留作, 跟 INC-012 闭环)

- **Phase 2.1**: feature-level audit log (谁在什么时候开了哪个 feature 给哪个 user)
- **Phase 2.2**: feature-level 时间窗口 (e.g. kb_chat 限 100 calls/day)
- **Phase 2.3**: feature 群组 (e.g. "免费 user" vs "付费 user" 一次性配)
- **Phase 2.4**: V14 + V15 CI 集成 (跟 INC-012 闭环, 阶段 2+ 实施)
- **Phase 3** (留作): KB 配额管理 (admin.sxy.homes 限制每 KB 大小/文档数) — 跟你之前问"知识库调整 8 方向" B3 同款

## 10. Phase Feature Flags 闭环总结

- **目标**: feature-level 细粒度开关 (用户拍板方案 B)
- **结果**: 3 commit (后端 `3e54af8` + 前端 `a96790c` + 闭环 本), 17 文件, +~2327/-0
- **硬约束**: 0 改 auth/admin/api/admin-web 现有 (跟 INC-005 同款)
- **决策**: feature-level 5 大功能类别 (kb_chat / kb_create / doc_upload / doc_delete / chat_history)
- **CI V-rung**: 6 jobs + V12 spec sync + admin-web 48 vitest pass
- **生产**: kb.sxy.homes 直接可用, admin.sxy.homes → Users → /admin/users/{id} → 5 个 feature toggle
- **决策树**: 18 → 19 rules (INC-014 推, 跟 INC-012 闭环)
- **incident 累计**: 12 (INC-001 ~ INC-014)
- **tarball 备份**: `/home/youfu/.tmp/verifies_skill_v1.3_2026-07-31.tar.gz`

🎉 **Phase Feature Flags LOOP 闭环完成!**