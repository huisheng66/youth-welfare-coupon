// E2E 共享工具：演示种子账号、UI 登录、管理端 API 准备动作。
// 测试数据全部来自 E2E 随机隔离库的种子（SEED_DEMO_ACCOUNTS=true）。

export const ACC = {
  admin: ['admin', 'admin123'], // super_admin
  issuer: ['issuer', 'issuer123'], // issue_admin
  merchant1: ['merchant1', 'merchant123'],
  youth1: ['youth1', 'youth123'], // 已核验，含演示券与 10.00 时长
  youth2: ['youth2', 'youth123'], // 待审核
}

/** UI 登录并等待角色首页。 */
export async function uiLogin(page, username, password) {
  await page.goto('/login')
  await page.getByPlaceholder('邮箱或用户名').fill(username)
  // 登录/注册/忘记密码三块表单同时挂在 DOM 里，密码框必须用可访问名限定
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15_000 })
}

/** 管理员通过页面已持有的 Cookie 调 API（page.request 与浏览器上下文共享会话）。
 * 写接口需要 X-Requested-With 以通过后端 CSRF 校验（前端 axios 全局注入同款）。 */
const CSRF = { 'X-Requested-With': 'XMLHttpRequest' }

async function adminGet(page, url, params) {
  const res = await page.request.get(url, { params, headers: CSRF })
  if (!res.ok()) throw new Error(`GET ${url} -> ${res.status()} ${await res.text()}`)
  return res.json()
}

/** 管理员给目标用户发券（发券走 API 准备数据，用户/商家侧仍走真实 UI）。
 * merchantName 指定券所属门店（必须与核销商家一致，默认取第一个模板）。 */
export async function adminIssueCoupon(page, username, { quantity = 1, merchantName } = {}) {
  const users = await adminGet(page, '/api/users', { q: username, limit: 50 })
  const user = users.items.find((i) => i.username === username)
  if (!user) throw new Error(`seeded user not found: ${username}`)
  const templates = await adminGet(page, '/api/coupons/templates', { active_only: 'true' })
  let template = templates.items[0]
  if (merchantName) {
    const merchants = await adminGet(page, '/api/merchants')
    const store = merchants.items.find((m) => m.name === merchantName)
    if (!store) throw new Error(`merchant not found: ${merchantName}`)
    template = templates.items.find((t) => t.merchant_id === store.id)
    if (!template) throw new Error(`no active template for store: ${merchantName}`)
  }
  if (!template) throw new Error('no active coupon template seeded')
  const res = await page.request.post('/api/coupons/issue', {
    data: { user_id: user.id, template_id: template.id, quantity },
    headers: CSRF,
  })
  if (!res.ok()) throw new Error(`issue coupon -> ${res.status()} ${await res.text()}`)
  return res.json()
}

/** 管理员作废指定券。 */
export async function adminVoidCoupon(page, couponId, reason = 'E2E 作废') {
  const res = await page.request.post(`/api/coupons/instances/${couponId}/void`, {
    data: { reason },
    headers: CSRF,
  })
  if (!res.ok()) throw new Error(`void coupon -> ${res.status()} ${await res.text()}`)
  return res.json()
}

/** 查询目标用户的未使用券列表。 */
export async function listMyCoupons(page, status) {
  const res = await page.request.get('/api/coupons/my', {
    params: status ? { status, limit: 500 } : { limit: 500 },
  })
  if (!res.ok()) throw new Error(`coupons/my -> ${res.status()} ${await res.text()}`)
  // T18：/coupons/my 升级为 Page 结构 { total, items }
  const body = await res.json()
  return body.items ?? body
}
