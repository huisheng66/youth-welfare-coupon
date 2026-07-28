<template>
  <div data-od-id="admin-dashboard">
    <div class="page-card">
      <div class="page-header">
        <div>
          <h2 class="page-title">今日总览</h2>
          <p class="page-desc">优先处理待审与今日核销；下方为库存与累计指标。</p>
        </div>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>

      <el-skeleton v-if="loading && !data" animated :rows="4" />
      <template v-else>
        <p class="section-label">今日关注</p>
        <div class="stat-grid is-primary">
          <div
            v-for="item in primaryCards"
            :key="item.label"
            class="stat-item"
            :class="{ 'is-accent': item.accent }"
          >
            <div class="label">{{ item.label }}</div>
            <div class="value">{{ item.value }}</div>
          </div>
        </div>

        <p class="section-label" style="margin-top: 8px">库存与累计</p>
        <div class="stat-grid is-secondary">
          <div v-for="item in secondaryCards" :key="item.label" class="stat-item">
            <div class="label">{{ item.label }}</div>
            <div class="value">{{ item.value }}</div>
          </div>
        </div>

        <div class="quick-actions">
          <el-button type="primary" @click="$router.push('/admin/users')">处理用户核验</el-button>
          <el-button @click="$router.push('/admin/points')">发放志愿时长</el-button>
          <el-button @click="$router.push('/admin/templates')">管理券模板</el-button>
          <el-button @click="$router.push('/admin/redemptions')">查看核销流水</el-button>
        </div>
      </template>
    </div>

    <div class="page-card section-gap">
      <h2 class="page-title">最近动态</h2>
      <p class="page-desc">最新核销成功与待审申请</p>
      <el-empty
        v-if="!loading && !activities.length"
        description="暂无动态。完成一次发券或核销后会出现在这里。"
      />
      <el-timeline v-else-if="activities.length">
        <el-timeline-item
          v-for="(item, idx) in activities"
          :key="idx"
          :timestamp="formatTime(item.time)"
          :type="item.kind === 'redeem' ? 'success' : 'warning'"
          placement="top"
        >
          <div class="act-title">{{ item.title }}</div>
          <div class="muted act-detail">{{ item.detail }}</div>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../../api'
import { formatTime } from '../../utils/format'

const data = ref(null)
const loading = ref(false)

const primaryCards = computed(() => {
  const d = data.value || {}
  return [
    { label: '待审核', value: d.pending_verifications ?? '-', accent: true },
    { label: '今日核销', value: d.today_redemptions ?? '-' },
    { label: '今日发券', value: d.today_issued ?? '-' },
    { label: '已通过用户', value: d.approved_users ?? '-' },
  ]
})

const secondaryCards = computed(() => {
  const d = data.value || {}
  return [
    { label: '青年用户', value: d.users ?? '-' },
    { label: '未使用券', value: d.unused_coupons ?? '-' },
    { label: '已过期券', value: d.expired_coupons ?? '-' },
    { label: '累计核销', value: d.coupons_used ?? '-' },
    { label: '累计发券', value: d.coupons_issued ?? '-' },
    { label: '商家', value: d.merchants ?? '-' },
    { label: '券模板', value: d.templates ?? '-' },
  ]
})

const activities = computed(() => data.value?.recent_activity || [])

async function load() {
  loading.value = true
  try {
    const res = await api.get('/dashboard')
    data.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.act-title {
  font-weight: 600;
  color: var(--ink);
}

.act-detail {
  margin-top: 2px;
  font-size: 0.875rem;
}
</style>
