<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">账号设置</h2>
        <p class="page-desc">绑定邮箱（需验证码）、修改登录密码</p>
      </div>
    </div>

    <el-descriptions :column="1" border style="max-width:480px;margin-bottom:20px">
      <el-descriptions-item label="用户名">{{ auth.account?.username }}</el-descriptions-item>
      <el-descriptions-item label="邮箱">{{ auth.account?.email || '未绑定' }}</el-descriptions-item>
      <el-descriptions-item label="昵称">{{ auth.account?.display_name || '-' }}</el-descriptions-item>
      <el-descriptions-item label="角色">{{ roleLabel }}</el-descriptions-item>
    </el-descriptions>

    <h3 class="section-title">绑定 / 修改邮箱</h3>
    <el-form label-width="100px" style="max-width:480px;margin-bottom:28px" @submit.prevent="onEmail">
      <el-form-item label="邮箱">
        <el-input v-model="emailForm.email" type="email" placeholder="登录可用邮箱" />
      </el-form-item>
      <el-form-item label="验证码">
        <div class="code-row">
          <el-input v-model="emailForm.code" maxlength="8" placeholder="邮箱验证码" />
          <el-button :disabled="emailCooldown > 0 || codeSending" :loading="codeSending" @click="sendBindCode">
            {{ emailCooldown > 0 ? `${emailCooldown}s` : '获取验证码' }}
          </el-button>
        </div>
        <p v-if="emailDebugCode" class="debug-tip">开发模式验证码：<strong>{{ emailDebugCode }}</strong></p>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="emailLoading" native-type="submit">保存邮箱</el-button>
      </el-form-item>
    </el-form>

    <h3 class="section-title">修改密码</h3>
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="100px"
      style="max-width:480px"
      @submit.prevent="onSubmit"
    >
      <el-form-item label="原密码" prop="old_password">
        <el-input v-model="form.old_password" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-form-item label="新密码" prop="new_password">
        <el-input v-model="form.new_password" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirm">
        <el-input v-model="form.confirm" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" native-type="submit">保存新密码</el-button>
        <el-button @click="resetForm">清空</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import api, { AUTH_SLOW_TIMEOUT } from '../api'
import { useAuth } from '../auth'
import { roleLabel as mapRole } from '../utils/format'

const auth = useAuth()
const roleLabel = computed(() => mapRole(auth.account?.role))
const formRef = ref(null)
const loading = ref(false)
const emailLoading = ref(false)
const codeSending = ref(false)
const emailCooldown = ref(0)
const emailDebugCode = ref('')
let emailTimer = null

const form = reactive({
  old_password: '',
  new_password: '',
  confirm: '',
})
const emailForm = reactive({ email: '', code: '' })

const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '至少 8 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v !== form.new_password) cb(new Error('两次输入不一致'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
}

function resetForm() {
  form.old_password = ''
  form.new_password = ''
  form.confirm = ''
  formRef.value?.clearValidate?.()
}

function syncAccount(data) {
  if (!auth.account) return
  Object.assign(auth.account, data)
  localStorage.setItem('account', JSON.stringify(auth.account))
}

function validEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

async function sendBindCode() {
  const email = emailForm.email.trim()
  if (!email) {
    ElMessage.warning('请填写邮箱')
    return
  }
  if (!validEmail(email)) {
    ElMessage.warning('邮箱格式不正确')
    return
  }
  codeSending.value = true
  try {
    const { data } = await api.post('/auth/email/send-code', { email, purpose: 'bind_email' })
    emailDebugCode.value = data.debug_code || ''
    if (data.debug_code) {
      emailForm.code = data.debug_code
      ElMessage.success(`开发模式验证码：${data.debug_code}`)
    } else {
      ElMessage.success(data.message || '验证码已发送')
    }
    emailCooldown.value = 60
    clearInterval(emailTimer)
    emailTimer = setInterval(() => {
      emailCooldown.value -= 1
      if (emailCooldown.value <= 0) clearInterval(emailTimer)
    }, 1000)
  } finally {
    codeSending.value = false
  }
}

async function onEmail() {
  const email = emailForm.email.trim()
  if (!email) {
    ElMessage.warning('请填写邮箱')
    return
  }
  if (!validEmail(email)) {
    ElMessage.warning('邮箱格式不正确')
    return
  }
  if (!emailForm.code.trim()) {
    ElMessage.warning('请填写验证码')
    return
  }
  emailLoading.value = true
  try {
    const res = await api.put('/auth/me/email', { email, code: emailForm.code.trim() })
    syncAccount(res.data)
    emailForm.code = ''
    emailDebugCode.value = ''
    ElMessage.success('邮箱已更新')
  } finally {
    emailLoading.value = false
  }
}

async function onSubmit() {
  if (loading.value) return
  const valid = await formRef.value?.validate?.().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await api.post(
      '/auth/change-password',
      {
        old_password: form.old_password,
        new_password: form.new_password,
      },
      { timeout: AUTH_SLOW_TIMEOUT },
    )
    ElMessage.success('密码已修改，请使用新密码登录')
    resetForm()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  emailForm.email = auth.account?.email || ''
})

onUnmounted(() => {
  clearInterval(emailTimer)
})
</script>

<style scoped>
.section-title {
  margin: 0 0 12px;
  font-size: 1rem;
  font-weight: 600;
}
.code-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.code-row .el-input { flex: 1; }
.debug-tip {
  margin: 6px 0 0;
  font-size: 0.8125rem;
  color: var(--brand, #0f6e6a);
}
</style>
