import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import basicSsl from '@vitejs/plugin-basic-ssl'

// HTTPS 寮€鍙戯細鎵嬫満鐢ㄥ眬鍩熺綉 IP 璁块棶鏃朵篃鑳借皟鎽勫儚澶达紙闇€娴忚鍣ㄤ俊浠昏嚜绛捐瘉涔︿竴娆★級
// API 浠嶇敱鏈満 Vite 浠ｇ悊鍒?http://127.0.0.1:19001
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

