// 门头照 UI 全链路（T25）：管理端真实选择文件上传 → 缩略图回显 → 用户端详情页展示照片。
// 补 API 上传用例之外的缺口：label+input 选择文件的交互路径。

import { expect, test } from '@playwright/test'
import { ACC, uiLogin } from './helpers.mjs'

const CSRF = { 'X-Requested-With': 'XMLHttpRequest' }
// 合法 1x1 PNG
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
)

test('管理员经 UI 上传门头照，用户端详情页展示', async ({ page }) => {
  await uiLogin(page, ...ACC.admin)
  // 管理员阶段先确定门店 id（商家列表对 user 角色是 403，切换身份后不能再查）
  const merchants = await page.request.get('/api/merchants', { headers: CSRF }).then((r) => r.json())
  const storeId = merchants.items.find((m) => m.name === '示例餐饮店')?.id
  expect(storeId, 'seeded merchant present').toBeTruthy()

  await page.goto('/admin/merchants')
  await page.locator('.el-table__row', { hasText: '示例餐饮店' }).first().getByRole('button', { name: '编辑' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // label 形式的上传入口 → 通过真实 input 选择文件
  await expect(dialog.getByText('上传门头照')).toBeVisible()
  await dialog.locator('input[type=file]').setInputFiles({ name: 'photo.png', mimeType: 'image/png', buffer: PNG })

  // 上传成功：入口变「更换照片」，缩略图真实加载（同源 cookie 认证）
  await expect(dialog.getByText('更换照片')).toBeVisible({ timeout: 10_000 })
  const thumb = dialog.locator('img.photo-thumb')
  await expect(thumb).toBeVisible()
  await expect.poll(async () => thumb.evaluate((el) => el.naturalWidth > 0), { timeout: 10_000 }).toBe(true)
  await dialog.getByRole('button', { name: '取消' }).click()

  // 换用户身份：详情页照片可见
  await page.getByRole('button', { name: '退出登录' }).click()
  await page.waitForURL(/\/login/)
  await uiLogin(page, ...ACC.youth1)
  await page.goto(`/user/merchants/${storeId}`)
  const photo = page.locator('img.photo')
  await expect(photo).toBeVisible()
  await expect.poll(async () => photo.evaluate((el) => el.naturalWidth > 0), { timeout: 10_000 }).toBe(true)
  await expect(page.getByText('商家暂未上传门头照')).toBeHidden()
})
