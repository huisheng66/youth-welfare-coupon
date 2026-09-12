import { expect, test } from '@playwright/test'
import { ACC, listMyCoupons, uiLogin } from './helpers.mjs'

// 链路四：时长兑换（T21）+ 券换时长（T24b）。youth1 种子余额 10.00，可兑换券价格 2.00。
// 兑换有确认弹窗（ElMessageBox），成功后余额扣减且券列表新增一张未使用券；
// 券换时长单向流动：仅非兑换所得的券可换回（换回即作废），兑换所得的券不可换回。

test('青年用户用时长相换券：确认弹窗、余额扣减、券出现在列表', async ({ page }) => {
  await uiLogin(page, ...ACC.youth1)
  await page.goto('/user/points')

  const before = await listMyCoupons(page, 'unused')
  const balanceBox = page.locator('.value').first()
  await expect(balanceBox).toHaveText(/^10\.00$/)

  await page.getByRole('button', { name: '兑换', exact: true }).first().click()
  // ElMessageBox 确认文案包含券名与消耗时长
  const confirmBox = page.locator('.el-message-box')
  await expect(confirmBox.getByText(/兑换「.+」/)).toBeVisible()
  await confirmBox.getByRole('button', { name: '确认兑换' }).click()

  // 兑换成功后追问「是否立即出示动态券码」：选稍后再说触发余额/列表刷新
  const askBox = page.locator('.el-message-box')
  await expect(askBox.getByText(/是否立即出示动态券码/)).toBeVisible()
  await askBox.getByRole('button', { name: '稍后再说' }).click()

  await expect(balanceBox).toHaveText(/^8\.00$/, { timeout: 15_000 })
  const after = await listMyCoupons(page, 'unused')
  expect(after.length).toBe(before.length + 1)

  // —— T24b 券换时长（单向流动）——
  // 时长兑换所得的券不可换回：可换清单只含种子演示券，不新增
  const backButtons = page.getByRole('button', { name: '换回时长' })
  await expect(backButtons).toHaveCount(before.length)
  await backButtons.first().click()
  const backConfirm = page.locator('.el-message-box')
  await expect(backConfirm.getByText(/该券将作废，操作不可撤销/)).toBeVisible()
  await backConfirm.getByRole('button', { name: '确认换回' }).click()

  // 换回成功：余额 8.00 → 10.00；被换回的券作废，未使用券数量回到兑换前
  await expect(balanceBox).toHaveText(/^10\.00$/, { timeout: 15_000 })
  const afterBack = await listMyCoupons(page, 'unused')
  expect(afterBack.length).toBe(before.length)

  // 时长换券不受影响：可继续兑换（10 → 8），兑换所得的券依然不可换回
  await expect(page.getByRole('button', { name: '兑换', exact: true }).first()).toBeEnabled()
  await page.getByRole('button', { name: '兑换', exact: true }).first().click()
  await expect(confirmBox.getByText(/兑换「.+」/)).toBeVisible()
  await confirmBox.getByRole('button', { name: '确认兑换' }).click()
  await expect(askBox.getByText(/是否立即出示动态券码/)).toBeVisible()
  await askBox.getByRole('button', { name: '稍后再说' }).click()
  await expect(balanceBox).toHaveText(/^8\.00$/, { timeout: 15_000 })
  await expect(page.getByRole('button', { name: '换回时长' })).toHaveCount(0)
})
