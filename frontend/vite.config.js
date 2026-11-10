import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理: /api/rag -> 8001, /api/cs -> 8002, /api/eval -> 8003, /api/admin -> 8004
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api/rag': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/rag/, ''),
      },
      '/api/cs': {
        target: 'http://localhost:8002',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/cs/, ''),
      },
      '/api/eval': {
        target: 'http://localhost:8003',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/eval/, ''),
      },
      '/api/admin': {
        target: 'http://localhost:8004',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/admin/, ''),
      },
    },
  },
})
