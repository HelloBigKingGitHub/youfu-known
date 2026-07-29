// One-off: 验证前端能友好展示后端 400 / 401 错误, 截图
import { chromium } from 'playwright-core'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const OUT = resolve('screenshots')
await mkdir(OUT, { recursive: true })

const browser = await chromium.launch({
  executablePath: '/usr/bin/chromium',
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
  headless: true,
})
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } })
const page = await ctx.newPage()

async function snap(name) {
  const p = resolve(OUT, `${name}.png`)
  await page.screenshot({ path: p, fullPage: false })
  console.log('saved', p)
}

async function solveCaptcha() {
  // Vite dev: 暴露在 window.__captchaCode
  const code = await page.evaluate(() => window.__captchaCode?.())
  if (!code) throw new Error('no captcha code (dev only)')
  const input = page.locator('[data-testid="captcha-input"]')
  await input.fill(code)
  await page.locator('[data-testid="captcha-verify"]').click()
  await page.waitForSelector('[data-testid="captcha-success"]', { timeout: 4000 })
}

console.log('1) /register 短密码 -> 后端字段错误')
await page.goto('http://127.0.0.1:5177/register', { waitUntil: 'networkidle' })
await page.locator('input').first().fill('alice_test')
await page.locator('input[type="password"]').first().fill('123456')
await page.locator('input[type="password"]').nth(1).fill('123456')
await solveCaptcha()
await page.locator('button:has-text("注册")').click()
await page.waitForSelector('text=密码至少 8 个字符', { timeout: 10000 })
await snap('register-field-errors')

console.log('1b) /register 短密码 + 邮箱非法 -> 多字段')
await page.goto('http://127.0.0.1:5177/register', { waitUntil: 'networkidle' })
const uname = `bob_${Date.now().toString(36).slice(-5)}`
await page.locator('input').first().fill(uname)
await page.locator('input').nth(1).fill('notanemail')
await page.locator('input[type="password"]').first().fill('123456')
await page.locator('input[type="password"]').nth(1).fill('123456')
await solveCaptcha()
page.on('response', (r) => {
  if (r.url().includes('/api/')) console.log('[api]', r.status(), r.url())
})
await page.locator('button:has-text("注册")').click()
await page.waitForTimeout(3000)
await snap('register-field-errors-multi')
console.log('after click')

console.log('2) /login 错密码 -> 表单错误')
await page.goto('http://127.0.0.1:5177/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill('admin')
await page.locator('input[type="password"]').fill('wrong-pw')
await page.locator('button:has-text("登录")').click()
await page.waitForSelector('text=用户名或密码错误', { timeout: 8000 })
await snap('login-form-error')

console.log('3) /login 网络断开模拟 -> toast')
await page.route('**/api/auth/login', (route) => route.abort('failed'))
await page.locator('input').first().fill('admin')
await page.locator('input[type="password"]').fill('whatever')
await page.locator('button:has-text("登录")').click()
await page.waitForSelector('text=/无法连接|登录失败/', { timeout: 8000 })
await snap('login-toast-error')

await browser.close()
console.log('DONE')
