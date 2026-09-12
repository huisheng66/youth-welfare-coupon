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

    <div class="page-card" style="margin-bottom:16px">
      <h2 class="page-title">券换时长</h2>
      <p class="page-desc">非时长兑换所得的未使用券可按模板当前标价换回时长，换回后券作废（每张券限一次）</p>
      <EmptyState
        v-if="!backOptions.length"
        title="暂无可换回时长的券"
        description="仅未使用、标价大于 0 且非时长兑换所得的券可换回时长"
      />
      <div v-for="item in backOptions" :key="item.coupon_id" class="row">
        <div>
          <strong>{{ item.template_name }}</strong>
          <div class="muted">商家：{{ item.merchant_name ?? '-' }} · 券码 {{ item.code }}</div>
          <div class="muted">有效期至 {{ formatTime(item.expires_at) }}</div>
        </div>
        <div class="actions">
          <el-tag type="success" effect="light" round>退 {{ formatHours(item.refund_hours) }} 小时</el-tag>
          <el-button type="warning" plain @click="exchangeBack(item)">
            换回时长
          </el-button>
        </div>
      </div>
    </div>

    <div class="page-card">
      <h2 class="page-title">时长流水</h2>
      <el-table :data="ledger" stripe>
        <template #empty>
          <EmptyState title="暂无流水" description="管理员入账或自助兑换后，变动会记录在这里" />
        </template>
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
import api from '../../api'
import EmptyState from '../../components/EmptyState.vue'
import { formatHours, formatTime } from '../../utils/format'
import { idempotencyHeader, newIdempotencyKey } from '../../utils/idempotency'

const router = useRouter()

const balance = ref(null)
const catalog = ref([])
const ledger = ref([])
const backOptions = ref([])

async function load() {
  const [b, c, l, o] = await Promise.all([
    api.get('/points/me'),
    api.get('/points/catalog'),
    api.get('/points/me/ledger', { params: { limit: 50 } }),
    api.get('/points/exchange-back/options'),
  ])
  balance.value = b.data.balance
  catalog.value = c.data
  ledger.value = l.data.items
  backOptions.value = o.data.items
}

// 同一兑换意图复用同一幂等键：超时/失败后重试由服务端重放，不会重复扣时长
let exchangeKey = ''

async function exchange(item) {
  await ElMessageBox.confirm(
    `确认用 ${formatHours(item.cost_points)} 小时兑换「${item.name}」？兑换后不可撤销。`,
    '兑换确认',
    { type: 'warning', confirmButtonText: '确认兑换', cancelButtonText: '取消' },
  )
  if (!exchangeKey) exchangeKey = newIdempotencyKey()
  let res
  try {
    res = await api.post(
      '/points/exchange',
      { template_id: item.id },
      { headers: idempotencyHeader(exchangeKey) },
    )
  } catch (err) {
    // 保留 key：用户重试本次兑换时复用，服务端按 key 重放原结果
    throw err
  }
  exchangeKey = ''
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

// 券换时长（T24）：与兑换同一幂等键模式——同一意图复用同一 key，成功后重置
let exchangeBackKey = ''

async function exchangeBack(item) {
  await ElMessageBox.confirm(
    `确认将「${item.template_name}」换回 ${formatHours(item.refund_hours)} 小时？该券将作废，操作不可撤销。`,
    '换回确认',
    { type: 'warning', confirmButtonText: '确认换回', cancelButtonText: '取消' },
  )
  if (!exchangeBackKey) exchangeBackKey = newIdempotencyKey()
  let res
  try {
    res = await api.post(
      '/points/exchange-back',
      { coupon_id: item.coupon_id },
      { headers: idempotencyHeader(exchangeBackKey) },
    )
  } catch (err) {
    // 保留 key：用户重试本次换回时复用，服务端按 key 重放原结果
    throw err
  }
  exchangeBackKey = ''
  ElMessage.success(`已换回 ${formatHours(res.data.refunded_hours)} 小时`)
  await load()
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

@media (max-width: 640px) {
  .row {
    align-items: stretch;
    flex-direction: column;
  }

  .actions {
    justify-content: space-between;
  }

  .actions .el-button {
    min-width: 112px;
    min-height: 44px;
  }
}
</style>
