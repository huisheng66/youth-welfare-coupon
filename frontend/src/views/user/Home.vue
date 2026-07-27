<template>
  <div>
    <div class="page-card" style="margin-bottom:16px">
      <h2 class="page-title">你好，{{ auth.account?.display_name || auth.account?.username }}</h2>
      <p class="page-desc">完成身份核验后，可获发券或用志愿服务时长兑换指定商家优惠券。</p>

      <el-skeleton v-if="loading" animated :rows="4" />
      <template v-else>
        <div class="stat-grid">
          <div class="stat-item is-accent">
            <div class="label">未使用券</div>
            <div class="value">{{ unusedCount }}</div>
          </div>
          <div class="stat-item">
            <div class="label">已使用</div>
            <div class="value">{{ usedCount }}</div>
          </div>
          <div class="stat-item">
            <div class="label">可用时长</div>
            <div class="value">{{ balance ?? 0 }}<span class="unit">h</span></div>
          </div>
          <div class="stat-item">
            <div class="label">核验状态</div>
            <div class="status-val">
              <StatusTag :text="statusText" :type="statusType" />
            </div>
          </div>
        </div>

        <el-alert
          v-if="profile?.verify_status === 'draft' || profile?.verify_status === 'rejected'"
          class="section-gap"
          type="warning"
          :closable="false"
          :title="profile?.verify_status === 'rejected' ? '上次申请已驳回，请修改后重新提交' : '请先完善资料并提交核验'"
        />

        <div class="quick-actions">
          <el-button type="primary" @click="$router.push('/user/coupons')">我的优惠券</el-button>
          <el-button @click="$router.push('/user/points')">时长兑换</el-button>
          <el-button @click="$router.push('/user/profile')">资料 / 提交核验</el-button>
          <el-button @click="$router.push('/user/settings')">修改密码</el-button>
        </div>
      </template>
    </div>

    <el-alert
      v-if="!loading && expiringList.length"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom:16px"
      :title="`有 ${expiringList.length} 张券将在 7 天内过期，请尽快使用`"
    />

    <div v-if="!loading && unusedList.length" class="page-card">
      <div class="page-header">
        <div>
          <h2 class="page-title">待使用优惠券</h2>
          <p class="page-desc">到店前打开动态券码；商家扫码后本页会提示成功</p>
        </div>
        <el-button link type="primary" @click="$router.push('/user/coupons')">查看全部</el-button>
      </div>
      <div v-for="c in unusedList" :key="c.id" class="coupon-row">
        <div>
          <strong>{{ c.template_name }}</strong>
          <el-tag v-if="isExpiring(c)" size="small" type="warning" effect="light" style="margin-left:6px">即将过期</el-tag>
          <div class="muted">指定商家：{{ c.merchant_name }}</div>
          <div class="muted">过期 {{ formatTime(c.expires_at) }}</div>
        </div>
        <el-button type="primary" @click="$router.push({ path: '/user/coupons', query: { open: c.id } })">
          出示动态码
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../../api'
import { useAuth } from '../../auth'
import StatusTag from '../../components/StatusTag.vue'
import { formatTime, verifyStatusText, verifyStatusType } from '../../utils/format'

const auth = useAuth()
const profile = ref(null)
const balance = ref(null)
const coupons = ref([])
const loading = ref(true)
const statusText = computed(() => verifyStatusText(profile.value?.verify_status))
const statusType = computed(() => verifyStatusType(profile.value?.verify_status))

function isExpiring(c) {
  if (!c?.expires_at || c.status !== 'unused') return false
  const exp = new Date(c.expires_at).getTime()
  const now = Date.now()
  return exp > now && exp - now <= 7 * 24 * 3600 * 1000
}

const unusedList = computed(() => {
  const list = coupons.value.filter((c) => c.status === 'unused')
  list.sort((a, b) => {
    const ae = isExpiring(a) ? 0 : 1
    const be = isExpiring(b) ? 0 : 1
    if (ae !== be) return ae - be
    return new Date(a.expires_at) - new Date(b.expires_at)
  })
  return list.slice(0, 5)
})
const expiringList = computed(() => coupons.value.filter((c) => isExpiring(c)))
const unusedCount = computed(() => coupons.value.filter((c) => c.status === 'unused').length)
const usedCount = computed(() => coupons.value.filter((c) => c.status === 'used').length)

onMounted(async () => {
  try {
    const [profileRes, pointsRes, couponRes] = await Promise.all([
      api.get('/users/me/profile'),
      api.get('/points/me').catch(() => ({ data: { balance: 0 } })),
      api.get('/coupons/my').catch(() => ({ data: [] })),
    ])
    profile.value = profileRes.data
    balance.value = pointsRes.data.balance
    coupons.value = couponRes.data || []
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 4px;
}
.stat-item {
  background: var(--surface-2);
  border-radius: 10px;
  padding: 14px 12px;
  border: 1px solid var(--border);
}
.stat-item.is-accent {
  background: var(--brand-soft);
  border-color: rgba(15, 110, 106, 0.25);
}
.stat-item .label {
  font-size: 0.75rem;
  color: var(--muted);
  margin-bottom: 6px;
}
.stat-item .value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.1;
}
.stat-item .unit {
  font-size: 0.875rem;
  font-weight: 600;
  margin-left: 2px;
  color: var(--muted);
}
.status-val { margin-top: 4px; }
.coupon-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}
.coupon-row:last-child { border-bottom: none; }
@media (max-width: 720px) {
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .coupon-row { flex-direction: column; align-items: stretch; }
}
</style>
