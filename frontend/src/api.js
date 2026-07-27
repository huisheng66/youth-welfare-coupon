import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from './router'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : err.message || '请求失败'
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
