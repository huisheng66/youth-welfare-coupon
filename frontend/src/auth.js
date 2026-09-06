import api, { AUTH_SLOW_TIMEOUT } from './api'
import { clearAuthState, setAuthState, state } from './authState'

export { clearAuthState }
export { state as _authState }

export function useAuth() {
  return state
}

export async function login(username, password) {
  // 后端 Set-Cookie 下发 HttpOnly token；随后用 /auth/me 拉取账号信息
  await api.post(
    '/auth/login',
    { username, password },
    { timeout: AUTH_SLOW_TIMEOUT },
  )
  const me = await api.get('/auth/me', { timeout: AUTH_SLOW_TIMEOUT })
  setAuthState(me.data)
  return me.data
}

export async function register(payload) {
  await api.post('/auth/register', payload, { timeout: AUTH_SLOW_TIMEOUT })
  // 注册后用邮箱登录
  return login(payload.email, payload.password)
}

// 页面启动时的会话恢复：有本地登录标记时先验证 Cookie 是否仍有效。
// 结果进程内只执行一次，路由守卫 await 它，避免“本地残留账号 + Cookie 已过期”
// 被放行业务路由后每个请求都 401 反复跳转。
let authReadyPromise = null

export function ensureAuthReady() {
  if (!authReadyPromise) {
    authReadyPromise = (async () => {
      if (!state.token || !state.account) return
      try {
        const me = await api.get('/auth/me', { timeout: 8000, silent: true })
        state.account = me.data
        localStorage.setItem('account', JSON.stringify(me.data))
      } catch (err) {
        if (err?.response?.status === 401) {
          clearAuthState()
        }
        // 网络故障等不本地登出：保留状态，交给后续请求的错误处理
      }
    })()
  }
  return authReadyPromise
}

export async function logout() {
  // 必须先清本地登录态再调后端：调用方紧接着 router.push('/login')，
  // 若等接口返回再清理，路由守卫会因 token 仍在而把 /login 弹回业务首页，
  // 表现为“点击退出后停留在原页面，再次点击/刷新才跳转”。
  clearAuthState()
  try {
    await api.post('/auth/logout')
  } catch {
    // 网络失败时本地状态已清理，HttpOnly Cookie 由后端过期策略兜底
  }
}

export function homePathByRole(role) {
  if (role === 'merchant') return '/merchant'
  if (role === 'user') return '/user'
  return '/admin'
}
