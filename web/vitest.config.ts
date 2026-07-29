// Vitest 配置: jsdom 环境 + @testing-library/jest-dom 断言扩展
//   - 独立于 vite.config.ts (开发 / 构建 用), 避免污染 dev/build 行为
//   - 复用 vite.config.ts 的 React plugin (通过 @vitejs/plugin-react 的 import 也可以,
//     但 vitest 默认用 esbuild 处理 .tsx, 这里我们显式指定 plugin 以保证一致)
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true, // 让 describe/it/expect/vi 直接可用, 跟 apiErrors.test.ts 风格一致
    environment: 'jsdom', // Chakra UI 需要 DOM (jsdom 跟 chakra-emotion 兼容)
    setupFiles: ['./src/test-setup.ts'], // 加载 @testing-library/jest-dom 匹配器
    css: false, // Chakra UI 走 emotion CSS-in-JS, 不需要真解析 .css 文件
  },
})
