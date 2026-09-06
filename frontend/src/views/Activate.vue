<template>
  <div class="activate-page">
    <div class="panel page-card">
      <div class="hero">
        <div>
          <h1>youth</h1>
          <p class="page-desc" style="margin:0">设置账号密码以完成激活</p>
        </div>
      </div>

      <!-- 完成 / 失败终态 -->
      <template v-if="done">
        <el-result icon="success" title="账号已激活" sub-title="请使用新设置的密码登录">
          <template #extra>
            <el-button type="primary" @click="goLogin">前往登录</el-button>
          </template>
        </el-result>
      </template>

      <template v-else-if="tokenInvalid">
        <el-result
          icon="error"
          title="链接无效"
          sub-title="激活链接不存在、已被使用或已过期（48 小时有效）。请联系管理员重新发送激活邮件。"
        >
          <template #extra>
            <el-button @click="goLogin">前往登录</el-button>
          </template>
        </el-result>
      </template>

      <!-- 设置密码表单 -->
      <el-form v-else label-position="top" @submit.prevent="onActivate">
        <el-form-item label="新密码" required>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="new-password"
            size="large"
            placeholder="至少 8 位，需同时包含字母和数字"
          />
        </el-form-item>
        <el-form-item label="确认新密码" required>
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            autocomplete="new-password"
            size="large"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width:100%"
          :loading="loading"
          native-type="submit"
        >
          激活账号
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api, { AUTH_SLOW_TIMEOUT } from '../api'

const route = useRoute()
const router = useRouter()
const token = ref('')
const loading = ref(false)
const done = ref(false)
const tokenInvalid = ref(false)
const form = reactive({ password: '', confirm: '' })

onMounted(() => {
  const t = route.query.token
  if (typeof t !== 'string' || !t.trim()) {
    tokenInvalid.value = true
  } else {
    token.value = t.trim()
  }
})

function hasLetterAndDigit(s) {
  return /[a-zA-Z]/.test(s) && /\d/.test(s)
}

async function onActivate() {
  if (loading.value) return
  if (!form.password || form.password.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  if (!hasLetterAndDigit(form.password)) {
    ElMessage.warning('密码需同时包含字母和数字')
    return
  }
  if (form.password !== form.confirm) {
    ElMessage.warning('两次密码不一致')
    return
  }
  loading.value = true
  try {
    await api.post(
      '/auth/activate',
      { token: token.value, new_password: form.password },
      { timeout: AUTH_SLOW_TIMEOUT },
    )
    done.value = true
  } catch (err) {
    const detail = err?.response?.data?.detail || ''
    // token 已消费 / 过期 / 无效 → 直接进入失败终态，不再允许重试表单
    if (/已被使用|过期|无效/.test(String(detail))) {
      tokenInvalid.value = true
    }
  } finally {
    loading.value = false
  }
}

function goLogin() {
  router.push('/login')
}
</script>

<style scoped>
.activate-page {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: max(24px, env(safe-area-inset-top)) max(24px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom)) max(24px, env(safe-area-inset-left));
  background:
    radial-gradient(circle at 18% 12%, color-mix(in srgb, var(--brand) 16%, transparent), transparent 46%),
    var(--bg);
}
.panel {
  width: min(440px, 100%);
}
.hero {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
}
h1 {
  margin: 0 0 4px;
  font-size: var(--text-xl);
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.25;
  color: var(--brand);
  text-transform: lowercase;
  font-family: ui-rounded, "Segoe UI", system-ui, sans-serif;
}
</style>
