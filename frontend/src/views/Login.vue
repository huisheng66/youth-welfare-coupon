<template>
  <div class="login-page">
    <div class="panel page-card">
      <div class="hero">
        <span class="mark">福</span>
        <div>
          <h1>青年福利券系统</h1>
          <p class="page-desc" style="margin:0">身份核验、指定商家发券、到店核销</p>
        </div>
      </div>

      <el-tabs v-model="tab">
        <el-tab-pane label="登录" name="login">
          <el-form label-position="top" @submit.prevent="onLogin">
            <el-form-item label="用户名">
              <el-input v-model="form.username" autocomplete="username" size="large" clearable />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password autocomplete="current-password" size="large" />
            </el-form-item>
            <el-button type="primary" size="large" style="width:100%" :loading="loading" native-type="submit">
              登录
            </el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="青年用户注册" name="register">
          <el-form label-position="top" @submit.prevent="onRegister">
            <el-form-item label="用户名">
              <el-input v-model="reg.username" size="large" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="reg.password" type="password" show-password size="large" />
            </el-form-item>
            <el-form-item label="昵称">
              <el-input v-model="reg.display_name" size="large" />
            </el-form-item>
            <el-form-item label="手机号">
              <el-input v-model="reg.phone" size="large" />
            </el-form-item>
            <el-button type="primary" size="large" style="width:100%" :loading="loading" native-type="submit">
              注册并登录
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <div class="demo">
        <div class="demo-title muted">演示账号（点击填入）</div>
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
const reg = reactive({ username: '', password: '', display_name: '', phone: '' })

const demos = [
  { label: '超管 admin', username: 'admin', password: 'admin123' },
  { label: '发券 issuer', username: 'issuer', password: 'issuer123' },
  { label: '商家 merchant1', username: 'merchant1', password: 'merchant123' },
  { label: '用户 youth1', username: 'youth1', password: 'youth123' },
]

function fillDemo(item) {
  tab.value = 'login'
  form.username = item.username
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
    ElMessage.warning('请输入用户名和密码')
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

async function onRegister() {
  if (!reg.username || !reg.password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  if (reg.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  loading.value = true
  try {
    const account = await register(reg)
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
