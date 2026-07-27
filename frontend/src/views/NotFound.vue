<template>
  <div class="wrap">
    <div class="page-card panel">
      <h1 class="page-title">页面不存在</h1>
      <p class="page-desc">链接可能已失效，或你没有访问该页面的权限。</p>
      <div class="quick-actions">
        <el-button type="primary" @click="goHome">返回首页</el-button>
        <el-button @click="$router.push('/login')">去登录</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { homePathByRole, useAuth } from '../auth'

const router = useRouter()
const auth = useAuth()

function goHome() {
  if (auth.token && auth.account) {
    router.push(homePathByRole(auth.account.role))
  } else {
    router.push('/login')
  }
}
</script>

<style scoped>
.wrap {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--bg);
}
.panel { width: min(420px, 100%); text-align: center; }
.quick-actions { justify-content: center; }
</style>
