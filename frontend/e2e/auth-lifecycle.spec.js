import { expect, test } from '@playwright/test'
import { ACC, uiLogin } from './helpers.mjs'

// 链路五：密码生命周期与会话失效（T21）。
// 首次改密强制约束、改密后旧会话废止、Cookie 失效后被守卫拦回登录页。

test('初始密码账号被强制改密，改密后须重新登录', async ({ page }) => {
  // 0. 超管通过 API 创建商家账号（must_change_password=true）
  const adminCtx = page.context()
  await uiLogin(page, ...ACC.admin)
  const merchants = await page.request.get('/api/merchants')
  const merchantList = await merchants.json()
  const merchantId = merchantList.items[0].id
  const username = `e2e_merchant_${Date.now()}`
  const created = await page.request.post('/api/auth/merchant-accounts', {
    data: {
      username,
      password: 'Start12345',
      display_name: 'E2E 商家',
      merchant_id: merchantId,
    },
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
  })
  expect(created.ok()).toBeTruthy()

  // 1. 新账号登录：被路由守卫强制停在账号设置页
  const userCtx = await adminCtx.browser().newContext()
  const userPage = await userCtx.newPage()
  await uiLogin(userPage, username, 'Start12345')
  await expect(userPage).toHaveURL(/\/merchant\/settings$/)

  // 2. 设置页只暴露改密表单（绑定邮箱表单在首改密期间隐藏），三个密码输入框
  const pwInputs = userPage.locator('input[type=password]')
  await expect(pwInputs).toHaveCount(3)
  await pwInputs.nth(0).fill('Start12345')
  await pwInputs.nth(1).fill('NewPass12345')
  await pwInputs.nth(2).fill('NewPass12345')
  await userPage.getByRole('button', { name: '保存新密码' }).click()

  // 3. 改密成功后旧会话废止：回到登录页
  await expect(userPage).toHaveURL(/\/login/, { timeout: 15_000 })

  // 4. 旧密码不可再用，新密码登录后不再被强制改密
  await uiLogin(userPage, username, 'NewPass12345')
  await expect(userPage).toHaveURL(/\/merchant$/)

  await userCtx.close()
})

test('Cookie 会话失效后被认证守卫拦回登录页', async ({ page }) => {
  await uiLogin(page, ...ACC.youth1)
  await expect(page).toHaveURL(/\/user$/)
  // 模拟服务端会话废止（改密/停用等）：客户端凭据清空
  await page.context().clearCookies()
  await page.goto('/user/coupons')
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
})
