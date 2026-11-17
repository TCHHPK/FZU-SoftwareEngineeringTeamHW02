import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 注意：本项目 package.json 声明了 "type": "module"，
// 在 ESM 下 __dirname 不存在，用它解析路径会得到 undefined（原配置的警告就来自这里）。
// 正确写法是用 import.meta.url 换算目录。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // 开发时把 /api 代理到线上后端；生产环境由后端同源提供，不需要代理
      '/api': {
        target: 'http://47.114.55.115:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    // 交付给后端做静态挂载，产物固定输出到 dist
    outDir: 'dist',
    emptyOutDir: true
  }
})
