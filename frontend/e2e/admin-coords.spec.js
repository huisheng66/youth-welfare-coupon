// 商家坐标编辑（T25 补充）：整串粘贴自动分列、在线搜索入口（未配 key 时给出配置提示），
// 坐标保存后用户端详情页从地址搜索兜底升级为三家地图精确导航。

import { expect, test } from '@playwright/test'
import { ACC, uiLogin } from './helpers.mjs'

const CSRF = { 'X-Requested-With': 'XMLHttpRequest' }

test('粘贴坐标自动分列，保存后用户端出现三家导航直链', async ({ page }) => {
  await uiLogin(page, ...ACC.admin)
  // 管理员阶段先确定门店 id（商家列表对 user 角色是 403）
  const merchants = await page.request.get('/api/merchants', { headers: CSRF }).then((r) => r.json())
  const store = merchants.items.find((m) => m.name === '示例书店')
  expect(store, 'seeded bookstore present').toBeTruthy()

  await page.goto('/admin/merchants')
  await page.locator('.el-table__row', { hasText: '示例书店' }).first().getByRole('button', { name: '编辑' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByPlaceholder('经度，如 116.397428')).toHaveValue('')

  // 腾讯拾取器格式的 lat,lng 顺序也能自动识别并分列
  await dialog.getByPlaceholder(/整串粘贴坐标/).fill('39.909230,116.397428')
  await expect(dialog.getByPlaceholder('经度，如 116.397428')).toHaveValue('116.397428')
  await expect(dialog.getByPlaceholder('纬度，如 39.909230')).toHaveValue('39.909230')

  await dialog.getByRole('button', { name: '保存商家' }).click()
  await expect(dialog).toBeHidden()

  // 用户端：书店详情页从「高德地图搜索」兜底升级为精确导航直链
  await page.getByRole('button', { name: '退出登录' }).click()
  await page.waitForURL(/\/login/)
  await uiLogin(page, ...ACC.youth1)
  await page.goto(`/user/merchants/${store.id}`)
  const amap = page.getByRole('link', { name: '高德地图', exact: true })
  await expect(amap).toHaveAttribute('href', /uri\.amap\.com\/navigation\?.*to=116\.397428,39\.909230/)
  await expect(page.getByRole('link', { name: '腾讯地图', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '百度地图', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '高德地图搜索' })).toBeHidden()
})

test('未配置 AMAP_WEB_KEY 时在线搜索返回配置提示', async ({ page }) => {
  await uiLogin(page, ...ACC.admin)
  await page.goto('/admin/merchants')
  await page.locator('.el-table__row', { hasText: '示例餐饮店' }).first().getByRole('button', { name: '编辑' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: '搜索坐标' }).click()
  await expect(page.locator('.el-message').first()).toContainText('AMAP_WEB_KEY', { timeout: 10_000 })
})
