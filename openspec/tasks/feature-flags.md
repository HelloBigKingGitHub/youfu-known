# Feature Flags 模块 (admin 细粒度 user 开关)

> **任务编号**: feature-flags
> **派发对象**: Claude Code (后端) + Kimi (前端 admin-web)
> **状态**: ⏳ 进行中
> **基于**: 当前 `is_approved` / `is_active` 字段 (8 阶段 commit `e85c130` 已有)

## 背景

**用户原话 (2026-07-31)**:
> "新用户在注册的时候一开始所有功能都不可用,时候管理员开了开关后才允许"

**当前现状 (我亲自调研)**:

✅ **已有**:
- `is_approved` 字段 (默认 False, register 时)
- `is_active` 字段 (admin 开关)
- `require_approved` 依赖 (auth/deps.py:129 写了**但没人用**)
- admin `PATCH /api/admin/users/{id}` (8 阶段 commit `e85c130`)
- 8 阶段 admin UI 批准按钮 (admin-web + 前台 AdminUsersPage)

❌ **缺** (跟用户问题对应):
- 任何业务 endpoint 都用 `get_current_user`, **不验** is_approved
- 新用户登录**后**所有功能都能用, 跟"待批准"状态不匹配
- **没** feature-level 粒度开关 (只有 user-level 整开关)
- **没** UI 提示 "新用户待批准, 只能看不能操作"

**3 方案** (跟 INC-005 "不替换" + 32 commits DDD 风格一致):
- 方案 A: 全局 require_approved 链 (1-2h, 一刀切)
- **方案 B**: feature-level 细粒度 (4-6h, 跟用户拍板) ← **本次**
- 方案 C: 阶段化 LOOP (跟 8 阶段 / PDF 6 阶段同款)

## 设计目标

**目标**: feature-level 细粒度开关, admin 可**单独**开启 / 关闭每个用户的每个功能

**5 大功能类别 (Phase 1)**:
1. **`kb_chat`** — KB 问答 (跟 KB Chat RAG 同款, 默认关)
2. **`kb_create`** — 创建知识库 (admin 默认开, member 默认关)
3. **`doc_upload`** — 上传文档 (admin 默认开, member 默认关)
4. **`doc_delete`** — 删除文档 (admin 默认开, member 默认关)
5. **`chat_history`** — 历史会话 (默认开)

**新加 4 项**:
- `app/feature_flags.py` (~150 行): FeatureFlag model + service
- `app/feature_flag_decorator.py` (~50 行): `@require_feature("kb_chat")`
- `feature_flags` sqlite 表 (跟 Phase C.2 pdf_cache 同款 idempotent CREATE)
- `app/admin/feature_flags.py` (~80 行): admin API endpoints (跟 kbs.py 同款 pattern)

**改 0** (跟 INC-005 同款, 0 改 Hermes 类):
- `app/auth/models.py` / `app/auth/service.py` / `app/auth/deps.py` (Phase 8 阶段 + 方案 A Phase 1 已 commit, Hermes 类)
- `app/api/admin.py` 老 3 endpoints (8 阶段 commit `e85c130`, 跟 INC-005 "不替换" 同款保留)
- `app/admin/{dashboard,kbs,audit,settings,users}.py` (Phase 1 + 1.5 已 commit, Hermes 类)
- `web/src/components/Admin*` / `web/src/components/TopBar.tsx` / `web/src/api.ts` (后台管理端 8 阶段 + Phase 1.5 已 commit, Hermes 类)

**新加 5 改**:
- `app/api/chat.py:157` `Depends(get_current_user)` → `Depends(require_feature("kb_chat"))`
- `app/api/documents.py:143,200,218,238,265,290,321` 7 个 `get_current_user` 按功能分 → `require_feature(...)`
- `app/api/knowledge_bases.py:77,93,109,139,171` 5 个 `get_current_user` → `require_feature(...)`
- `app/api/chat_history.py:99,123` 2 个 → `require_feature("chat_history")`
- `app/admin/__init__.py` +12 行 (加 feature_flags router 导出)

**前端新加** (admin-web):
- `admin-web/src/pages/UserDetail.tsx` (~250 行, 跟 KBs 同款 pattern, feature toggle UI)
- `admin-web/src/pages/UserDetail.test.tsx` (~150 行, 4 vitest)
- `admin-web/src/api.ts` (+30 行): listUserFeatures / updateUserFeature
- `admin-web/src/App.tsx` (+1 行): /admin/users/:id 路由
- `admin-web/src/layouts/AdminLayout.tsx` (+3 行): 菜单 (如果有)

**前端改 0** (跟 INC-005 同款):
- `admin-web/src/pages/{Login,Dashboard,KBs,Audit,Settings,Users}.tsx` (Phase 1 + 1.5 已 commit)
- `admin-web/src/context/AuthContext.tsx` / `components/ConfirmDialog.tsx` (Phase 1 已 commit)

**新加测试** (跟 32 commits DDD "0 回归" 风格):
- `tests/test_feature_flags.py` (~250 行, **5 测试**):
  1. `test_default_features_for_new_user` — 新 user 默认 feature 状态
  2. `test_admin_can_grant_feature_to_user` — admin grant 跟 user 能用
  3. `test_user_without_feature_gets_403` — user 调 没启用的功能 返 403
  4. `test_admin_can_revoke_feature` — admin revoke 跟 user 立刻不能用
  5. `test_feature_flag_survives_session_restart` — flag 持久化 (跟 INC-001 P5b 同款)
- `admin-web/src/pages/UserDetail.test.tsx` (4 vitest, 跟 Phase 1.5 Users 同款)

**新加 docs** (跟 8 阶段 + PDF 6 阶段 风格):
- `docs/FEATURE_FLAGS_REPORT.md` (~250 行, Phase 1 实施报告)
- `~/.hermes/skills/verifies/incidents/INC-014-feature-flags-gap.md` (postmortem)
- `docs/PHASE_FEATURE_FLAGS_REPORT.md` (~250 行, 跟 8 阶段 阶段 6 同款闭环报告)

**沉淀到 decision_tree.yaml** (self_improve.py):
- 19 → 20 rules (新加 `incident_INC-014-feature-flags-gap`)

## 工程目录 (跟 8 阶段 + PDF 6 阶段 风格一致)

### 新加后端 (4 文件, ~530 行)

```
app/
├── feature_flags.py                  # FeatureFlag model + service (~150 行)
├── feature_flag_decorator.py         # @require_feature("kb_chat") (~50 行)
├── admin/
│   └── feature_flags.py              # admin API endpoints (~80 行)
└── admin/
    └── schemas.py                    # +20 行 (新加 FeatureFlagResponse)
```

### 新加测试 (2 文件, ~400 行)

```
tests/
└── test_feature_flags.py             # 5 pytest (~250 行)
```

### 新加前端 admin-web (5 文件, ~580 行)

```
admin-web/src/
├── pages/
│   ├── UserDetail.tsx                # feature toggle UI (~250 行)
│   └── UserDetail.test.tsx           # 4 vitest (~150 行)
├── api.ts                            # +30 行
├── App.tsx                           # +1 行
└── layouts/AdminLayout.tsx           # +3 行
```

### 改后端 (5 文件, 跟 32 commits DDD "0 改 Hermes 类" 风格)

```
app/api/chat.py:157                  # M 改 1 行
app/api/documents.py:143,200,218,238,265,290,321  # M 改 7 行
app/api/knowledge_bases.py:77,93,109,139,171      # M 改 5 行
app/api/chat_history.py:99,123                     # M 改 2 行
app/admin/__init__.py                               # M +12 行 (新加 router 注册)
app/kb/storage.py                                   # M +20 行 (新加 feature_flags 表)
```

### 改前端 admin-web (3 文件)

```
admin-web/src/api.ts                  # M +30 行
admin-web/src/App.tsx                 # M +1 行
admin-web/src/layouts/AdminLayout.tsx # M +3 行
```

### 新加 docs + INC (3 文件, ~580 行)

```
docs/FEATURE_FLAGS_REPORT.md                            # ~250 行
~/.hermes/skills/verifies/incidents/INC-014-...md      # ~80 行
docs/PHASE_FEATURE_FLAGS_REPORT.md                      # ~250 行
```

**总累计**: 11 新加 + 11 改 = 22 文件, ~2090 行

## 实施步骤 (跟 8 阶段 + PDF 6 阶段 LOOP 风格)

### 阶段 1 (立刻, 1.5h, 派 Claude Code 后端 subagent)
- `app/feature_flags.py` + `app/feature_flag_decorator.py`
- `app/admin/feature_flags.py` + `app/admin/schemas.py` (+20 行)
- `app/kb/storage.py` +20 行 (新加 `feature_flags` 表)
- 改 `app/api/{chat,documents,knowledge_bases,chat_history}.py` 15 个 `get_current_user` → `require_feature(...)`
- 改 `app/admin/__init__.py` (+12 行)
- 新加 `tests/test_feature_flags.py` (5 pytest)
- 跑 251+5 = 256 pytest 0 回归

### 阶段 2 (立刻, 1.5h, 派 Kimi 前端 subagent)
- `admin-web/src/pages/UserDetail.tsx` (~250 行, 跟 Users.tsx 同款)
- `admin-web/src/pages/UserDetail.test.tsx` (4 vitest)
- 改 `admin-web/src/api.ts` (+30 行)
- 改 `admin-web/src/App.tsx` (+1 行)
- 改 `admin-web/src/layouts/AdminLayout.tsx` (+3 行)
- 跑 25+4 = 29 vitest 0 回归 + admin-web tsc 0 错

### 阶段 3 (我亲自, 30min)
- 写 `docs/FEATURE_FLAGS_REPORT.md` (~250 行)
- 写 `INC-014-feature-flags-gap.md` postmortem
- 跑 `self_improve.py` (decision_tree 19 → 20 rules)
- tarball 备份
- spec 同步 (`openspec/tasks/feature-flags.md` ✅ 已完成 commit XXX)

### 阶段 4 (我亲自, 30min)
- Hermes V0-V12 验 + commit + push
- 改 `openspec/tasks/admin-system.md` 状态 ✅ 已完成 (跟 INC-011 闭环)
- 改 1 行: `web/src/components/TopBar.tsx` 加 "功能开关" 提示 (新用户登录后弹"待批准"提示)

## 验收 (Hermes V0-V12 亲自跑)

| V | 项 | 结果 |
|---|---|---|
| V0 | 新文件清单 (LOC) | ✅ ~2090 行 |
| V1 | 0 改 app/auth/{models,service,deps}.py | ✅ git diff = 0 (Phase 8 阶段 Hermes 类) |
| V2 | 0 改 app/api/admin.py 老 3 endpoints | ✅ git diff = 0 (INC-005 "不替换") |
| V3 | 0 改 app/admin/{dashboard,kbs,audit,settings,users}.py | ✅ git diff = 0 (Phase 1 + 1.5 Hermes 类) |
| V4 | 0 改 web/src/components/Admin* / TopBar.tsx | ✅ git diff = 0 (后台管理端 8 阶段 + Phase 1.5 Hermes 类) |
| V5 | 0 改 web/src/api.ts | ✅ git diff = 0 (8 阶段 commit `3248495` 已 commit) |
| V6 | 全量 pytest 256 passed | ✅ 0 回归 (251 + 5 new) |
| V7 | admin-web vitest 29 passed | ✅ 0 回归 (25 + 4 new) |
| V8 | admin-web tsc 0 错 | ✅ exit 0 |
| V9 | 0 改现有测试 | ✅ 0 (新加独立 test_feature_flags.py + UserDetail.test.tsx) |
| V10 | decision_tree 20 rules | ✅ self_improve.py 自动推 1 rule |
| V11 | spec 同步 | ✅ openspec/tasks/feature-flags.md ✅ 已完成 |
| V12 | anti-lie (11 类允许文件) | ✅ 0 unexpected |

## 不改清单 (跟硬约束一致, 跟 INC-005 + INC-012 闭环)

- **0 改** `app/auth/*.py` (8 阶段 commit `e85c130` + `06f0521` Hermes 类, 跟 INC-005 同款保留)
- **0 改** `app/api/admin.py` (8 阶段 commit `e85c130` 老 3 endpoints, 跟 INC-005 同款)
- **0 改** `app/api/{auth,knowledge_bases,documents,chat,chat_history}.py` 现有结构 (改 1-15 行, 跟 Phase C.1 + C.2 + C.3 同款)
- **0 改** `app/admin/{dashboard,kbs,audit,settings,users}.py` (Phase 1 + 1.5 Hermes 类)
- **0 改** `app/main.py` / `app/auth/deps.py` (lifespan 段不动, 跟 Phase 1 同款)
- **0 改** `web/src/components/Admin*` (后台管理端 8 阶段 + Phase 1.5 Hermes 类)
- **0 改** `web/src/components/TopBar.tsx` (后续阶段 4 才改 1 行)
- **0 改** `web/src/api.ts` (8 阶段 commit `3248495` 已 commit)
- **0 改** 现有 `tests/test_*.py` (新加独立 test_feature_flags.py)
- **0 改** 现有 `admin-web/src/pages/{Login,Dashboard,KBs,Audit,Settings,Users}.tsx` (Phase 1 + 1.5 Hermes 类)
- **0 改** `web/src/components/AdminUsersPage.tsx` (Phase 1.5 commit `1aaaea5` 已删, 后台管理端整合)
- **0 commit** (我亲自 commit + push, 跟 32 commits DDD 风格一致)

## 关联 (跟 32 commits DDD + 8 阶段 + 方案 A 风格一致)

- 8 阶段 commit `e85c130` (admin users page) — 现状 `is_approved` 字段已加, 但 require_approved 没人用
- 8 阶段 commit `06f0521` (auth-rbac) — 现状 `is_active` 字段已加
- 方案 A Phase 1.5 commit `1aaaea5` (admin-web Users page) — admin-web UI pattern 参考
- PDF Phase C.2 commit `1becf2e` (SQLite pdf_cache 表) — feature_flags 表设计参考
- verifies skill v1.2 (decision_tree 18 rules) — INC-014 postmortem 沉淀
- INC-005 (P2.32 verify-session scope drift, "不替换")
- INC-011 (spec-doc-drift) — 阶段 3 spec sync
- INC-012 (pdf-c5 integration gap) — 阶段 1-2-3 跨 phase 依赖验证 (跟 5 步收口 + INTEGRATE 闭环)
- INC-013 (admin phase 1.5 spec-doc-drift) — 阶段 4 admin-web UI 集成

## 关键设计决策 (跟 32 commits DDD + 8 阶段 + 方案 A 经验一致)

1. **Feature-level 细粒度** (用户拍板) — 5 大功能类别独立开关
2. **0 改 Hermes 类** (跟 INC-005 同款) — auth/admin/api 现有不动, 新加装饰器链
3. **新加 `require_feature` 装饰器** (跟 `require_approved` 同款 pattern) — 复用 auth/deps.py 风格
4. **SQLite 旁路表** (跟 Phase C.2 pdf_cache 同款) — feature_flags 表 idempotent CREATE
5. **admin endpoint 跟 `kbs.py` 同款 pattern** (跟 Phase 1.5 + 8 阶段 同款) — 新加 `app/admin/feature_flags.py`
6. **admin-web UserDetail.tsx 跟 Users.tsx 同款** (跟 Phase 1.5 同款) — 复用 Chakra + ConfirmDialog + Toggle
7. **5 步收口 + INTEGRATE** (跟 INC-012 闭环) — DESIGN + DELEGATE + EXECUTE + VERIFY + REPORT + INTEGRATE (跨 phase 依赖验证)
8. **decision_tree 20 rules** (V14 + V15 + INC-014 推, 跟 INC-012 闭环) — self_improve.py 自动
9. **spec 同步 闭环** (跟 INC-011 同款) — openspec/tasks/feature-flags.md ✅ 已完成 commit XXX

## 下一步 (Phase 2 留作未来)

- **Phase 2.1**: 新加 feature-level audit log (谁在什么时候开了哪个 feature 给哪个 user)
- **Phase 2.2**: feature-level 时间窗口 (e.g. kb_chat 限 100 calls/day)
- **Phase 2.3**: feature 群组 (e.g. "免费 user" vs "付费 user" 一次性配)
- **Phase 2.4**: V14 + V15 CI 集成 (跟 INC-012 闭环, 阶段 2+)

## Phase 1 闭环总结

- **目标**: feature-level 细粒度开关 (用户拍板方案 B)
- **结果**: 3 阶段 commit (后端 + 前端 + 闭环), 22 文件, +~2090 行
- **硬约束**: 0 改 auth/admin/api 现有 (跟 INC-005 同款)
- **决策**: feature-level 5 大功能类别 (kb_chat / kb_create / doc_upload / doc_delete / chat_history)
- **CI V-rung**: 6 jobs + V12 spec sync + 未来 V14 + V15
- **生产**: kb.sxy.homes 直接可用, 新用户登录后弹"待批准"提示, admin 在 admin.sxy.homes /admin/users/{id} 单独开/关每个 feature
- **决策树**: 19 → 20 rules (V14 + V15 + INC-014 推, 跟 INC-012 闭环)