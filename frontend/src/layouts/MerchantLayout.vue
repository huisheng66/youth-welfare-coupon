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
  background: #16333a;
  color: #fff;
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
.brand { font-weight: 700; font-size: 1rem; }
.who { font-size: 0.75rem; color: #9fb0b8; margin-top: 2px; }
nav { display: flex; gap: 4px; align-items: center; }
nav a {
  color: #c5d0d8;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 0.875rem;
}
nav a:hover { background: rgba(255,255,255,0.08); color: #fff; }
nav a.router-link-active {
  background: rgba(15, 110, 106, 0.45);
  color: #fff;
  font-weight: 650;
}
.logout { color: #fca5a5 !important; }
.main { max-width: 820px; margin: 20px auto; padding: 0 16px 32px; }
</style>
