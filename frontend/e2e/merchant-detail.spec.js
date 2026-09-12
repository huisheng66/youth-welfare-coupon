// 商家详情页（T25）：券行「指定商家」链接进入详情，展示门头照/地址/电话并可唤起导航。
// 种子商家「示例餐饮店」带 GCJ-02 演示坐标，因此断言三家地图导航直链。

import { expect, test } from '@playwright/test'
import { ACC, uiLogin } from './helpers.mjs'

test.describe('商家详情页', () => {
  test('从券行进入详情，展示门店资料与三家地图导航链接', async ({ page }) => {
    await uiLogin(page, ...ACC.youth1)
    await page.goto('/user/coupons')
    await expect(page.getByRole('heading', { name: '我的优惠券' })).toBeVisible()

    // 券行「指定商家：」后为可点链接（渲染为 a.merchant-link），进入详情页
    const merchantLink = page.locator('.coupon-card a.merchant-link').first()
    await expect(merchantLink).toBeVisible()
    const merchantName = (await merchantLink.innerText()).trim()
    expect(merchantName.length).toBeGreaterThan(0)
    await merchantLink.click()
    await expect(page).toHaveURL(/\/user\/merchants\//)
    await expect(page.getByRole('heading', { name: merchantName })).toBeVisible()

    // 位置卡：地址 + 复制按钮 + 三家地图导航直链（GCJ-02 坐标 → 各家 URI）
    await expect(page.getByText('示例市青年路 88 号 1 层 101 室')).toBeVisible()
    await expect(page.getByRole('button', { name: '复制' }).first()).toBeVisible()
    const amap = page.getByRole('link', { name: '高德地图', exact: true })
    const tencent = page.getByRole('link', { name: '腾讯地图', exact: true })
    const baidu = page.getByRole('link', { name: '百度地图', exact: true })
    await expect(amap).toHaveAttribute('href', /uri\.amap\.com\/navigation\?.*to=116\.397428,39\.909230/)
    await expect(amap).toHaveAttribute('target', '_blank')
    await expect(tencent).toHaveAttribute('href', /apis\.map\.qq\.com\/uri\/v1\/routeplan\?.*tocoord=39\.909230,116\.397428/)
    await expect(baidu).toHaveAttribute('href', /api\.map\.baidu\.com\/direction\?.*coord_type=gcj02/)

    // 电话卡：tel: 链接（手机端可直接拨打）
    await expect(page.getByRole('link', { name: '13800000001' })).toHaveAttribute('href', 'tel:13800000001')

    // 门头照：未上传时展示虚线占位
    await expect(page.getByText('商家暂未上传门头照')).toBeVisible()
  })

  test('返回按钮可回到券列表', async ({ page }) => {
    await uiLogin(page, ...ACC.youth1)
    await page.goto('/user/coupons')
    await page.locator('.coupon-card a.merchant-link').first().click()
    await expect(page).toHaveURL(/\/user\/merchants\//)
    await page.getByRole('button', { name: '← 返回' }).click()
    await expect(page).toHaveURL(/\/user\/coupons/)
  })

  test('不存在的商家 id 显示友好空态', async ({ page }) => {
    await uiLogin(page, ...ACC.youth1)
    await page.goto('/user/merchants/not-exist-id')
    await expect(page.getByRole('heading', { name: '商家不存在' })).toBeVisible()
  })
})
