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

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', component: Login, meta: { public: true } },
    {
      path: '/admin',
      component: AdminLayout,
      meta: { roles: ['super_admin', 'issue_admin'] },
      children: [
        { path: '', component: Dashboard },
        { path: 'users', component: Users },
        { path: 'merchants', component: Merchants },
        { path: 'templates', component: Templates },
        { path: 'coupons', component: Coupons },
        { path: 'redemptions', component: Redemptions },
        { path: 'points', component: AdminPoints },
        { path: 'audit', component: AuditLogs },
        { path: 'accounts', component: Accounts },
        { path: 'settings', component: Settings },
      ],
    },
    {
      path: '/user',
      component: UserLayout,
      meta: { roles: ['user'] },
      children: [
        { path: '', component: UserHome },
        { path: 'profile', component: UserProfile },
        { path: 'coupons', component: UserCoupons },
        { path: 'points', component: UserPoints },
        { path: 'settings', component: Settings },
      ],
    },
    {
      path: '/merchant',
      component: MerchantLayout,
      meta: { roles: ['merchant'] },
      children: [
        { path: '', component: MerchantRedeem },
        { path: 'logs', component: MerchantLogs },
        { path: 'settings', component: Settings },
      ],
    },
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

export default router
