import { defineConfig } from '@playwright/test'

// 最小 E2E：真实启动后端（独立 e2e.db，含种子账号）+ Vite dev server。
// 运行：npm run e2e（首次需 npx playwright install chromium）
const BACKEND_PORT = 19001
const FRONTEND_PORT = 5173

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'line' : 'list',
  use: {
    baseURL: `https://127.0.0.1:${FRONTEND_PORT}`,
    ignoreHTTPSErrors: true, // vite dev 使用自签证书
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command:
        'rm -f data/e2e.db && ' +
        'DATABASE_URL=sqlite:///./data/e2e.db ' +
        'SEED_DEMO_ACCOUNTS=true ' +
        'RATE_LIMIT_BACKEND=memory GLOBAL_IP_MAX_REQUESTS=0 ' +
        'COUPON_EXPIRE_SCAN_INTERVAL=0 ' +
        'MAIL_SERVER= MAIL_USERNAME= MAIL_PASSWORD= MAIL_FROM= ' +
        '.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 19001',
      cwd: '../backend',
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT}`,
      url: `https://127.0.0.1:${FRONTEND_PORT}/`,
      ignoreHTTPSErrors: true, // 自签证书的探活也要放行
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
