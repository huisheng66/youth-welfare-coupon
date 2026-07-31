<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">我的优惠券</h2>
        <p class="page-desc">到店前打开动态券码，约 30 秒刷新一次；商家核销后会立即提示成功</p>
      </div>
      <el-radio-group v-model="status" @change="load">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="unused">未使用</el-radio-button>
        <el-radio-button label="used">已使用</el-radio-button>
        <el-radio-button label="void">已作废</el-radio-button>
        <el-radio-button label="expired">已过期</el-radio-button>
      </el-radio-group>
    </div>

    <EmptyState
      v-if="!items.length"
      title="暂无优惠券"
      description="可通过管理员发券，或在「时长兑换」中自助兑换"
    >
      <el-button type="primary" @click="$router.push('/user/points')">去兑换</el-button>
    </EmptyState>
    <div v-for="c in items" :key="c.id" class="coupon-card">
      <div>
        <strong>{{ c.template_name }}</strong>
        <div class="muted">指定商家：{{ c.merchant_name }}</div>
        <div class="muted">
          <StatusTag :text="couponStatusText(c.status)" :type="couponStatusType(c.status)" />
          <span style="margin-left:8px">过期 {{ formatTime(c.expires_at) }}</span>
        </div>
      </div>
      <el-button type="primary" :disabled="c.status !== 'unused'" @click="showCode(c)">出示动态券码</el-button>
    </div>

    <el-dialog
      v-model="visible"
      :title="redeemed ? '核销成功' : '到店出示动态券码'"
      width="440px"
      @closed="onDialogClosed"
    >
      <!-- 商家核销后立即展示 -->
      <div v-if="redeemed" class="success-wrap">
        <el-result icon="success" title="核销成功" sub-title="商家已完成扫码核销，本券已使用">
          <template #extra>
            <el-button type="primary" @click="closeAfterSuccess">完成</el-button>
          </template>
        </el-result>
        <p class="muted center" v-if="current">
          {{ current.template_name }} · {{ current.merchant_name }}
        </p>
      </div>

      <template v-else>
        <el-alert
          type="info"
          :closable="false"
          title="动态码约 30 秒刷新一次。店员扫码核销后，本页会立即显示成功，无需等待刷新。"
          style="margin-bottom:12px"
        />
        <div v-if="live">
          <QrCode :value="live.live_code" :size="200" :key="live.live_code" />
          <div class="countdown">剩余 {{ remain }} 秒后自动刷新</div>
          <el-input
            type="textarea"
            :rows="3"
            :model-value="live.live_code"
            readonly
            style="margin-top:10px"
          />
          <p class="muted center" style="margin-top:10px">
            {{ live.template_name }} · 仅限「{{ live.merchant_name }}」
          </p>
          <div class="btn-row">
            <el-button @click="copyLive">复制动态码</el-button>
            <el-button link type="primary" @click="showPermanent = !showPermanent">
              {{ showPermanent ? '隐藏' : '显示' }}备用永久码
            </el-button>
          </div>
          <div v-if="showPermanent" class="coupon-code" style="margin-top:12px;font-size:18px">
            {{ live.permanent_code }}
          </div>
        </div>
        <el-skeleton v-else animated :rows="4" />
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../../api'
import QrCode from '../../components/QrCode.vue'
import EmptyState from '../../components/EmptyState.vue'
import StatusTag from '../../components/StatusTag.vue'
import { couponStatusText, couponStatusType, formatTime } from '../../utils/format'

const route = useRoute()
const router = useRouter()

const items = ref([])
const status = ref('')
const visible = ref(false)
const current = ref(null)
const live = ref(null)
const remain = ref(0)
const showPermanent = ref(false)
const redeemed = ref(false)

let refreshTimer = null
let tickTimer = null
let pollTimer = null

async function load() {
  const res = await api.get('/coupons/my', { params: { status: status.value || undefined } })
  items.value = res.data
  return res.data
}

async function openFromQuery() {
  const openId = route.query.open
  if (!openId || typeof openId !== 'string') return
  const list = items.value.length ? items.value : await load()
  const hit = list.find((c) => c.id === openId && c.status === 'unused')
  if (hit) {
    await showCode(hit)
  }
  // 清掉 query，避免刷新反复弹窗
  router.replace({ path: '/user/coupons', query: {} })
}

function clearTimers() {
  if (refreshTimer) clearTimeout(refreshTimer)
  if (tickTimer) clearInterval(tickTimer)
  if (pollTimer) clearInterval(pollTimer)
  refreshTimer = null
  tickTimer = null
  pollTimer = null
}

function stopLiveOnly() {
  if (refreshTimer) clearTimeout(refreshTimer)
  if (tickTimer) clearInterval(tickTimer)
  refreshTimer = null
  tickTimer = null
  live.value = null
  remain.value = 0
}

function onDialogClosed() {
  clearTimers()
  live.value = null
  remain.value = 0
  redeemed.value = false
  current.value = null
}

function closeAfterSuccess() {
  visible.value = false
  onDialogClosed()
  load()
}

async function checkRedeemed() {
  if (!current.value || redeemed.value) return false
  try {
    // 静默查询：不走会弹错误的 live-code
    const res = await api.get('/coupons/my', { silent: true })
    const hit = (res.data || []).find((c) => c.id === current.value.id)
    if (hit) {
      current.value = { ...current.value, ...hit }
      if (hit.status === 'used') {
        onRedeemedSuccess()
        return true
      }
    }
  } catch {
    // ignore poll errors
  }
  return false
}

function onRedeemedSuccess() {
  if (redeemed.value) return
  redeemed.value = true
  stopLiveOnly()
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  ElMessage.success('商家已核销成功')
  // 后台列表同步
  load()
}

async function refreshLive() {
  if (!current.value || redeemed.value) return
  // 刷新前先看是否已核销
  if (await checkRedeemed()) return
  try {
    const res = await api.get(`/coupons/instances/${current.value.id}/live-code`, { silent: true })
    if (redeemed.value) return
    live.value = res.data
    remain.value = res.data.expires_in
    if (refreshTimer) clearTimeout(refreshTimer)
    if (tickTimer) clearInterval(tickTimer)
    tickTimer = setInterval(() => {
      remain.value = Math.max(0, remain.value - 1)
    }, 1000)
    // 到期前约 3 秒刷新（30s 周期）
    const waitMs = Math.max(3, res.data.expires_in - 3) * 1000
    refreshTimer = setTimeout(refreshLive, waitMs)
  } catch (e) {
    const detail = e?.response?.data?.detail || ''
    // 核销后 live-code 会返回「当前状态不可出示：used」
    if (typeof detail === 'string' && detail.includes('used')) {
      onRedeemedSuccess()
      return
    }
    // 其它错误不关窗，继续轮询状态
  }
}

function startStatusPoll() {
  if (pollTimer) clearInterval(pollTimer)
  // 约 1.5 秒轮询一次券状态，核销后几乎立刻提示
  pollTimer = setInterval(() => {
    checkRedeemed()
  }, 1500)
}

async function showCode(c) {
  current.value = c
  showPermanent.value = false
  redeemed.value = false
  visible.value = true
  live.value = null
  clearTimers()
  startStatusPoll()
  try {
    await refreshLive()
  } catch {
    if (!redeemed.value) {
      visible.value = false
    }
  }
}

async function copyLive() {
  if (!live.value?.live_code) return
  try {
    await navigator.clipboard.writeText(live.value.live_code)
    ElMessage.success('动态码已复制')
  } catch {
    ElMessage.info('请手动复制')
  }
}

onMounted(async () => {
  await load()
  await openFromQuery()
})
onBeforeUnmount(() => {
  clearTimers()
})
</script>

<style scoped>
.coupon-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.coupon-card:last-child { border-bottom: none; }
.countdown {
  text-align: center;
  margin-top: 8px;
  font-weight: 600;
  color: var(--brand, #0f6e6a);
}
.center { text-align: center; }
.btn-row {
  text-align: center;
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 8px;
}
.success-wrap {
  padding: 8px 0 4px;
}

@media (max-width: 640px) {
  .coupon-card {
    align-items: stretch;
    flex-direction: column;
  }

  .coupon-card .el-button {
    width: 100%;
    min-height: 44px;
  }
}
</style>
