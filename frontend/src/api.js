import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from './router'

/** 登录 / 改密 / 重置密码等含 bcrypt 的接口，网络抖动时给更长窗口 */
export const AUTH_SLOW_TIMEOUT = 30000

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
  // 携带 HttpOnly Cookie（认证 token 不再走 localStorage / Authorization 头）
  withCredentials: true,
})

api.interceptors.request.use((config) => {
  // CSRF 防护：后端要求写接口带 X-Requested-With，axios 全局注入
  config.headers['X-Requested-With'] = 'XMLHttpRequest'
  return config
})

const FIELD_LABELS = {
  username: '用户名',
  password: '密码',
  old_password: '原密码',
  new_password: '新密码',
  email: '邮箱',
  display_name: '昵称',
  merchant_id: '商家',
  code: '验证码',
  phone: '手机号',
}

function formatValidationDetail(detail) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (!Array.isArray(detail) || !detail.length) return ''
  const parts = detail.map((item) => {
    const loc = Array.isArray(item?.loc) ? item.loc : []
    const field = loc.filter((x) => x !== 'body' && x !== 'query' && x !== 'path').join('.')
    const label = FIELD_LABELS[field] || field || '参数'
    let msg = item?.msg || '校验失败'
    // Pydantic 英文默认文案 → 中文
    if (/at least 8 characters/i.test(msg)) msg = '至少 8 位'
    else if (/at least 3 characters/i.test(msg)) msg = '至少 3 个字符'
    else if (/at least \d+ characters/i.test(msg)) {
      const n = msg.match(/at least (\d+)/i)?.[1]
      msg = n ? `至少 ${n} 个字符` : msg
    } else if (/value is not a valid email/i.test(msg)) msg = '邮箱格式不正确'
    else if (/field required/i.test(msg)) msg = '不能为空'
    // 自定义 ValueError 已是中文
    if (typeof item?.ctx?.error === 'string' && item.ctx.error.trim()) {
      msg = item.ctx.error
    }
    // pydantic v2: msg often "Value error, 用户名至少 3 个字符"
    const ve = /^Value error,?\s*(.+)$/i.exec(msg)
    if (ve) msg = ve[1]
    return field ? `${label}：${msg}` : msg
  })
  return parts.filter(Boolean).join('；') || '提交内容不符合要求'
}

function friendlyErrorMessage(err) {
  const detail = err.response?.data?.detail
  const validationMsg = formatValidationDetail(detail)
  if (validationMsg) return validationMsg
  if (typeof detail === 'string' && detail.trim()) return detail
  const code = err.code || ''
  const raw = err.message || ''
  if (err.response?.status === 422) {
    return '提交内容不符合要求，请检查用户名（≥3）和密码（≥8）'
  }
  if (code === 'ECONNABORTED' || /timeout/i.test(raw)) {
    return '请求超时：请勿重复提交。若刚修改密码，可能已成功，请稍后用新密码登录确认'
  }
  if (code === 'ERR_NETWORK' || /network error/i.test(raw)) {
    return '网络异常，请检查连接后重试'
  }
  return raw || '请求失败'
}

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = friendlyErrorMessage(err)
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('account')
      if (router.currentRoute.value.path !== '/login') {
        router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
      }
    }
    // 轮询等场景可传 { silent: true } 避免打断用户
    if (!err.config?.silent) {
      ElMessage.error(msg)
    }
    return Promise.reject(err)
  },
)

export async function downloadFile(path, fallbackName = 'export.csv') {
  const res = await api.get(path, { responseType: 'blob' })
  const dispo = res.headers['content-disposition'] || ''
  const match = /filename="?([^"]+)"?/i.exec(dispo)
  const name = match?.[1] || fallbackName
  if (res.headers['x-export-truncated'] === '1') {
    ElMessage.warning('导出已截断为最多 5000 条，请缩小筛选范围')
  }
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/** 将日期区间转为 API 的 date_from / date_to (YYYY-MM-DD) */
export function dateRangeParams(range) {
  if (!range || range.length !== 2) return {}
  const fmt = (d) => {
    if (!d) return undefined
    if (typeof d === 'string' && /^\d{4}-\d{2}-\d{2}/.test(d)) return d.slice(0, 10)
    const x = d instanceof Date ? d : new Date(d)
    if (Number.isNaN(x.getTime())) return undefined
    const y = x.getFullYear()
    const m = String(x.getMonth() + 1).padStart(2, '0')
    const day = String(x.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  return { date_from: fmt(range[0]), date_to: fmt(range[1]) }
}

export default api
