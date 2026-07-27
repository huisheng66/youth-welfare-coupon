<template>
  <el-container class="shell">
    <el-aside :width="collapsed ? '72px' : '228px'" class="aside">
      <div class="brand">
        <span class="brand-mark">福</span>
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-title">青年福利券</div>
          <div class="brand-sub">运营管理端</div>
        </div>
      </div>
      <el-menu
        :default-active="route.path"
        router
        :collapse="collapsed"
        background-color="transparent"
        text-color="#c5d0d8"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/admin">仪表盘</el-menu-item>
        <el-menu-item index="/admin/users">
          <span>用户核验</span>
          <el-badge v-if="pendingCount > 0 && !collapsed" :value="pendingCount" class="badge" />
        </el-menu-item>
        <el-menu-item v-if="isSuper" index="/admin/merchants">商家管理</el-menu-item>
        <el-menu-item index="/admin/templates">券模板</el-menu-item>
        <el-menu-item index="/admin/coupons">券列表</el-menu-item>
        <el-menu-item index="/admin/redemptions">核销流水</el-menu-item>
        <el-menu-item index="/admin/points">志愿时长</el-menu-item>
        <el-menu-item v-if="isSuper" index="/admin/accounts">账号管理</el-menu-item>
        <el-menu-item v-if="isSuper" index="/admin/audit">审计日志</el-menu-item>
        <el-menu-item index="/admin/settings">账号设置</el-menu-item>
      </el-menu>
      <button class="collapse-btn" type="button" @click="collapsed = !collapsed">
        {{ collapsed ? '展开' : '收起' }}
      </button>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div>
          <div class="header-title">{{ pageTitle }}</div>
          <div class="header-sub muted">{{ roleLabel }} · {{ auth.account?.display_name }}</div>
        </div>
        <div class="header-actions">
          <el-button v-if="pendingCount > 0" type="warning" plain size="small" @click="$router.push('/admin/users')">
            {{ pendingCount }} 条待审
          </el-button>
          <el-button link type="primary" @click="onLogout">退出登录</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout, useAuth } from '../auth'
import api from '../api'
import { roleLabel as mapRole } from '../utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const collapsed = ref(false)
const isSuper = computed(() => auth.account?.role === 'super_admin')
const roleLabel = computed(() => mapRole(auth.account?.role))
const pendingCount = ref(0)

const titles = {
  '/admin': '仪表盘',
  '/admin/users': '用户核验',
  '/admin/merchants': '商家管理',
  '/admin/templates': '券模板',
  '/admin/coupons': '券列表',
  '/admin/redemptions': '核销流水',
  '/admin/points': '志愿服务时长',
  '/admin/accounts': '账号管理',
  '/admin/audit': '审计日志',
  '/admin/settings': '账号设置',
}
const pageTitle = computed(() => titles[route.path] || '管理端')

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
watch(() => route.path, loadPending)
</script>

<style scoped>
.shell { min-height: 100vh; background: var(--bg); }
.aside {
  background: linear-gradient(180deg, #16333a 0%, #0f2429 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255,255,255,0.06);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  min-height: 72px;
}
.brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: var(--brand);
  font-weight: 700;
  flex-shrink: 0;
}
.brand-title { font-weight: 700; font-size: 0.95rem; }
.brand-sub { font-size: 0.75rem; color: #9fb0b8; margin-top: 2px; }
.el-menu { border-right: none; flex: 1; }
.collapse-btn {
  margin: 8px;
  border: 1px solid rgba(255,255,255,0.12);
  background: transparent;
  color: #c5d0d8;
  border-radius: 8px;
  padding: 8px;
  cursor: pointer;
  font-size: 0.8125rem;
}
.collapse-btn:hover { background: rgba(255,255,255,0.06); color: #fff; }
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  height: auto !important;
  min-height: 64px;
  padding: 12px 20px;
}
.header-title { font-weight: 650; font-size: 1.05rem; }
.header-sub { font-size: 0.8125rem; margin-top: 2px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.main { padding: 16px 20px 28px; }
.badge { margin-left: 8px; }
@media (max-width: 900px) {
  .aside { width: 72px !important; }
  .brand-text, .collapse-btn { display: none; }
}
</style>
