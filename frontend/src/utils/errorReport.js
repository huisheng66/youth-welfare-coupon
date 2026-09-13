// 全局错误上报：未捕获异常 / Promise 拒绝不再静默丢失。
// 只上报到后端审计（POST /api/client-errors，免登录、204），并输出完整堆栈到控制台；
// 不弹提示框，避免干扰核销等关键流程的既有错误处理。
import api from '../api'
import router from '../router'

// 同一会话相同错误只上报一次；总量封顶，防止错误风暴刷爆审计日志
const seen = new Set()
let sent = 0
const MAX_PER_SESSION = 10

export function reportError(err, context = {}) {
  const message = err?.message || String(err ?? '未知错误')
  const stack = typeof err?.stack === 'string' ? err.stack : ''
  const kind = context.type || 'error'
  const info = context.info || ''
  const key = `${kind}|${info}|${message}`

  // 控制台始终完整输出，便于用户直接反馈
  console.error('[未捕获错误]', err, context)

  try {
    if (sent >= MAX_PER_SESSION || seen.has(key)) return
    seen.add(key)
    sent += 1
    api.post('/client-errors', {
      kind,
      message: message.slice(0, 500),
      stack: stack.slice(0, 4000),
      route: String(router.currentRoute?.value?.fullPath || '').slice(0, 200),
    })
  } catch {
    // 上报链路自身的异常一律吞掉，绝不能因上报再抛错
  }
}
