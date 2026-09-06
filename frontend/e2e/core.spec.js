import { expect, test } from '@playwright/test'
import { ACC, uiLogin } from './helpers.mjs'

// 链路一：四角色登录与错误恢复（T21）。种子账号来自 E2E 隔离库。

test('超级管理员登录进入管理端仪表盘', async ({ page }) => {
  await uiLogin(page, ...ACC.admin)
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('heading', { name: '今日总览' })).toBeVisible()
  await expect(page.getByText('今日关注')).toBeVisible()
})

test('发券管理员登录进入管理端', async ({ page }) => {
  await uiLogin(page, ...ACC.issuer)
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('heading', { name: '今日总览' })).toBeVisible()
})

test('商家登录进入核销工作台', async ({ page }) => {
  await uiLogin(page, ...ACC.merchant1)
  await expect(page).toHaveURL(/\/merchant$/)
  await expect(page.getByText('今日核销')).toBeVisible()
  await expect(page.getByRole('heading', { name: '券码核销' })).toBeVisible()
})

test('青年用户登录进入用户首页', async ({ page }) => {
  await uiLogin(page, ...ACC.youth1)
  await expect(page).toHaveURL(/\/user$/)
})

test('错误密码登录失败有可读提示并可重试', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('邮箱或用户名').fill(ACC.admin[0])
  await page.getByRole('textbox', { name: '密码', exact: true }).fill('definitely-wrong-pass')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.locator('.el-message').getByText(/错误|失败/)).toBeVisible()
  // 仍停留在登录页，且可立即用正确密码重试成功（错误恢复）
  await expect(page).toHaveURL(/\/login/)
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(ACC.admin[1])
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/admin$/)
})

test('用户退出登录后立即跳转登录页且受保护页被拦截', async ({ page }) => {
  await uiLogin(page, ...ACC.youth1)
  await expect(page).toHaveURL(/\/user$/)
  await page.getByRole('button', { name: '退出', exact: true }).click()
  // logout() 先同步清本地登录态再调后端：守卫看到 token 已清空放行 /login，
  // 点击退出后应立即跳转，无需二次点击或刷新
  await expect(page).toHaveURL(/\/login/)
  // 退出生效后直接访问受保护页仍会被拦回登录页
  await page.goto('/user/coupons')
  await expect(page).toHaveURL(/\/login/)
})
