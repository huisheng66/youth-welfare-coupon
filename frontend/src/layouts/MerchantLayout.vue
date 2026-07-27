<template>
  <div class="wrap">
    <header class="top">
      <div class="brand-block">
        <span class="mark">店</span>
        <div>
          <div class="brand">商家核销台</div>
          <div class="who">{{ auth.account?.display_name }}</div>
        </div>
      </div>
      <nav>
        <router-link to="/merchant">核销</router-link>
        <router-link to="/merchant/logs">核销记录</router-link>
        <router-link to="/merchant/settings">设置</router-link>
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
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: saturate(180%) blur(18px);
  -webkit-backdrop-filter: saturate(180%) blur(18px);
  border-bottom: 1px solid var(--border);
  color: var(--ink);
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
.brand { font-weight: 700; font-size: 1rem; color: var(--ink); letter-spacing: -0.01em; }
.who { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
nav { display: flex; gap: 4px; align-items: center; }
nav a {
  color: var(--muted);
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 0.875rem;
  font-weight: 500;
  transition: background 120ms ease, color 120ms ease;
}
nav a:hover { background: var(--surface-2); color: var(--ink); }
nav a.router-link-active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 700;
}
.logout { color: var(--danger) !important; border-radius: 999px !important; }
.main { max-width: 820px; margin: 20px auto; padding: 0 16px 32px; }
</style>
