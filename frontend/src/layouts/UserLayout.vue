<template>
  <div class="wrap">
    <header class="top" data-od-id="user-topbar">
      <div class="brand-block">
        <div>
          <div class="brand">youth</div>
          <div class="who">{{ auth.account?.display_name || auth.account?.username }}</div>
        </div>
      </div>
      <nav aria-label="用户导航">
        <router-link to="/user">首页</router-link>
        <router-link to="/user/profile">资料核验</router-link>
        <router-link to="/user/coupons">我的券</router-link>
        <router-link to="/user/points">时长兑换</router-link>
        <router-link to="/user/settings">设置</router-link>
        <el-button link class="logout" @click="onLogout">退出</el-button>
      </nav>
    </header>
    <main class="main" data-od-id="user-main">
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
.wrap {
  min-height: 100vh;
  background: var(--bg);
}

.top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand {
  font-weight: 700;
  font-size: 1.125rem;
  color: #2bb5a0;
  letter-spacing: 0.04em;
  text-transform: lowercase;
  font-family: ui-rounded, "Segoe UI", system-ui, sans-serif;
}

.who {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 2px;
}

nav {
  display: flex;
  gap: 2px;
  align-items: center;
  flex-wrap: wrap;
}

nav a {
  color: var(--muted);
  padding: 7px 11px;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  transition: background 150ms ease, color 150ms ease;
}

nav a:hover {
  background: var(--surface-2);
  color: var(--ink);
}

nav a.router-link-active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 600;
}

nav a:focus-visible {
  box-shadow: var(--focus);
  outline: none;
}

.logout {
  color: var(--danger) !important;
  margin-left: 4px;
}

.main {
  max-width: 920px;
  margin: 20px auto;
  padding: 0 16px 32px;
}

@media (max-width: 640px) {
  .top {
    padding: 10px 12px;
  }

  nav a {
    padding: 6px 8px;
    font-size: 0.8125rem;
  }
}
</style>
