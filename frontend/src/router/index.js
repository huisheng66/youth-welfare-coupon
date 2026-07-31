import { createRouter, createWebHistory } from 'vue-router'
import { useAuth, homePathByRole } from '../auth'
import Login from '../views/Login.vue'

// 路由懒加载：按角色拆 chunk，首屏仅加载登录页
const AdminLayout = () => import('../layouts/AdminLayout.vue')
const UserLayout = () => import('../layouts/UserLayout.vue')
const MerchantLayout = () => import('../layouts/MerchantLayout.vue')
const Dashboard = () => import('../views/admin/Dashboard.vue')
const Users = () => import('../views/admin/Users.vue')
const Merchants = () => import('../views/admin/Merchants.vue')
const Templates = () => import('../views/admin/Templates.vue')
const Coupons = () => import('../views/admin/Coupons.vue')
const Redemptions = () => import('../views/admin/Redemptions.vue')
const AuditLogs = () => import('../views/admin/AuditLogs.vue')
const Accounts = () => import('../views/admin/Accounts.vue')
const AdminPoints = () => import('../views/admin/Points.vue')
const UserHome = () => import('../views/user/Home.vue')
const UserProfile = () => import('../views/user/Profile.vue')
const UserCoupons = () => import('../views/user/Coupons.vue')
const UserPoints = () => import('../views/user/Points.vue')
const MerchantRedeem = () => import('../views/merchant/Redeem.vue')
const MerchantLogs = () => import('../views/merchant/Logs.vue')
const Settings = () => import('../views/Settings.vue')
const NotFound = () => import('../views/NotFound.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', component: Login, meta: { public: true, title: '登录' } },
    {
      path: '/admin',
      component: AdminLayout,
      meta: { roles: ['super_admin', 'issue_admin'] },
      children: [
        { path: '', component: Dashboard, meta: { title: '仪表盘' } },
        { path: 'users', component: Users, meta: { title: '用户核验' } },
        { path: 'merchants', component: Merchants, meta: { title: '商家管理' } },
        { path: 'templates', component: Templates, meta: { title: '券模板' } },
        { path: 'coupons', component: Coupons, meta: { title: '券列表' } },
        { path: 'redemptions', component: Redemptions, meta: { title: '核销流水' } },
        { path: 'points', component: AdminPoints, meta: { title: '志愿时长' } },
        { path: 'audit', component: AuditLogs, meta: { title: '审计日志' } },
        { path: 'accounts', component: Accounts, meta: { title: '账号管理' } },
        { path: 'settings', component: Settings, meta: { title: '账号设置' } },
      ],
    },
    {
      path: '/user',
      component: UserLayout,
      meta: { roles: ['user'] },
      children: [
        { path: '', component: UserHome, meta: { title: '首页' } },
        { path: 'profile', component: UserProfile, meta: { title: '资料核验' } },
        { path: 'coupons', component: UserCoupons, meta: { title: '我的优惠券' } },
        { path: 'points', component: UserPoints, meta: { title: '时长兑换' } },
        { path: 'settings', component: Settings, meta: { title: '账号设置' } },
      ],
    },
    {
      path: '/merchant',
      component: MerchantLayout,
      meta: { roles: ['merchant'] },
      children: [
        { path: '', component: MerchantRedeem, meta: { title: '核销' } },
        { path: 'logs', component: MerchantLogs, meta: { title: '核销记录' } },
        { path: 'settings', component: Settings, meta: { title: '账号设置' } },
      ],
    },
    { path: '/:pathMatch(.*)*', component: NotFound, meta: { public: true, title: '页面不存在' } },
  ],
})

router.beforeEach((to) => {
  const auth = useAuth()
  if (to.meta.public) {
    if (auth.token && auth.account && to.path === '/login') {
      return homePathByRole(auth.account.role)
    }
    return true
  }
  if (!auth.token || !auth.account) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  const roles = to.matched.find((r) => r.meta.roles)?.meta.roles
  if (roles && !roles.includes(auth.account.role)) {
    return homePathByRole(auth.account.role)
  }
  return true
})

router.afterEach((to) => {
  const page = [...to.matched].reverse().find((r) => r.meta?.title)?.meta?.title
  document.title = page ? `${page} · youth` : 'youth'
})

export default router
