<template>
  <div class="wrap">
    <header class="top" data-od-id="merchant-topbar">
      <div class="brand-block">
        <span class="mark" aria-hidden="true">店</span>
        <div>
          <div class="brand">商家核销台</div>
          <div class="who">{{ auth.account?.display_name }}</div>
        </div>
      </div>
      <nav aria-label="商家导航">
        <router-link to="/merchant">核销</router-link>
        <router-link to="/merchant/logs">核销记录</router-link>
        <router-link to="/merchant/settings">设置</router-link>
        <el-button link class="logout" @click="onLogout">退出</el-button>
      </nav>
    </header>
    <main class="main" data-od-id="merchant-main">
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
  background: #122a30;
  color: #fff;
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mark {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--brand);
  color: #fff;
  font-weight: 700;
  font-size: 0.95rem;
}

.brand {
  font-weight: 650;
  font-size: 0.95rem;
  letter-spacing: -0.01em;
}

.who {
  font-size: 0.75rem;
  color: #9fb0b8;
  margin-top: 2px;
}

nav {
  display: flex;
  gap: 2px;
  align-items: center;
  flex-wrap: wrap;
}

nav a {
  color: #c5d0d8;
  padding: 7px 11px;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  transition: background 150ms ease, color 150ms ease;
}

nav a:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

nav a.router-link-active {
  background: color-mix(in srgb, var(--brand) 50%, #0a1c20);
  color: #fff;
  font-weight: 600;
}

nav a:focus-visible {
  box-shadow: var(--focus);
  outline: none;
}

.logout {
  color: #f0a8a8 !important;
  margin-left: 4px;
}

.main {
  max-width: 820px;
  margin: 20px auto;
  padding: 0 16px 32px;
}
</style>
