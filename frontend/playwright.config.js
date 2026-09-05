import { defineConfig } from '@playwright/test'
import { existsSync, mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// T21：跨平台可重复运行的 E2E 套件。
// - 独立端口（默认 19011/5199），不占用开发服务 19001/5173；
// - 每次运行在系统临时目录新建随机 SQLite 库，绝不读写开发数据；
// - 命令在 Windows 与 Linux CI 下一致：python 路径按平台解析 venv。
// 运行：npm run e2e（首次需 npx playwright install chromium）

// playwright 会转译本配置：HERE 即本文件所在目录（frontend/e2e）
const HERE = path.dirname(fileURLToPath(import.meta.url))
// 双保险：playwright 加载上下文中 import.meta.url 异常时回退到进程 cwd
const FRONTEND_ROOT = existsSync(path.join(process.cwd(), 'vite.config.js'))
  ? process.cwd()
  : path.resolve(HERE, '..')
const BACKEND_ROOT = path.resolve(FRONTEND_ROOT, '..', 'backend')

const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT || 19011)
const FRONTEND_PORT = Number(process.env.E2E_FRONT_PORT || 5199)

const isWin = process.platform === 'win32'
const venvPython = path.join(
  BACKEND_ROOT,
  '.venv',
  isWin ? 'Scripts' : 'bin',
  isWin ? 'python.exe' : 'python',
)
const PYTHON = existsSync(venvPython) ? venvPython : 'python'

// 随机隔离测试库：每次运行全新建表 + 种子数据
const e2eDir = path.join(os.tmpdir(), `welfare-e2e-${process.pid}-${Date.now()}`)
mkdirSync(e2eDir, { recursive: true })
const DATABASE_URL = `sqlite:///${e2eDir.split(path.sep).join('/')}/e2e.db`

const BACKEND_ENV = {
  ...process.env,
  APP_ENV: 'development',
  SECRET_KEY: 'e2e-fixed-test-secret-key-32b', // secret-scan:allow E2E 临时库测试专用，非生产凭据
  DATABASE_URL,
  SEED_DEMO_ACCOUNTS: 'true',
  RATE_LIMIT_BACKEND: 'memory',
  GLOBAL_IP_MAX_REQUESTS: '0',
  LOGIN_MAX_FAILS: '50',
  COUPON_EXPIRE_SCAN_INTERVAL: '0',
  MAIL_SERVER: '',
  MAIL_USERNAME: '',
  MAIL_PASSWORD: '',
  MAIL_FROM: '',
  AUTH_ALLOW_BEARER: 'true',
  OPENAPI_ENABLED: 'false',
}

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'line' : 'list',
  // 双会话核销等链路依赖同一份种子数据，串行保证可重复
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: `https://127.0.0.1:${FRONTEND_PORT}`,
    ignoreHTTPSErrors: true, // vite dev 使用自签证书
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'zh-CN',
  },
  webServer: [
    {
      command: `"${PYTHON}" -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: BACKEND_ROOT,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      // 显式继承 process.env：Windows 下覆盖式 env 会丢失 SystemRoot，
      // 导致 spawn cmd.exe ENOENT
      env: BACKEND_ENV,
    },
    {
      // 经启动器在真实路径上启动 vite（见 e2e/run-frontend.mjs 顶注）：
      // 本进程 cwd 用 ASCII 临时目录，规避部分 shell 会话对非 ASCII
      // 命令行的编码问题；vite 自身以真实项目根为 root
      command: `"${process.execPath}" "${path.join(FRONTEND_ROOT, 'e2e', 'run-frontend.mjs')}" "${FRONTEND_ROOT}" ${FRONTEND_PORT}`,
      cwd: os.tmpdir(),
      url: `https://127.0.0.1:${FRONTEND_PORT}/`,
      ignoreHTTPSErrors: true, // 自签证书的探活也要放行
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        E2E_BACKEND_PORT: String(BACKEND_PORT),
        E2E_FRONT_PORT: String(FRONTEND_PORT),
      },
    },
  ],
})
