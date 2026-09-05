import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import basicSsl from '@vitejs/plugin-basic-ssl'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// HTTPS dev: so phones on LAN IP can also open camera (browser needs to trust self-signed cert once)
// API is proxied by Vite dev server to http://127.0.0.1:19001
// T21：端口与后端代理目标可经环境变量覆盖，E2E 用独立端口，不占用开发服务
const SERVER_PORT = Number(process.env.E2E_FRONT_PORT || 5173)
const BACKEND_ORIGIN = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 19001)}`
const analyze = process.argv.includes('--mode=analyze')
const visualizer = analyze
  ? (await import('rollup-plugin-visualizer')).visualizer({
      open: true,
      filename: 'dist/stats.html',
      gzipSize: true,
      brotliSize: true,
    })
  : null

export default defineConfig({
  plugins: [
    vue(),
    basicSsl(),
    // Element Plus 按需引入：组件自动注册，ElMessage/ElMessageBox 等 API 自动导入
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
    ...(visualizer ? [visualizer] : []),
  ],
  server: {
    host: '0.0.0.0',
    port: SERVER_PORT,
    strictPort: true,
    https: true,
    hmr: {
      protocol: 'wss',
      clientPort: SERVER_PORT,
    },
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    https: true,
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Only split vue core; element-plus is on-demand imported by unplugin,
        // let Vite auto-chunk its components alongside the views that use them.
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router'],
        },
      },
    },
  },
})
