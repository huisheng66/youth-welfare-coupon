import { test, expect } from '@playwright/test'

// 最小冒烟：登录跳转 / 用户出示动态券码 / 商家核销页。
// 覆盖关键路径，防止 Element Plus 升级或重构静默破坏核心流程。

async function login(page, username, password) {
  await page.goto('/login')
  await page.getByPlaceholder('邮箱或用户名').fill(username)
  // 登录/注册/忘记密码三块表单同时挂在 DOM 里，密码框必须用可访问名限定
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
}

test('管理员登录后进入仪表盘', async ({ page }) => {
  await login(page, 'admin', 'admin123')
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('heading', { name: '今日总览' })).toBeVisible()
  await expect(page.getByText('今日关注')).toBeVisible()
})

test('青年用户出示 30 秒动态券码', async ({ page }) => {
  await login(page, 'youth1', 'youth123')
  await expect(page).toHaveURL(/\/user$/)
  await page.goto('/user/coupons')
  await expect(page.getByRole('heading', { name: '我的优惠券', level: 2 })).toBeVisible()

  await page.getByRole('button', { name: '出示动态券码' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('canvas')).toBeVisible() // 本地渲染二维码，无第三方服务
  await expect(dialog.getByText(/剩余 \d+ 秒后自动刷新/)).toBeVisible()
})

test('商家核销页展示统计与核销入口', async ({ page }) => {
  await login(page, 'merchant1', 'merchant123')
  await expect(page).toHaveURL(/\/merchant$/)
  await expect(page.getByText('今日核销')).toBeVisible()
  await expect(page.getByText('累计核销')).toBeVisible()
  await expect(page.getByRole('heading', { name: '券码核销' })).toBeVisible()
})
