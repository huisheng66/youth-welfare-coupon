<template>
  <el-container class="shell">
    <el-aside :width="collapsed ? '72px' : '228px'" class="aside" data-od-id="admin-sidebar">
      <div class="brand">
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-title">youth</div>
          <div class="brand-sub">运营管理端</div>
        </div>
        <div v-else class="brand-title brand-title-collapsed" title="youth">y</div>
      </div>
      <el-menu
        :default-active="route.path"
        router
        :collapse="collapsed"
        background-color="transparent"
        text-color="var(--shell-ink)"
        active-text-color="#ffffff"
        class="nav-menu"
      >
        <el-menu-item v-for="item in visibleNavItems" :key="item.path" :index="item.path">
          <!-- 折叠时只露图标：待审用红点提示；展开时显示数量徽标；tooltip 展示完整标签+数量 -->
          <el-badge
            v-if="item.showPending && pendingCount > 0 && collapsed"
            is-dot
            class="icon-dot"
          >
            <el-icon><component :is="item.icon" /></el-icon>
          </el-badge>
          <el-icon v-else><component :is="item.icon" /></el-icon>
          <template #title>
            <span>{{ item.label }}</span>
            <el-badge
              v-if="item.showPending && pendingCount > 0"
              :value="pendingCount"
              class="badge"
            />
          </template>
        </el-menu-item>
      </el-menu>
      <button
        class="collapse-btn"
        type="button"
        :aria-expanded="!collapsed"
        :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? '展开' : '收起' }}
      </button>
    </el-aside>
    <el-container class="body">
      <el-header class="header" data-od-id="admin-topbar">
        <div class="header-left">
          <el-button
            class="mobile-menu-btn"
            text
            circle
            :icon="MenuIcon"
            aria-label="打开导航菜单"
            @click="mobileNavOpen = true"
          />
          <div>
            <div class="header-title">{{ pageTitle }}</div>
            <div class="header-sub muted">{{ roleLabel }} · {{ auth.account?.display_name }}</div>
          </div>
        </div>
        <div class="header-actions">
          <el-button
            v-if="pendingCount > 0"
            type="warning"
            plain
            size="small"
            @click="$router.push('/admin/users')"
          >
            {{ pendingCount }} 条待审
          </el-button>
          <el-button link type="primary" @click="onLogout">退出登录</el-button>
        </div>
      </el-header>
      <el-main class="main" data-od-id="admin-main">
        <router-view />
      </el-main>
    </el-container>

    <el-drawer
      v-model="mobileNavOpen"
      class="mobile-drawer"
      direction="ltr"
      size="min(86vw, 320px)"
      :with-header="false"
    >
      <div class="drawer-head">
        <div>
          <div class="brand-title">youth</div>
          <div class="drawer-sub">{{ roleLabel }} · {{ auth.account?.display_name }}</div>
        </div>
        <el-button
          text
          circle
          :icon="CloseIcon"
          aria-label="关闭导航菜单"
          @click="mobileNavOpen = false"
        />
      </div>
      <el-menu
        :default-active="route.path"
        router
        class="mobile-nav-menu"
        @select="mobileNavOpen = false"
      >
        <el-menu-item v-for="item in visibleNavItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <el-badge
            v-if="item.showPending && pendingCount > 0"
            :value="pendingCount"
            class="badge"
          />
        </el-menu-item>
      </el-menu>
      <el-button class="drawer-logout" plain type="danger" @click="onLogout">退出登录</el-button>
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Close as CloseIcon,
  Document,
  List,
  Menu as MenuIcon,
  Odometer,
  Setting,
  Shop,
  Ticket,
  Tickets,
  Timer,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import { logout, useAuth } from '../auth'
import api from '../api'
import { roleLabel as mapRole } from '../utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const collapsed = ref(false)
const mobileNavOpen = ref(false)
const isSuper = computed(() => auth.account?.role === 'super_admin')
const roleLabel = computed(() => mapRole(auth.account?.role))
const pendingCount = ref(0)

/** Single source of truth for sidebar + mobile drawer menus. */
const navItems = [
  { path: '/admin', label: '仪表盘', icon: Odometer },
  { path: '/admin/users', label: '用户核验', icon: User, showPending: true },
  { path: '/admin/merchants', label: '商家管理', icon: Shop },
  { path: '/admin/templates', label: '券模板', icon: Ticket },
  { path: '/admin/coupons', label: '券列表', icon: Tickets },
  { path: '/admin/redemptions', label: '核销流水', icon: List },
  { path: '/admin/points', label: '志愿时长', icon: Timer, title: '志愿服务时长' },
  { path: '/admin/accounts', label: '账号管理', icon: UserFilled, superOnly: true },
  { path: '/admin/audit', label: '审计日志', icon: Document, superOnly: true },
  { path: '/admin/settings', label: '账号设置', icon: Setting },
]
const visibleNavItems = computed(() =>
  navItems.filter((item) => !item.superOnly || isSuper.value),
)
const pageTitle = computed(() => {
  const item = navItems.find((entry) => entry.path === route.path)
  return item?.title || item?.label || '管理端'
})

async function loadPending() {
  try {
    const res = await api.get('/dashboard')
    pendingCount.value = res.data.pending_verifications || 0
  } catch {
    pendingCount.value = 0
  }
}

function onLogout() {
  logout()
  router.push('/login')
}

onMounted(loadPending)
watch(() => route.path, () => {
  mobileNavOpen.value = false
  loadPending()
})
</script>

<style scoped>
.shell {
  min-height: 100vh;
  background: var(--bg);
}

.aside {
  background: var(--shell-bg);
  color: #fff;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  transition: width 180ms ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  min-height: 68px;
}

.brand-title {
  font-weight: 700;
  font-size: 1.125rem;
  letter-spacing: 0.04em;
  color: var(--brand-bright);
  text-transform: lowercase;
  font-family: ui-rounded, "Segoe UI", system-ui, sans-serif;
}

.brand-title-collapsed {
  width: 100%;
  text-align: center;
  font-size: 1.25rem;
}

.brand-sub {
  font-size: 0.75rem;
  color: var(--shell-ink-muted);
  margin-top: 2px;
  letter-spacing: 0.02em;
}

.nav-menu {
  border-right: none;
  flex: 1;
  padding: 8px 0;
  overflow-y: auto;
}

.nav-menu :deep(.el-menu-item) {
  margin: 2px 8px;
  border-radius: 8px;
  height: 40px;
  line-height: 40px;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.nav-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06) !important;
}

.nav-menu :deep(.el-menu-item.is-active) {
  background: color-mix(in srgb, var(--brand) 55%, var(--shell-bg-deep)) !important;
  font-weight: 600;
}

/* 折叠态红点贴在图标右上角，避免被窄宽菜单裁切 */
.icon-dot :deep(.el-badge__content.is-dot) {
  right: 6px;
  top: 4px;
}

.collapse-btn {
  margin: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: transparent;
  color: var(--shell-ink);
  border-radius: 8px;
  padding: 8px;
  cursor: pointer;
  font-size: 0.8125rem;
  letter-spacing: 0.02em;
  transition: background 150ms ease, color 150ms ease;
}

.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.collapse-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus);
}

.body {
  min-width: 0;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  height: auto !important;
  min-height: 60px;
  padding: 10px 20px;
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.header-title {
  font-weight: 650;
  font-size: 1.05rem;
  letter-spacing: -0.01em;
  color: var(--ink);
}

.header-left {
  display: flex;
  align-items: center;
  min-width: 0;
}

.mobile-menu-btn {
  display: none;
  width: 44px;
  height: 44px;
  margin-left: -10px;
  margin-right: 2px;
  color: var(--ink);
}

.header-sub {
  font-size: 0.8125rem;
  margin-top: 2px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.main {
  padding: 16px 20px 32px;
}

.badge {
  margin-left: 8px;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 64px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}

.drawer-sub {
  margin-top: 2px;
  color: var(--muted);
  font-size: var(--text-xs);
}

.mobile-nav-menu {
  border-right: 0;
  padding: 8px;
}

.mobile-nav-menu :deep(.el-menu-item) {
  height: 44px;
  margin: 2px 0;
  border-radius: var(--radius-sm);
}

.drawer-logout {
  width: calc(100% - 24px);
  min-height: 44px;
  margin: 12px;
}

:global(.mobile-drawer .el-drawer__body) {
  display: flex;
  flex-direction: column;
  padding: 0 0 max(12px, env(safe-area-inset-bottom));
}

@media (max-width: 900px) {
  .aside {
    display: none;
  }

  .mobile-menu-btn {
    display: inline-flex;
  }

  .main {
    padding: 12px 12px 24px;
  }
}

@media (max-width: 520px) {
  .header {
    min-height: 56px;
    padding: max(6px, env(safe-area-inset-top)) 12px 6px;
  }

  .header-sub {
    max-width: 42vw;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header-actions .el-button--warning {
    display: none;
  }

  .main {
    padding: 10px 8px max(20px, env(safe-area-inset-bottom));
  }
}

@media (prefers-reduced-motion: reduce) {
  .aside {
    transition: none;
  }
}
</style>
