import { reactive } from 'vue'

function readStoredAccount() {
  try {
    return JSON.parse(localStorage.getItem('account') || 'null')
  } catch {
    localStorage.removeItem('account')
    localStorage.removeItem('token')
    return null
  }
}

// JWT 由后端 HttpOnly Cookie 承载，前端不可读；localStorage 仅保留登录标记与账号信息。
// token 字段为 '1' 表示已登录（用于路由守卫），不再是真实 JWT。
const storedAccount = readStoredAccount()
export const state = reactive({
  token: storedAccount ? localStorage.getItem('token') || '' : '',
  account: storedAccount,
})

/** 同步清空 reactive 状态与本地缓存：401、退出登录、改密成功后共用。
 *
 * 只清 localStorage 不清 reactive 状态时，路由守卫仍认为已登录，
 * 会把用户重定向回受保护页面再触发 401，形成循环跳转。
 */
export function clearAuthState() {
  state.token = ''
  state.account = null
  localStorage.removeItem('token')
  localStorage.removeItem('account')
}

/** 登录成功后写入状态与本地缓存。 */
export function setAuthState(account) {
  state.token = '1'
  state.account = account
  localStorage.setItem('token', '1')
  localStorage.setItem('account', JSON.stringify(account))
}

// 多标签页同步：任一标签退出或会话失效（storage 被清）时，其余标签立即失去业务状态；
// storage 事件只携带变更键名，不传输 token。
window.addEventListener('storage', (e) => {
  if (e.key === 'token' || e.key === 'account') {
    if (!localStorage.getItem('token')) {
      state.token = ''
      state.account = null
    }
  }
})
