import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { reportError } from './utils/errorReport'
import './styles.css'

// Element Plus 按需引入：组件由 unplugin-vue-components 自动注册，
// ElMessage/ElMessageBox 等 API 由 unplugin-auto-import 自动导入，
// 中文 locale 通过 App.vue 的 <el-config-provider> 注入。
const app = createApp(App)
app.use(router)

// 全局错误兜底：组件内未捕获异常 → errorHandler；
// 运行时 JS 异常（target 为元素的是资源加载错误，跳过）与未处理的 Promise
// 拒绝 → window 钩子。三者统一走 reportError（控制台 + 上报审计）。
app.config.errorHandler = (err, _instance, info) => {
  reportError(err, { type: 'vue', info })
}
window.addEventListener('error', (event) => {
  if (event.target && event.target !== window && event.target instanceof Element) return
  reportError(event.error || new Error(event.message || '未知脚本错误'), { type: 'error' })
})
window.addEventListener('unhandledrejection', (event) => {
  reportError(event.reason, { type: 'unhandledrejection' })
})

app.mount('#app')
