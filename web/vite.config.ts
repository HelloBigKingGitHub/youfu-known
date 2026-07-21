import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置:
// - React plugin
// - 开发服务器端口 5173
// - /api 反代 -> 后端 8000 (生产) / 8765 (dev)
//   端口可通过 .env / .env.local 中 YOUFU_VITE_API_TARGET 覆盖, 例如:
//   YOUFU_VITE_API_TARGET=http://127.0.0.1:8765
export default defineConfig(({ mode }) => {
  // loadEnv 把 VITE_ / 你自定义的 prefix 注入进来, 我们用自定义前缀
  const env = loadEnv(mode, process.cwd(), ['YOUFU_', 'VITE_'])
  const target = env.YOUFU_VITE_API_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
        },
      },
    },
  }
})