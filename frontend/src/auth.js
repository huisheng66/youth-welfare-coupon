import { reactive } from 'vue'
import api, { AUTH_SLOW_TIMEOUT } from './api'

// JWT 现由后端 HttpOnly Cookie 承载，前端不可读；localStorage 仅保留登录标记与账号信息。
// token 字段为 '1' 表示已登录（用于路由守卫），不再是真实 JWT。
const state = reactive({
  token: localStorage.getItem('token') || '',
  account: JSON.parse(localStorage.getItem('account') || 'null'),
})

export function useAuth() {
  return state
}

export async function login(username, password) {
  // 后端 Set-Cookie 下发 HttpOnly token；响应体仍返回 access_token 仅供过渡兼容
  await api.post(
    '/auth/login',
    { username, password },
    { timeout: AUTH_SLOW_TIMEOUT },
  )
  state.token = '1'
  localStorage.setItem('token', '1')
  const me = await api.get('/auth/me', { timeout: AUTH_SLOW_TIMEOUT })
  state.account = me.data
  localStorage.setItem('account', JSON.stringify(me.data))
  return me.data
}

export async function register(payload) {
  await api.post('/auth/register', payload, { timeout: AUTH_SLOW_TIMEOUT })
  // 注册后用邮箱登录
  return login(payload.email, payload.password)
}

export async function logout() {
  try {
    await api.post('/auth/logout')
  } catch {
    // 即便网络失败也清理本地状态
  }
  state.token = ''
  state.account = null
  localStorage.removeItem('token')
  localStorage.removeItem('account')
}

export function homePathByRole(role) {
  if (role === 'merchant') return '/merchant'
  if (role === 'user') return '/user'
  return '/admin'
}
