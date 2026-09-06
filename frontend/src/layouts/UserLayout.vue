<template>
  <div class="wrap">
    <header class="top" data-od-id="user-topbar">
      <div class="brand-block">
        <div>
          <div class="brand">youth</div>
          <div class="who">{{ auth.account?.display_name || auth.account?.username }}</div>
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
      <nav aria-label="用户导航">
        <!-- /user 是父路由，inclusive 匹配会让「首页」在子页常驻高亮，故仅精确匹配时才激活 -->
        <router-link to="/user" active-class="" exact-active-class="router-link-active">
          <el-icon><HomeFilled /></el-icon><span>首页</span>
        </router-link>
        <router-link to="/user/profile"><el-icon><User /></el-icon><span>资料</span></router-link>
        <router-link to="/user/coupons"><el-icon><Ticket /></el-icon><span>我的券</span></router-link>
        <router-link to="/user/points"><el-icon><Timer /></el-icon><span>时长兑换</span></router-link>
        <router-link to="/user/settings"><el-icon><Setting /></el-icon><span>设置</span></router-link>
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
import { HomeFilled, Setting, SwitchButton, Ticket, Timer, User } from '@element-plus/icons-vue'
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
  /* 浅色顶栏上用 --brand 保证对比度；亮青 --brand-bright 仅限深色 shell */
  color: var(--brand);
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
  display: inline-flex;
  align-items: center;
  gap: 5px;
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

.mobile-logout {
  display: none;
}

.main {
  max-width: 920px;
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
    color: var(--danger);
  }

  nav {
    position: fixed;
    z-index: var(--z-sticky);
    left: 0;
    right: 0;
    bottom: 0;
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0;
    min-height: 58px;
    padding: 4px max(4px, env(safe-area-inset-right)) max(4px, env(safe-area-inset-bottom)) max(4px, env(safe-area-inset-left));
    background: var(--surface);
    border-top: 1px solid var(--border);
  }

  nav a {
    min-width: 0;
    min-height: 50px;
    padding: 5px 2px;
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
