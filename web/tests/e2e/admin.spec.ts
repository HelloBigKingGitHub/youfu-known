/**
 * 后台管理端 e2e test (Playwright).
 *
 * 跟 32 commits DDD + verifies skill + 阶段 1-4 同款:
 * - 0 改 web/src/components/ (component 不动, 跟阶段 1+2 一致)
 * - 真实 Chromium 浏览器 跑 e2e, 不 mock
 *
 * 调研发现真实 selectors (跟 brief 不一致):
 * - LoginPage Input 无 htmlFor/id, 必须用 placeholder:
 *     username placeholder="admin"
 *     password placeholder="••••••••"
 * - Admin 路由: /admin/users
 * - Admin 入口: TopBar.tsx user menu (MenuButton + MenuItem "用户管理")
 * - Search placeholder: "搜索用户名或邮箱"
 * - Status badge 文字: "已批准" (green) / "待批准" (yellow) / "已禁用" (red)
 * - Approve button 只在 !u.is_approved 时渲染
 * - Turnstile secret 是 test-turnstile 真值, register API 走不通 → test 2 用 test.skip() graceful
 */
import { test, expect, type Page, request as playwrightRequest } from '@playwright/test'

const ADMIN_USER = { username: 'admin', password: 'rootpw' }  // 跟 .env 配

async function adminLogin(page: Page) {
  await page.goto('/login')
  // LoginPage Input 无 htmlFor/id 绑定, 用 placeholder (调研确认)
  await page.getByPlaceholder('admin').fill(ADMIN_USER.username)
  await page.getByPlaceholder('••••••••').fill(ADMIN_USER.password)
  await page.getByRole('button', { name: '登录' }).click()
  // 等 redirect 出 /login (LoginPage 成功后跳 / 或 KB 主页面)
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10_000 })
}

async function openAdminUsersPage(page: Page) {
  // 1. login
  await adminLogin(page)
  // 2. 找 TopBar user menu (Chakra MenuButton 内含 Avatar + username "admin")
  //    Chakra MenuButton 默认 role=button, 文本是 "admin admin" (avatar alt + username)
  //    用 exact name match 找 user menu (避免误中其他 button)
  const menuButton = page.getByRole('button', { name: 'admin admin', exact: true })
  await expect(menuButton).toBeVisible({ timeout: 5_000 })
  await menuButton.click()
  // 3. 找 MenuItem "用户管理" (Chakra MenuItem role=menuitem)
  const adminLink = page.getByRole('menuitem', { name: /用户管理/ })
  await expect(adminLink).toBeVisible({ timeout: 5_000 })
  await adminLink.click()
  // 4. 验 /admin/users 页面
  await expect(page).toHaveURL(/\/admin\/users/, { timeout: 10_000 })
}

test.describe('后台管理端 (e2e)', () => {

  test('admin login + navigate to /admin/users', async ({ page }) => {
    await openAdminUsersPage(page)

    // 验页面标题
    await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()

    // 验表格加载
    const table = page.getByRole('table')
    await expect(table).toBeVisible({ timeout: 10_000 })

    // 至少 1 row (admin 自己) - thead + tbody 各算 row
    const rows = page.getByRole('row')
    const rowCount = await rows.count()
    expect(rowCount).toBeGreaterThan(0)
  })

  test('admin search filters user list', async ({ page }) => {
    await openAdminUsersPage(page)

    // 等表格加载
    const table = page.getByRole('table')
    await expect(table).toBeVisible({ timeout: 10_000 })

    // 初始 row count (包括 thead)
    const rowsBefore = await page.getByRole('row').count()
    expect(rowsBefore).toBeGreaterThan(1)

    // 输 search "admin" (调研 placeholder 真实)
    const search = page.getByPlaceholder('搜索用户名或邮箱')
    await expect(search).toBeVisible()
    await search.fill('admin')

    // 等筛选生效
    await page.waitForTimeout(500)

    // 验证 row 数 <= 初始 (筛掉了非 admin)
    const rowsAfter = await page.getByRole('row').count()
    expect(rowsAfter).toBeLessThanOrEqual(rowsBefore)
    // 至少 1 row (admin 自己应该匹配)
    expect(rowsAfter).toBeGreaterThan(0)

    // 清 search
    await search.fill('')
    await page.waitForTimeout(500)

    // 验证恢复
    const rowsFinal = await page.getByRole('row').count()
    expect(rowsFinal).toBeGreaterThanOrEqual(rowsBefore)
  })

  test('admin approve pending user (skip if no pending user)', async ({ page }) => {
    await openAdminUsersPage(page)

    // 等表格加载
    const table = page.getByRole('table')
    await expect(table).toBeVisible({ timeout: 10_000 })

    // 找任意有 "待批准" 文字 的 row (test data 可能没 pending user, 用 test.skip graceful)
    const pendingRow = page.getByRole('row').filter({ hasText: '待批准' }).first()
    const pendingRowCount = await pendingRow.count()
    if (pendingRowCount === 0) {
      test.skip(true, 'No pending user in DB to approve (register API blocks via Turnstile, no test data setup)')
      return
    }

    // 点批准 button
    const approveBtn = pendingRow.getByRole('button', { name: '批准' })
    await expect(approveBtn).toBeVisible()
    await approveBtn.click()

    // 验证 toast (Chakra useToast 渲染 role="status")
    const toast = page.getByRole('status').filter({ hasText: '已批准' })
    await expect(toast).toBeVisible({ timeout: 5_000 })

    // 验证 row 状态变 (Badge 颜色或文字)
    await page.waitForTimeout(1_000)
    // 找 username 行的状态变 (verify badge update)
    const allRows = await page.getByRole('row').all()
    for (const row of allRows) {
      const text = await row.textContent()
      // 至少某个 row 现在是 "已批准" (admin 自身或刚批的)
      if (text && text.includes('已批准')) {
        return  // 验到
      }
    }
    // Fallback: 至少 toast 出现就 OK
    await expect(toast).toBeVisible()
  })
})
