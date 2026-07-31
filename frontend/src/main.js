import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles.css'

// Element Plus 按需引入：组件由 unplugin-vue-components 自动注册，
// ElMessage/ElMessageBox 等 API 由 unplugin-auto-import 自动导入，
// 中文 locale 通过 App.vue 的 <el-config-provider> 注入。
createApp(App).use(router).mount('#app')
