import { expect, test } from '@playwright/test'
import { ACC, adminIssueCoupon, adminVoidCoupon, listMyCoupons, uiLogin } from './helpers.mjs'

// 链路二：双会话真实核销（T21 核心）。管理员发券 → 用户出码 → 商家粘贴码核销
// → 用户侧轮询立即看到成功。独立浏览器上下文模拟三方。

test('管理员发券后，用户出示动态码、商家核销、用户看到核销成功', async ({ browser }) => {
  // 1. 管理员：发一张券给 youth1（最新券出现在用户券列表首位）
  const adminCtx = await browser.newContext()
  const adminPage = await adminCtx.newPage()
  await uiLogin(adminPage, ...ACC.admin)
  await adminIssueCoupon(adminPage, 'youth1', { merchantName: '示例餐饮店' })

  // 2. 用户：出示动态券码
  const userCtx = await browser.newContext()
  const userPage = await userCtx.newPage()
  await uiLogin(userPage, ...ACC.youth1)
  await userPage.goto('/user/coupons')
  const dialog = userPage.getByRole('dialog')
  await userPage.getByRole('button', { name: '出示动态券码' }).first().click()
  await expect(dialog.locator('canvas')).toBeVisible() // 本地渲染二维码，无第三方服务
  const liveCode = await dialog.locator('textarea').inputValue()
  expect(liveCode.length).toBeGreaterThan(40)

  // 3. 商家：粘贴动态码 → 预览 → 确认核销
  const merchantCtx = await browser.newContext()
  const merchantPage = await merchantCtx.newPage()
  await uiLogin(merchantPage, ...ACC.merchant1)
  await merchantPage.goto('/merchant')
  await merchantPage.getByPlaceholder(/粘贴动态券码/).fill(liveCode)
  await merchantPage.getByRole('button', { name: '预览券信息' }).click()
  await expect(merchantPage.getByText('未使用')).toBeVisible() // 预览状态
  await expect(merchantPage.getByRole('button', { name: '确认核销' })).toBeEnabled()
  await merchantPage.getByRole('button', { name: '确认核销' }).click()
  // onRedeem 有 ElMessageBox 二次确认（弹窗内按钮同名，需限定作用域）
  const redeemConfirm = merchantPage.locator('.el-message-box')
  await expect(redeemConfirm.getByText(/确认核销「/)).toBeVisible()
  await redeemConfirm.getByRole('button', { name: '确认核销' }).click()

  // 4. 核销结果以流水为准（结果面板受页面时序影响）；用户侧轮询应几乎
  //    立即将弹窗切换为成功态
  await expect
    .poll(
      async () => {
        const logs = await merchantPage.request.get('/api/coupons/redemptions', {
          params: { result: 'success' },
        })
        return (await logs.json()).total
      },
      { timeout: 20_000 },
    )
    .toBeGreaterThanOrEqual(1)

  await expect(dialog.getByRole('heading', { name: '核销成功' })).toBeVisible({ timeout: 20_000 })
  // 关闭弹窗后列表里确实存在已使用券
  await dialog.getByRole('button', { name: '完成' }).click()
  const coupons = await listMyCoupons(userPage)
  expect(coupons.some((c) => c.status === 'used')).toBeTruthy()

  await adminCtx.close()
  await userCtx.close()
  await merchantCtx.close()
})

test('作废券不可出码：出示按钮禁用、列表状态为已作废', async ({ browser }) => {
  const adminCtx = await browser.newContext()
  const adminPage = await adminCtx.newPage()
  await uiLogin(adminPage, ...ACC.admin)
  const issued = await adminIssueCoupon(adminPage, 'youth1', { merchantName: '示例餐饮店' })
  await adminVoidCoupon(adminPage, issued[0].id)

  const userCtx = await browser.newContext()
  const userPage = await userCtx.newPage()
  await uiLogin(userPage, ...ACC.youth1)
  await userPage.goto('/user/coupons')

  // 新发的券在列表首位且已作废：出示按钮禁用，无法进入核销链路
  const voidCard = userPage.locator('.coupon-card').filter({ hasText: '已作废' }).first()
  await expect(voidCard).toBeVisible()
  await expect(voidCard.getByRole('button', { name: '出示动态券码' })).toBeDisabled()

  await adminCtx.close()
  await userCtx.close()
})
