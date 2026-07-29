import { createRouter, createWebHistory } from 'vue-router'
import { useAuth, homePathByRole } from '../auth'
import Login from '../views/Login.vue'
import AdminLayout from '../layouts/AdminLayout.vue'
import UserLayout from '../layouts/UserLayout.vue'
import MerchantLayout from '../layouts/MerchantLayout.vue'
import Dashboard from '../views/admin/Dashboard.vue'
import Users from '../views/admin/Users.vue'
import Merchants from '../views/admin/Merchants.vue'
import Templates from '../views/admin/Templates.vue'
import Coupons from '../views/admin/Coupons.vue'
import Redemptions from '../views/admin/Redemptions.vue'
import AuditLogs from '../views/admin/AuditLogs.vue'
import Accounts from '../views/admin/Accounts.vue'
import AdminPoints from '../views/admin/Points.vue'
import UserHome from '../views/user/Home.vue'
import UserProfile from '../views/user/Profile.vue'
import UserCoupons from '../views/user/Coupons.vue'
import UserPoints from '../views/user/Points.vue'
import MerchantRedeem from '../views/merchant/Redeem.vue'
import MerchantLogs from '../views/merchant/Logs.vue'
import Settings from '../views/Settings.vue'
import NotFound from '../views/NotFound.vue'

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
