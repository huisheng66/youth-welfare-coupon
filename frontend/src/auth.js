import { reactive } from 'vue'
import api, { AUTH_SLOW_TIMEOUT } from './api'

const state = reactive({
  token: localStorage.getItem('token') || '',
  account: JSON.parse(localStorage.getItem('account') || 'null'),
})

export function useAuth() {
  return state
}

export async function login(username, password) {
  const { data } = await api.post(
    '/auth/login',
    { username, password },
    { timeout: AUTH_SLOW_TIMEOUT },
  )
  state.token = data.access_token
  localStorage.setItem('token', data.access_token)
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

export function logout() {
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
