<template>
  <div class="wrap">
    <header class="top" data-od-id="merchant-topbar">
      <div class="brand-block">
        <div>
          <div class="brand">youth</div>
          <div class="who">商家核销 · {{ auth.account?.display_name }}</div>
        </div>
      </div>
      <el-button
        class="mobile-logout"
        text
        circle
        :icon="SwitchButton"
        aria-label="退出登录"
        @click="onLogout"
      />
      <nav aria-label="商家导航">
        <router-link to="/merchant"><el-icon><Camera /></el-icon><span>核销</span></router-link>
        <router-link to="/merchant/logs"><el-icon><List /></el-icon><span>记录</span></router-link>
        <router-link to="/merchant/settings"><el-icon><Setting /></el-icon><span>设置</span></router-link>
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
import { Camera, List, Setting, SwitchButton } from '@element-plus/icons-vue'
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
  display: inline-flex;
  align-items: center;
  gap: 5px;
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

.mobile-logout {
  display: none;
}

.main {
  max-width: 820px;
  margin: 20px auto;
  padding: 0 16px 32px;
}

@media (max-width: 640px) {
  .top {
    min-height: 56px;
    padding: max(6px, env(safe-area-inset-top)) 12px 6px;
    flex-wrap: nowrap;
  }

  .mobile-logout {
    display: inline-flex;
    width: 44px;
    height: 44px;
    color: #f0a8a8;
  }

  nav {
    position: fixed;
    z-index: var(--z-sticky);
    left: 0;
    right: 0;
    bottom: 0;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0;
    min-height: 58px;
    padding: 4px max(4px, env(safe-area-inset-right)) max(4px, env(safe-area-inset-bottom)) max(4px, env(safe-area-inset-left));
    background: #122a30;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
  }

  nav a {
    min-height: 50px;
    padding: 5px 4px;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    font-size: 0.8125rem;
    line-height: 1.15;
    text-align: center;
  }

  nav a .el-icon {
    font-size: 1.125rem;
  }

  nav .logout {
    display: none;
  }

  .main {
    width: 100%;
    margin: 10px auto 0;
    padding: 0 8px calc(74px + env(safe-area-inset-bottom));
  }
}
</style>
