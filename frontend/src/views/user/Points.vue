<template>
  <div>
    <div class="page-card" style="margin-bottom:16px">
      <h2 class="page-title">我的志愿服务时长</h2>
      <p class="page-desc">管理员入账后可在此兑换指定商家优惠券</p>
      <div class="stat-grid">
        <div class="stat-item is-accent">
          <div class="label">可用时长（小时）</div>
          <div class="value">{{ balance == null ? '-' : formatHours(balance) }}</div>
        </div>
      </div>
    </div>

    <div class="page-card" style="margin-bottom:16px">
      <h2 class="page-title">可兑换券</h2>
      <p class="page-desc">仅展示兑换时长大于 0 的启用模板</p>
      <EmptyState
        v-if="!catalog.length"
        title="暂无可兑换券"
        description="请联系管理员配置可兑换模板，或等待时长入账"
      />
      <div v-for="item in catalog" :key="item.id" class="row">
        <div>
          <strong>{{ item.name }}</strong>
          <div class="muted">商家：{{ item.merchant_name }} · 有效 {{ item.valid_days }} 天</div>
          <div class="muted">{{ item.description }}</div>
        </div>
        <div class="actions">
          <el-tag type="warning" effect="light" round>{{ formatHours(item.cost_points) }} 小时</el-tag>
          <el-button
            type="primary"
            :disabled="Number(balance ?? 0) < Number(item.cost_points)"
            @click="exchange(item)"
          >
            兑换
          </el-button>
        </div>
      </div>
    </div>

    <div class="page-card">
      <h2 class="page-title">时长流水</h2>
      <el-table :data="ledger" stripe empty-text="暂无流水">
        <el-table-column prop="change" label="变动" width="110">
          <template #default="{ row }">
            <span :style="{ color: row.change >= 0 ? 'var(--success)' : 'var(--danger)', fontWeight: 600 }">
              {{ row.change >= 0 ? '+' : '' }}{{ formatHours(row.change) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="余额" width="100">
          <template #default="{ row }">{{ formatHours(row.balance_after) }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="说明" min-width="160" />
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'
import EmptyState from '../../components/EmptyState.vue'
import { formatHours, formatTime } from '../../utils/format'

const router = useRouter()

const balance = ref(null)
const catalog = ref([])
const ledger = ref([])

async function load() {
  const [b, c, l] = await Promise.all([
    api.get('/points/me'),
    api.get('/points/catalog'),
    api.get('/points/me/ledger', { params: { limit: 50 } }),
  ])
  balance.value = b.data.balance
  catalog.value = c.data
  ledger.value = l.data.items
}

async function exchange(item) {
  await ElMessageBox.confirm(
    `确认用 ${formatHours(item.cost_points)} 小时兑换「${item.name}」？兑换后不可撤销。`,
    '兑换确认',
    { type: 'warning', confirmButtonText: '确认兑换', cancelButtonText: '取消' },
  )
  const res = await api.post('/points/exchange', { template_id: item.id })
  ElMessage.success(`兑换成功，券码 ${res.data.coupon.code}`)
  const couponId = res.data.coupon?.id
  if (couponId) {
    await ElMessageBox.confirm('是否立即出示动态券码？', '兑换成功', {
      confirmButtonText: '出示券码',
      cancelButtonText: '稍后再说',
      type: 'success',
    }).then(() => {
      router.push({ path: '/user/coupons', query: { open: couponId } })
    }).catch(() => {
      load()
    })
  } else {
    load()
  }
}

onMounted(load)
</script>

<style scoped>
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.row:last-child { border-bottom: none; }
.actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
</style>
