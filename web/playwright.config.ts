import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30 * 1000,
  expect: { timeout: 5 * 1000 },
  retries: 0,
  workers: 1,  // admin 共享 backend db, 不要并行
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,  // 复用 dev server (实测 Vite + 8000 已经在跑)
    timeout: 60 * 1000,
  },
})
