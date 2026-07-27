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
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export default api
