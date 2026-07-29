/**
 * PDF 上传 + KBSettings e2e test (Playwright).
 *
 * 跟 32 commits DDD + verifies skill + 后台管理端 8 阶段 + Phase
 * C.1-C.4 同款:
 *  - 0 改 web/src/components/ (Uploader / KBSettings / KBMainArea /
 *    KBManageTab / AdminUsersPage / TopBar / DocumentList 都不动)
 *  - 0 改 web/tests/e2e/admin.spec.ts (阶段 5 已 commit)
 *  - 0 改 web/playwright.config.ts
 *  - 0 改 web/package.json
 *  - 真实 Chromium + 真 Vite + 真 FastAPI, 不 mock
 *  - 3 test, 1 hero (PDF upload, 跑得通), 2 graceful test.skip
 *    (KBSettings Drawer 在 C.4 阶段只 ship 了 component 跟 api.ts
 *    mock, 没 mount point — 这是已知 gap, 跟 32 commits DDD INC-011
 *    spec-doc-drift 同款, 阶段 C.6 spec sync 闭环)
 *
 * 调研发现 (跟 brief 不一致, 跟 source 一致):
 *  - KBSettings 组件**没有** mount point: web/src/components/ 下除
 *    KBSettings.test.tsx 外**没有** import KBSettings 的文件. C.4
 *    commit 7599e2e 只 ship 了 component + api.ts mock + vitest, 没在
 *    KBMainArea / KBManageTab / Uploader 加 trigger button.
 *  - /api/kbs/{id}/settings 后端**没有** real endpoint: app/api/
 *    knowledge_bases.py 下**没有** /settings 路由, 只有 GET / PATCH
 *    / DELETE. KBSettings.tsx 调 api.kbSettings() 必然 404 → catch
 *    走 DEFAULT_PDF_SETTINGS fallback (vitest 已验).
 *  - Uploader.tsx mount 时调 api.kbSettings(kbId) 拿 parser_preference;
 *    真后端 404 → catch 走 PARSER_LABELS.auto fallback, "1 个 PDF 文件,
 *    正在用 自动 (推荐) - 按 PDF 类型选 解析" toast 仍会触发.
 *  - LoginPage username/password placeholder 跟 brief 一致:
 *    "admin" / "••••••••" (admin.spec.ts 已验).
 *  - Admin menuButton accessible name = "admin admin" (avatar alt +
 *    username 拼接, admin.spec.ts 已验).
 *  - admin.spec.ts 用 [data-kb-name] 找 KB, 现阶段 source 没这个
 *    attribute, admin.spec.ts Phase 5 的 `[data-kb-name]` 是注册
 *    加的. e2e 我用 text-based locator 选 1 个 KB (不依赖 data attr).
 */

import { test, expect, type Page } from '@playwright/test'

const ADMIN_USER = { username: 'admin', password: 'rootpw' }

async function loginAsAdmin(page: Page) {
  await page.goto('/login')
  await page.getByPlaceholder('admin').fill(ADMIN_USER.username)
  await page.getByPlaceholder('••••••••').fill(ADMIN_USER.password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.includes('/login'), {
    timeout: 10_000,
  })
}

async function openFirstKB(page: Page) {
  // 进主页 (admin login 后 redirect 到 /)
  await page.goto('/')
  // 等 sidebar 加载 (KB list)
  // KnowledgeBaseSidebar.tsx 的 KB item 是 <Box onClick={navigate(/kbs/${id})}>,
  // 不是真 <a href>, 用 [role=button] 或 data-kb-name 找 (admin.spec.ts 用
  // data-kb-name, 但当前 source 没这个 attr — fallback 找 sidebar 内文字
  // 含 "aaa" 的 Box — 沙箱 admin 自带 1 个 KB 名为 "aaaa..." 跟 admin
  // 用户同名测试 friendly)
  await page.waitForLoadState('networkidle', { timeout: 10_000 })

  // Look for any clickable KB item. KnowledgeBaseSidebar.tsx uses
  // Chakra Box + onClick; the rendered role is "button" if aria
  // role is set, otherwise plain div. The "aaaaaaaaaaaaaaaa..." KB
  // name is unique in this sandbox. Use a flexible selector that
  // matches any element whose text starts with "aaaa" (the seeded
  // KB name) and is inside the sidebar.
  const sidebar = page.locator('aside, [data-testid="kb-sidebar"], nav').first()
  if ((await sidebar.count()) === 0) {
    // No sidebar at all — fall back to a "Click first KB-shaped text"
    // search across the whole page.
  }
  const kbItem = page
    .getByText(/^aaaa/)
    .first()
  const itemCount = await kbItem.count()
  if (itemCount === 0) {
    test.skip(
      true,
      'No KB visible in sidebar (register flow blocked by Turnstile, ' +
        'no test data setup in this env)',
    )
    return
  }
  await kbItem.click()
  // 等导航到 /kbs/{id} 或 /kbs/{id}/manage
  await page.waitForURL(/\/kbs\/[^/]+(\/manage)?$/, { timeout: 10_000 })
}

test.describe('PDF 上传 + KB 设置 (e2e, Phase PDF-C.5)', () => {
  test('admin 上传 PDF → toast 显示解析器偏好 → 文档出现在列表', async ({
    page,
  }) => {
    await loginAsAdmin(page)
    await openFirstKB(page)

    // 等 Uploader 拉 kbSettings (调 /api/kbs/{id}/settings, 404 走 fallback
    // auto) — mount 完会显示 PARSER_LABELS.auto 提示
    // toast 是动态的, 没法先 expect, 我们用 waitFor 配 mockNetwork
    // strategy: 等 kbSettings 拉完 (500ms 网络 roundtrip), 然后上传
    await page.waitForTimeout(1_000)

    // 上传 sample_text.pdf (Phase C.1 fixture → e2e/ copy)
    // playwright config cwd = web/, so path 相对 web/
    const fileChooser = page.locator('input[type="file"]')
    await expect(fileChooser).toBeAttached({ timeout: 5_000 })
    await fileChooser.setInputFiles('tests/e2e/fixtures/sample_text.pdf')

    // 验 PDF 上传 toast — Uploader.tsx 会在 PDF 文件丢入时弹 info toast
    // "1 个 PDF 文件, 正在用 <parserHint> 解析" (parserHint 是
    // PARSER_LABELS.auto = "自动 (推荐) - 按 PDF 类型选" 走 fallback)
    // toast 是 role=status, 含 "解析" 关键词
    const parserToast = page
      .getByRole('status')
      .filter({ hasText: /解析/ })
    await expect(parserToast.first()).toBeVisible({ timeout: 10_000 })

    // 验上传成功 toast (success): "已上传 N 个文件" — 可能在 parser
    // toast 之前或之后, 都 waitFor
    const successToast = page
      .getByRole('status')
      .filter({ hasText: /已上传/ })
    await expect(successToast.first()).toBeVisible({ timeout: 10_000 })

    // 验文档出现在 DocumentList — 表格/列表行 含 sample_text.pdf
    // DocumentList.tsx 表格模式: 找 <td> 含 sample_text.pdf
    // 卡片模式 (移动): 找含 sample_text.pdf 的 box
    // 用 last() 因为可能多个 file row
    await expect(
      page.getByText('sample_text.pdf').first(),
    ).toBeVisible({ timeout: 30_000 })
  })

  test('KBSettings Drawer 渲染所有 PDF 字段 (graceful skip if unmounted)', async ({
    page,
  }) => {
    await loginAsAdmin(page)

    // KBSettings 组件在 C.4 commit 中**只** ship 了 component + vitest
    // test, 没有 mount point (KBMainArea / KBManageTab / Uploader 都
    // 不 import KBSettings). 因此端到端浏览器内**没有**触发
    // "打开 KB PDF 设置 Drawer" 的按钮. 这是已知 gap — 跟 Phase
    // C.4 commit message 描述的 "0 改 Admin*" 一致 (component 处于
    // inert 状态, 等 C.5 真实 PUT /api/kbs/{id}/settings endpoint
    // + KBMainArea 加 trigger button 一起 ship).
    //
    // 验证方法: 在 page 内 grep 关键词 "知识库 PDF 解析设置" (Drawer
    // header) 或 "启用 Tesseract OCR" (Switch label), 不存在 → skip
    // 并留下明确的 原因 (跟 32 commits DDD verify-rungs pattern 同款).
    await page.goto('/')
    await page.waitForLoadState('networkidle', { timeout: 10_000 })

    // 检查 Drawer 是否在 DOM 中 (component isOpen=false 时不渲染,
    // 所以走 check 任意 trigger button — 但目前没有 trigger button)
    const triggerButton = page.getByRole('button', { name: /KB PDF 设置|PDF 解析设置/ })
    const triggerCount = await triggerButton.count()

    if (triggerCount === 0) {
      test.skip(
        true,
        'KBSettings Drawer 组件 ship 在 Phase C.4 但未 mount 到 ' +
          'KBMainArea / KBManageTab / Uploader — 阶段 C.5 backend PUT ' +
          '/api/kbs/{id}/settings + C.5.1 UI wiring 一起 ship 才能 ' +
          '端到端跑. 当前阶段先 skip, INC-011 spec-doc-drift 闭环.',
      )
      return
    }

    // 假如未来加了 trigger button:
    await triggerButton.first().click()
    await expect(
      page.getByText('启用 Tesseract OCR (扫描件)'),
    ).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('启用 Qwen-VL-Max 多模态')).toBeVisible()
    await expect(page.getByText('解析器偏好')).toBeVisible()
    await expect(page.getByText('PDF 缓存大小 (MB)')).toBeVisible()
    await expect(page.getByText('多模态 LLM 月度预算 (¥)')).toBeVisible()
  })

  test('KBSettings 保存 → 重开 → 持久化 (graceful skip — endpoint missing)', async ({
    page,
  }) => {
    await loginAsAdmin(page)

    // 后端 /api/kbs/{id}/settings 在 Phase C.5 spec 阶段**未** ship
    // (spec 7.7KB 写 "0 改 backend runtime" 硬约束, 跟 Phase C.1-C.4
    // 同款). 前端 api.ts 的 kbSettings / updateKBSettings 走 404 →
    // DEFAULT_PDF_SETTINGS fallback.
    //
    // 验证方法: 调一下 updateKBSettings 端点 (用 page.evaluate fetch),
    // 期望 404 — 如果是 200, 端点存在, 后端 C.5 实施跑得比 spec
    // 早, 可以解锁 persistence test.
    const probe = await page.evaluate(async () => {
      const tok = localStorage.getItem('youfu_user') ?? ''
      const r = await fetch('/api/kbs/anything/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      return { status: r.status, body: await r.text() }
    })

    if (probe.status !== 404 && probe.status !== 405) {
      // 后端 endpoint 存在 (C.5 实施跑得比预期早), 但我们没 mount
      // trigger button, 测不出 persistence 流程. 仍然 skip, 留个
      // 文档化的 "endpoint 已 ship, UI wiring 待做" 占位.
      test.skip(
        true,
        `PUT /api/kbs/{id}/settings 后端已 ship (status=${probe.status}), ` +
          '但 UI mount point 缺, 阶段 C.5.1 才能完整跑',
      )
      return
    }

    test.skip(
      true,
      'PUT /api/kbs/{id}/settings endpoint not implemented (Phase C.5 ' +
        '硬约束 "0 改 backend runtime"). 阶段 C.6 INC-011 spec sync ' +
        '闭环. 现阶段 KBSettings 走 DEFAULT_PDF_SETTINGS fallback (跟 ' +
        'KBSettings.tsx .catch 同款), 持久化测无法在 e2e 跑.',
    )
  })
})
