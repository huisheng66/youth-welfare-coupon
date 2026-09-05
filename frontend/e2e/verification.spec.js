import { expect, test } from '@playwright/test'
import { ACC, uiLogin } from './helpers.mjs'

// 链路三：管理员核验用户（T21）。youth2 为种子待审核账号。
// 审核走真实管理端 UI：待审核区勾选 → 批量通过。

test('管理员在待审核区批量通过后，用户状态变为已通过', async ({ page }) => {
  await uiLogin(page, ...ACC.admin)
  await page.goto('/admin/users')

  const pendingBox = page.locator('.pending-box')
  await expect(pendingBox.getByText(/待审核申请（\d+）/)).toBeVisible()

  // 勾选 youth2 所在行后批量通过
  const youth2Row = pendingBox.getByRole('row').filter({ hasText: ACC.youth2[0] })
  await youth2Row.locator('.el-checkbox').first().click()
  await pendingBox.getByRole('button', { name: /批量通过/ }).click()
  // ElMessageBox 确认
  const confirmBox = page.locator('.el-message-box')
  await expect(confirmBox.getByText(/确认批量通过/)).toBeVisible()
  await confirmBox.getByRole('button', { name: '确认通过' }).click()

  // 批量通过后待审核区消失，表示无剩余申请
  await expect(pendingBox).toHaveCount(0, { timeout: 15_000 })

  // 状态以接口结果为准：youth2 已是 approved
  const me = await page.request.get('/api/users', { params: { q: ACC.youth2[0] } })
  expect(me.ok()).toBeTruthy()
  const body = await me.json()
  const y2 = body.items.find((i) => i.username === ACC.youth2[0])
  expect(y2?.verify_status).toBe('approved')
})
