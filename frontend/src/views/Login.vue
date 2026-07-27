<template>
  <div class="login-page">
    <div class="panel page-card">
      <div class="hero">
        <span class="mark">福</span>
        <div>
          <h1>青年福利券系统</h1>
          <p class="page-desc" style="margin:0">支持邮箱注册 / 登录，也可使用用户名</p>
        </div>
      </div>

      <el-tabs v-model="tab">
        <el-tab-pane label="登录" name="login">
          <el-form label-position="top" @submit.prevent="onLogin">
            <el-form-item label="邮箱 / 用户名">
              <el-input
                v-model="form.username"
                autocomplete="username"
                size="large"
                clearable
                placeholder="邮箱或用户名"
              />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="form.password"
                type="password"
                show-password
                autocomplete="current-password"
                size="large"
              />
            </el-form-item>
            <el-button type="primary" size="large" style="width:100%" :loading="loading" native-type="submit">
              登录
            </el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="邮箱注册" name="register">
          <el-form label-position="top" @submit.prevent="onRegister">
            <el-form-item label="邮箱" required>
              <el-input v-model="reg.email" type="email" autocomplete="email" size="large" placeholder="用于登录" />
            </el-form-item>
            <el-form-item label="密码" required>
              <el-input v-model="reg.password" type="password" show-password size="large" placeholder="至少 6 位" />
            </el-form-item>
            <el-form-item label="确认密码" required>
              <el-input v-model="reg.confirm" type="password" show-password size="large" />
            </el-form-item>
            <el-form-item label="昵称">
              <el-input v-model="reg.display_name" size="large" placeholder="选填" />
            </el-form-item>
            <el-form-item label="手机号">
              <el-input v-model="reg.phone" size="large" placeholder="选填" />
            </el-form-item>
            <el-button type="primary" size="large" style="width:100%" :loading="loading" native-type="submit">
              注册并登录
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <div class="demo">
        <div class="demo-title muted">演示账号（点击填入，可用用户名或邮箱登录）</div>
        <div class="demo-list">
          <button
            v-for="item in demos"
            :key="item.username"
            type="button"
            class="role-chip"
            @click="fillDemo(item)"
          >
            {{ item.label }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { homePathByRole, login, register } from '../auth'

const router = useRouter()
const route = useRoute()
const tab = ref('login')
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const reg = reactive({ email: '', password: '', confirm: '', display_name: '', phone: '' })

const demos = [
  { label: '超管', username: 'admin', email: 'admin@demo.local', password: 'admin123' },
  { label: '发券', username: 'issuer', email: 'issuer@demo.local', password: 'issuer123' },
  { label: '商家', username: 'merchant1', email: 'merchant1@demo.local', password: 'merchant123' },
  { label: '用户', username: 'youth1', email: 'youth1@demo.local', password: 'youth123' },
]

function fillDemo(item) {
  tab.value = 'login'
  form.username = item.email || item.username
  form.password = item.password
}

async function goAfter(account) {
  const redirect = route.query.redirect
  if (typeof redirect === 'string' && redirect.startsWith('/')) {
    router.push(redirect)
  } else {
    router.push(homePathByRole(account.role))
  }
}

async function onLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入邮箱/用户名和密码')
    return
  }
  loading.value = true
  try {
    const account = await login(form.username, form.password)
    ElMessage.success('登录成功')
    await goAfter(account)
  } finally {
    loading.value = false
  }
}

function validEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

async function onRegister() {
  if (!reg.email.trim()) {
    ElMessage.warning('请填写邮箱')
    return
  }
  if (!validEmail(reg.email.trim())) {
    ElMessage.warning('邮箱格式不正确')
    return
  }
  if (!reg.password) {
    ElMessage.warning('请填写密码')
    return
  }
  if (reg.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  if (reg.password !== reg.confirm) {
    ElMessage.warning('两次密码不一致')
    return
  }
  loading.value = true
  try {
    const account = await register({
      email: reg.email.trim(),
      password: reg.password,
      display_name: reg.display_name,
      phone: reg.phone || null,
    })
    ElMessage.success('注册成功')
    await goAfter(account)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at 12% 18%, rgba(15, 110, 106, 0.14), transparent 42%),
    radial-gradient(circle at 88% 80%, rgba(29, 79, 145, 0.1), transparent 40%),
    var(--bg);
}
.panel { width: min(440px, 100%); }
.hero {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}
.mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--brand);
  color: #fff;
  font-weight: 700;
  font-size: 1.1rem;
  flex-shrink: 0;
}
h1 {
  margin: 0 0 4px;
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.demo {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.demo-title {
  font-size: 0.8125rem;
  margin-bottom: 10px;
}
.demo-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
