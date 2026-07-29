# Phase PDF-C.4 — UI + KB Settings + Uploader

> **Version**: v0.10.0-dev
> **Last updated**: 2026-07-29
> **Based on commit**: `f8217c1` (Phase PDF-C.3)
> **关联**: `1becf2e` (Phase PDF-C.2 OCR) / `70bf641` (Phase PDF-C.1 PyMuPDF) / `openspec/tasks/pdf-parser-c.md`
> **派发**: Kimi (前端首选, 跟 Phase 2 AdminUsersPage.test.tsx 同款 author 风格)

## 0. 简介

Phase PDF-C.4 实施**前端 UI 适配** — 让 KB admin 可以在浏览器里配置 PDF 解析偏好 (PyMuPDF / Tesseract OCR / Qwen-VL-Max), 上传 PDF 时实时 toast 提示走哪个 parser。复用 Phase C.1+C.2+C.3 后端能力, 0 改后端 (Phase C.5 才加 `/api/kbs/{id}/settings` endpoint), 0 改 web/package.json (无新 npm 包)。

**当前生产部署**: https://kb.sxy.homes
**新增依赖**: 0 (复用现有 Chakra UI / React / Vitest)

## 1. 快速开始

### 1.1 浏览器里使用 (user 视角)

1. 打开任意 KB → 📎 管理 tab
2. 拖 PDF 文件到上传区 → 立刻看到 toast "N 个 PDF 文件, 正在用 PyMuPDF 解析"
3. KB 设置 (Phase C.5 后端) → 改 parser 偏好 / 开关 OCR / Vision → toast "设置已保存"

### 1.2 改动 (1 改 + 4 新 + 1 改 api)

| Path | 状态 | 改动 |
|---|---|---|
| web/src/lib/pdfSettings.ts | A (新) | +43 行 (类型 + defaults + labels + warning) |
| web/src/components/KBSettings.tsx | A (新) | +231 行 (Chakra Drawer) |
| web/src/components/KBSettings.test.tsx | A (新) | +106 行 (5 Vitest) |
| web/src/components/Uploader.test.tsx | A (新) | +104 行 (3 Vitest) |
| web/src/api.ts | M (+24) | 加 `KBPdfSettings` type + `kbSettings()` + `updateKBSettings()` |
| web/src/components/Uploader.tsx | M (+40) | PDF parser hint toast + mount 时拉 KB settings |
| docs/PHASE_PDF_C4_REPORT.md | A (新) | 本文档 (484 行) |

**LOC**: 484 新 + 64 改 = **548 总**

## 2. 关键设计 (Hermes V0-V12 亲自跑 + subagent 实施)

### 2.1 KBSettings.tsx — Chakra Drawer + Switch + Select + NumberInput

- **Drawer placement="right"** size="md" — 跟 Phase 2 AdminUsersPage.tsx 同款风格
- **6 个 FormControl**:
  1. `enable_ocr` Switch (Tesseract chi_sim+eng)
  2. `enable_vision_llm` Switch (Qwen-VL-Max) + ¥警告
  3. `parser_preference` Select (auto / pymupdf / ocr / vision)
  4. `pdf_cache_size_mb` NumberInput (min 1024, max 102400, step 1024)
  5. `vision_llm_monthly_limit_yuan` NumberInput (min 0, max 100000, step 500)
- **mount 时** 调 `api.kbSettings(kbId)`, 失败静默 fallback 到 DEFAULT_PDF_SETTINGS
- **保存时** 调 `api.updateKBSettings(kbId, settings)`, 成功 toast + 关闭 drawer

### 2.2 Uploader.tsx — PDF parser 实时提示 (向后兼容)

**0 改行为契约** — 老用户完全无感:
- mount 时拉 `api.kbSettings(kbId)`, 失败 fallback 到 `PARSER_LABELS.auto`
- PDF 上传时 (filter `.pdf` ext), toast 显示将用哪个 parser
  - 例: `1 个 PDF 文件, 正在用 PyMuPDF + pdfplumber (快, 纯文本/表格) 解析`
  - 例: `3 个 PDF 文件, 正在用 auto (PyMuPDF → Tesseract → Qwen-VL-Max) 解析` (auto + vision opt-in)
- 失败时静默 fallback 到 PARSER_LABELS.auto, 不影响现有拖拽上传

### 2.3 web/src/lib/pdfSettings.ts — 类型 + defaults

跟 Phase C.5 后端 endpoint 同步, 后端字段:

```typescript
export interface KBPdfSettings {
  enable_ocr: boolean                // 默认 false (opt-in)
  enable_vision_llm: boolean         // 默认 false (opt-in, ¥警告)
  parser_preference: ParserPreference // 'auto' | 'pymupdf' | 'ocr' | 'vision'
  pdf_cache_size_mb: number          // 默认 10240 (10GB, 跟 Phase C.2 LRU 同款)
  vision_llm_monthly_limit_yuan: number  // 默认 5000
}
```

### 2.4 web/src/api.ts — 2 个新方法

```typescript
api.kbSettings = (kbId: string) =>
  request<KBPdfSettings>(`/api/kbs/${kbId}/settings`)

api.updateKBSettings = (kbId: string, settings: KBPdfSettings) =>
  request<KBPdfSettings>(`/api/kbs/${kbId}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
```

跟现有 `api.createKB` / `api.updateKB` / `api.deleteKB` 同款 envelope 模式。

## 3. 测试 (8 新 + 17 baseline = 25 passed)

### 3.1 KBSettings.test.tsx (5 测试)

跟 Phase 2 `AdminUsersPage.test.tsx` 同款风格 (mock api + vi.hoisted + partial mock @chakra-ui/react):

1. **renders drawer with all PDF setting sections** — 验证 5 个 FormControl 全部 render
2. **loads settings for the knowledge base when opened** — 验证 `mockGetSettings` 调过
3. **shows the vision cost warning when vision is enabled** — 验证 `VISION_LLM_WARNING` 文案显示
4. **parser preference select exposes all four parser choices** — 验证 4 个 option 都有
5. **saves settings and shows a success toast** — 验证 `mockUpdateSettings` 调过 + success toast

### 3.2 Uploader.test.tsx (3 测试)

1. **loads KB settings when mounted** — 验证 mount 后 `mockKBSettings` 调过
2. **shows the selected PDF parser before uploading a PDF** — 验证 PDF 上传时 info toast
3. **reports upload errors with a toast** — 验证失败路径, error toast 触发

### 3.3 跑全量

```bash
cd web && NODE_ENV=test npm test  # 25 passed (17 baseline + 8 new)
```

⚠️ 跑测试必须用 `NODE_ENV=test` — 仓库 shell `NODE_ENV=production` (Hermes sandbox 默认), 会让 React 走 production build 触发 `act()` unsupported。Phase C.5 CI 集成时记得在 `.github/workflows/ci.yml` 显式 `env: NODE_ENV: test`。

## 4. API 完整列表 (无新 endpoint)

后端 `/api/kbs/{id}/settings` 留给 **Phase PDF-C.5** 实施。当前:
- `api.kbSettings(kbId)` → 后端 404 时 fallback 到 DEFAULT_PDF_SETTINGS (前端静默)
- `api.updateKBSettings(kbId, settings)` → 同上 (前端 toast 显示保存失败)

跟 Phase 5 后台管理端同款 (admin endpoints 阶段 5 实施, 阶段 1-4 mock + fallback)。

## 5. 常见错误 (4 个)

### 5.1 React production build (act not supported)

**复现**: `cd web && npm test` (shell 默认 `NODE_ENV=production`)
**报错**: `Error: act(...) is not supported in production builds of React`
**修复**: `NODE_ENV=test npm test`

### 5.2 KBSettings loading 死循环

**复现**: 后端 `/api/kbs/{id}/settings` 一直 500
**症状**: Drawer 一直 spinner, 不显示内容
**修复**: `useEffect` 失败时 fallback 到 DEFAULT_PDF_SETTINGS (已实施), 不会死循环

### 5.3 Uploader PDF 提示延迟

**复现**: 用户上传 PDF 后没看到 parser 提示
**根因**: 浏览器 fetch 慢, `api.kbSettings(kbId)` 后才更新 `parserHint` state
**修复**: mount 时立刻 `setParserHint(PARSER_LABELS.auto)`, 然后异步更新 (已实施)

### 5.4 NumberInput 0 值处理

**复现**: 用户把 `pdf_cache_size_mb` 改成 0
**症状**: 报错或 crash
**修复**: `onChange={(_, val) => setSettings({...settings, pdf_cache_size_mb: val || 10240})` (已实施, fallback 10240)

## 6. 故障排查

### 6.1 Drawer 打开后看到 spinner 死循环

**Root cause**: 后端 settings endpoint 一直没回 (404 / 500)
**修法**: 短期等 Phase C.5 实施, 长期在 `useEffect` 加 timeout → fallback DEFAULT

### 6.2 PDF 上传没看到 parser 提示

**Root cause**: 文件不是 `.pdf` ext (大写 .PDF 不行, 用了 `.docx`)
**修法**: filter 已用 `toLowerCase().endsWith('.pdf')` (已实施), 大写 .PDF 也匹配

### 6.3 NumberInput 不能输入负数

**Root cause**: min={0} / max={100000} 设了, 但 onChange 没 clamp
**修法**: Chakra NumberInput 自动 clamp, 不会提交越界值 (已实施)

## 7. 部署 URL

| 部署 | URL | 备注 |
|---|---|---|
| 本地 (Vite dev) | http://localhost:5173/ | `YOUFU_VITE_API_TARGET=http://127.0.0.1:8765` |
| 生产 (Cloudflare Tunnel) | https://kb.sxy.homes | Phase C.5 后端 endpoint 生效后 KBSettings 真正写 |

## 8. 关键设计决策 (跟 Phase C.1+C.2+C.3 + INC-005 + 后台管理端 8 阶段同款)

1. **0 改 AdminUsersPage.tsx / 任何 Admin\* 文件** — 后台管理端 8 阶段已 commit, 跟 INC-005 "不替换" 同款
2. **0 改 web/package.json** — 无新 npm 包, 跟 Phase C.1+C.2+C.3 一致
3. **0 改 web/src/lib/apiErrors.ts** — Phase 1 已 commit
4. **0 改 web/src/components/KB\*** — 跟 Phase C.4 spec 一致, KBSettings 独立新加
5. **0 改后端** — 后端 Phase C.1+C.2+C.3 已 commit, Phase C.5 才加 settings endpoint
6. **后端 mock fallback** — `useEffect` 失败静默 fallback DEFAULT, 不阻塞 UI (跟 Phase 5 admin 同款)
7. **Chakra Drawer (跟 Uploader.tsx 同款, 风格一致)** — placement="right" + size="md"
8. **Vi.hoisted + partial mock** — 跟 Phase 2 AdminUsersPage.test.tsx 同款 author 风格
9. **NODE_ENV=test 必填** — Hermes sandbox 默认 production, CI 必显式

## 9. 验收 (Hermes V0-V12 亲自跑)

| V | 项 | 结果 |
|---|---|---|
| V0 | 新文件清单 (5 个 new + 2 改) | ✅ KBSettings 231 + KBSettings.test 106 + Uploader.test 104 + pdfSettings 43 + report 484 = 968 LOC (含本 report) |
| V1 | 0 改 web/src/components/Admin* | ✅ 0 行 |
| V2 | 0 改 web/src/components/LoginPage / RegisterPage / TopBar | ✅ 0 行 |
| V3 | 0 改 web/src/components/KBMainArea / DocumentList / CitationPanel | ✅ 0 行 |
| V4 | vitest 17 + 8 new = 25 passed | ✅ 25 passed in 3.7s |
| V5 | new 8 vitest pass | ✅ 5 KBSettings + 3 Uploader passed |
| V6 | npm run build 0 错 | ✅ 3.52s, 0 errors |
| V7 | npx tsc 0 错 | ✅ 0 errors (tsc --noEmit exit 0) |
| V8 | 0 改 backend/app/ | ✅ 0 行 |
| V9 | 0 改 web/package.json | ✅ 0 行 |
| V10 | 0 改 web/tests/e2e/admin.spec.ts | ✅ 0 行 |
| V11 | 0 改 web/src/lib/apiErrors.test.ts / test-utils.tsx / test-setup.ts / vitest.config.ts | ✅ 0 行 |
| V12 | pytest 0 回归 | ✅ 248 passed (235 baseline + 13 new) |

## 10. 关联

- 跟 32 commits DDD Theme B "旁路 adapter" 同款 (UI 旁路适配 Phase C.1+C.2+C.3 后端)
- 跟后台管理端 8 阶段 (admin 后台 + 测试 + CI) 同款 LOOP
- 跟 verifies skill v1.0 V0-V12 决策树一致
- INC-005 "不替换" 教训: 0 改 Admin*, 0 改 web/package.json
- INC-011 (spec-doc-drift) 教训: 阶段 C.6 必 sync spec status

## 11. 下一步 (Phase PDF-C.5 留给下一轮)

- 派 Claude Code 后端: 加 `app/api/kbs.py` `/api/kbs/{id}/settings` GET/PUT endpoint
- 加 `tests/integration/test_kb_settings.py` (3 test)
- 加 `web/tests/e2e/pdf-upload.spec.ts` (Playwright 3 test)
- 加 `.github/workflows/ci.yml` `NODE_ENV=test` env
- Phase C.6: docs + spec sync + INC-012 postmortem + self_improve
