import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import basicSsl from '@vitejs/plugin-basic-ssl'

// HTTPS 开发：手机用局域网 IP 访问时也能调摄像头（需浏览器信任自签证书一次）
// API 仍由本机 Vite 代理到 http://127.0.0.1:19001
export default defineConfig({
  plugins: [vue(), basicSsl()],
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
})
