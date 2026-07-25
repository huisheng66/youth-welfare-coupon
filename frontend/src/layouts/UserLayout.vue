<template>
  <div class="wrap">
    <header class="top">
      <div class="brand-block">
        <span class="mark">福</span>
        <div>
          <div class="brand">青年福利券</div>
          <div class="who">{{ auth.account?.display_name || auth.account?.username }}</div>
        </div>
      </div>
      <nav>
        <router-link to="/user">首页</router-link>
        <router-link to="/user/profile">资料核验</router-link>
        <router-link to="/user/coupons">我的券</router-link>
        <router-link to="/user/points">时长兑换</router-link>
        <el-button link class="logout" @click="onLogout">退出</el-button>
      </nav>
    </header>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { logout, useAuth } from '../auth'

const auth = useAuth()
const router = useRouter()
function onLogout() {
  logout()
  router.push('/login')
}
</script>

<style scoped>
.wrap { min-height: 100vh; background: var(--bg); }
.top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 20;
}
.brand-block { display: flex; align-items: center; gap: 10px; }
.mark {
  width: 36px; height: 36px; border-radius: 10px;
  display: grid; place-items: center;
  background: var(--brand); color: #fff; font-weight: 700;
}
.brand { font-weight: 700; font-size: 1rem; color: var(--ink); }
.who { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
nav { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
nav a {
  color: var(--muted);
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
}
nav a:hover { background: var(--surface-2); color: var(--ink); }
nav a.router-link-active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 650;
}
.logout { color: var(--danger) !important; }
.main { max-width: 920px; margin: 20px auto; padding: 0 16px 32px; }
</style>
