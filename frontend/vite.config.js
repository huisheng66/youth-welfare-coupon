import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import basicSsl from '@vitejs/plugin-basic-ssl'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// HTTPS dev: so phones on LAN IP can also open camera (browser needs to trust self-signed cert once)
// API is proxied by Vite dev server to http://127.0.0.1:19001
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
    port: 5173,
    strictPort: true,
    https: true,
    hmr: {
      protocol: 'wss',
      clientPort: 5173,
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:19001',
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
