<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">账号设置</h2>
        <p class="page-desc">绑定邮箱、修改登录密码</p>
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useAuth } from '../auth'
import { roleLabel as mapRole } from '../utils/format'

const auth = useAuth()
const roleLabel = computed(() => mapRole(auth.account?.role))
const formRef = ref(null)
const loading = ref(false)
const emailLoading = ref(false)
const form = reactive({
  old_password: '',
  new_password: '',
  confirm: '',
})
const emailForm = reactive({ email: '' })

const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '至少 6 位', trigger: 'blur' },
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

async function onEmail() {
  const email = emailForm.email.trim()
  if (!email) {
    ElMessage.warning('请填写邮箱')
    return
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    ElMessage.warning('邮箱格式不正确')
    return
  }
  emailLoading.value = true
  try {
    const res = await api.put('/auth/me/email', { email })
    syncAccount(res.data)
    ElMessage.success('邮箱已更新')
  } finally {
    emailLoading.value = false
  }
}

async function onSubmit() {
  const valid = await formRef.value?.validate?.().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await api.post('/auth/change-password', {
      old_password: form.old_password,
      new_password: form.new_password,
    })
    ElMessage.success('密码已修改，请使用新密码登录')
    resetForm()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  emailForm.email = auth.account?.email || ''
})
</script>

<style scoped>
.section-title {
  margin: 0 0 12px;
  font-size: 1rem;
  font-weight: 600;
}
</style>
