import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import basicSsl from '@vitejs/plugin-basic-ssl'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { readdirSync, readFileSync, writeFileSync, statSync, existsSync } from 'node:fs'
import { join, extname } from 'node:path'
import { gzipSync, brotliCompressSync, constants } from 'node:zlib'

// HTTPS dev: so phones on LAN IP can also open camera (browser needs to trust self-signed cert once)
// API is proxied by Vite dev server to http://127.0.0.1:19001
// T21：端口与后端代理目标可经环境变量覆盖，E2E 用独立端口，不占用开发服务
const SERVER_PORT = Number(process.env.E2E_FRONT_PORT || 5173)
const BACKEND_ORIGIN = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 19001)}`
// T18：构建分析入口统一——`npm run analyze` 或 `--mode=analyze` / `--mode analyze` 均可
const analyze =
  process.argv.includes('--mode=analyze') ||
  process.argv.includes('--mode') && process.argv[process.argv.indexOf('--mode') + 1] === 'analyze'
const visualizer = analyze
  ? (await import('rollup-plugin-visualizer')).visualizer({
      open: true,
      filename: 'dist/stats.html',
      gzipSize: true,
      brotliSize: true,
    })
  : null

/**零依赖预压缩插件：构建结束后为 assets/*.js|css 生成 .br 与 .gz。
 *
 *为什么需要：Vite dev 与 preview 默认**不压缩**，实测首包 entry 以 235KB
 * 明文传输（gzip 后仅约 84KB）。手机端通过 Wi‑Fi + HTTPS 访问时，这个差距
 * 直接表现为「打开很慢 / 交互迟滞」。生产 Nginx 侧虽配了 gzip，但实时压缩
 * 每次请求都要消耗 CPU；预生成静态文件后可由 gzip_static / brotli_static
 * 直接回源，既省 CPU 又省传输。
 */
function compressionPlugin() {
  const COMPRESSIBLE = new Set(['.js', '.css', '.html', '.json', '.svg'])
  const walk = (dir, out = []) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) walk(full, out)
      else out.push(full)
    }
    return out
  }
  return {
    name: 'youth-precompress',
    apply: 'build',
    closeBundle() {
      const dir = 'dist'
      if (!existsSync(dir)) return
      let gzCount = 0
      let brCount = 0
      for (const file of walk(dir)) {
        if (!COMPRESSIBLE.has(extname(file))) continue
        const raw = readFileSync(file)
        if (raw.length < 1024) continue // 小文件压缩收益抵不上额外IO
        writeFileSync(`${file}.gz`, gzipSync(raw, { level: 9 }))
        writeFileSync(
          `${file}.br`,
          brotliCompressSync(raw, {
            params: {
              [constants.BROTLI_PARAM_QUALITY]: 11,
              [constants.BROTLI_PARAM_SIZE_HINT]: raw.length,
            },
          }),
        )
        gzCount += 1
        brCount += 1
      }
      // eslint-disable-next-line no-console
      console.log(`\n预压缩完成：${gzCount} 个 .gz / ${brCount} 个 .br（供 Nginx gzip_static / brotli_static 使用）`)
    },
  }
}

/** 构建收尾：产出一份可直接 include 的 Nginx 缓存/压缩片段。
 *
 * 缓存策略要点（容易配错，故随构建生成而不是手写）：
 * - `/assets/` 下的文件带内容哈希 → 可安全 immutable 长缓存；
 * - `index.html` 不带哈希 → 必须 no-cache，否则发版后用户仍加载旧入口脚本。
 * Vite 自身不设置 HTTP 头，缓存策略只能由Nginx/CDN 层落地，因此这里输出配置。
 */
function hashedAssetsCachePlugin() {
  return {
    name: 'youth-assets-cache',
    apply: 'build',
    closeBundle() {
      const snippet =
        '# 由 frontend/vite.config.js 生成：带哈希产物长缓存 + 预压缩回源\n' +
        '# include 到 server 块中；gzip_static/brotli_static 直接回源 .gz/.br，避免实时压缩吃 CPU\n' +
        'location /assets/ {\n' +
        '    add_header Cache-Control "public, max-age=31536000, immutable";\n' +
        '    gzip_static on;\n' +
        '    brotli_static on;\n' +
        '    brotli on;\n' +
        '    gzip on;\n' +
        '    gzip_types application/javascript text/css application/json image/svg+xml;\n' +
        '}\n' +
        'location = /index.html {\n' +
        '    add_header Cache-Control "no-cache";\n' +
        '}\n'
      try {
        if (!existsSync('dist')) return
        writeFileSync(join('dist', '_assets-cache.conf'), snippet)
      } catch {
        /* 产物目录不可写时静默跳过，不影响构建结果 */
      }
    },
  }
}

export default defineConfig({
  plugins: [
    vue(),
    basicSsl(),
    // Element Plus 按需引入：组件自动注册，ElMessage/ElMessageBox 等 API 自动导入
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
    ...(visualizer ? [visualizer] : []),
    // 预压缩 + Nginx 缓存片段：均为构建收尾产物，不影响打包语义
    compressionPlugin(),
    hashedAssetsCachePlugin(),
  ],
  server: {
    host: '0.0.0.0',
    port: SERVER_PORT,
    strictPort: true,
    https: true,
    // 交互优化：把体积大、变动少的依赖预先打包成单文件。
    // 默认按需扫描会为 element-plus 生成数十个细碎请求（实测登录页
    // 23 个、管理端 53 个），首屏往返次数多；显式预构建后合并为少数
    // 几个大文件，dev 冷启动与首屏转译都明显更快。
    optimizeDeps: {
      include: [
        'vue',
        'vue-router',
        'axios',
        'element-plus/es/components/config-provider/index',
        'element-plus/es/components/button/index',
        'element-plus/es/components/input/index',
        'element-plus/es/components/table/index',
        'element-plus/es/components/table-column/index',
        'element-plus/es/components/dialog/index',
        'element-plus/es/components/form/index',
        'element-plus/es/components/form-item/index',
        'element-plus/es/components/select/index',
        'element-plus/es/components/pagination/index',
        'element-plus/es/components/date-picker/index',
        'element-plus/es/components/descriptions/index',
        'element-plus/es/components/tabs/index',
        'element-plus/es/components/tag/index',
        'element-plus/es/components/badge/index',
        'element-plus/es/components/alert/index',
        'element-plus/es/components/message/index',
        'element-plus/es/components/message-box/index',
        'element-plus/es/components/loading/index',
        'element-plus/es/components/drawer/index',
        'element-plus/es/components/menu/index',
        'element-plus/es/components/icon/index',
        'element-plus/es/components/switch/index',
        'element-plus/es/components/empty/index',
        'element-plus/es/components/result/index',
        'element-plus/es/components/tooltip/index',
        'element-plus/es/components/input-number/index',
      ],
    },
    hmr: {
      protocol: 'wss',
      clientPort: SERVER_PORT,
    },
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        // 重写 Origin/Host 为后端地址：通过 Vite 代理的请求，
        // 后端 CSRF 中间件要求来源与 Host 同源或命中白名单。
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
    // 交互优化：开启 CSS/JS 压缩 + 预生成 .gz/.br 预压缩产物。
    // 未压缩时首包 entry 约 235KB，gzip 后约 84KB，brotli 约 68KB；
    // 手机端走 Wi‑Fi + HTTPS 时差距非常明显（这是「加载很久」的主因）。
    cssCodeSplit: true,
    // sourcemap 生产不产出：省掉几十万行映射文件的构建与传输开销
    sourcemap: false,
    reportCompressedSize: false,
    rollupOptions: {
      output: {
        // 分块策略：只把**确实被多处共用**且体积可观的依赖独立出来。
        // 不要把 element-plus 整包合一——实测那样会产出 933KB 单文件，
        // 反而比拆分后更大（Element Plus 各组件间共享底层工具与样式，
        // 合并会重复打包）。按需引入 + 路由懒加载已能保证未用组件不进包。
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/vue/') || id.includes('vue-router') || id.includes('@vue/')) {
            return 'vendor-vue'
          }
          // 重型扫码库只在商家核销页用到，单独成 chunk 按需加载，
          // 避免首屏为用不到的条码格式（AZTEC/CODE_39 等）付出代价。
          if (id.includes('html5-qrcode') || id.includes('qrcode')) return 'vendor-scanner'
          if (id.includes('axios')) return 'vendor-http'
        },
      },
    },
  },
})

