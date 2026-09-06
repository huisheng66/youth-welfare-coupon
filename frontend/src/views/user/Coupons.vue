<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">我的优惠券</h2>
        <p class="page-desc">到店前打开动态券码，约 30 秒刷新一次；商家核销后会立即提示成功</p>
      </div>
      <el-radio-group v-model="status" @change="onStatusChange">
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

    <div v-if="total > pageSize" class="pager">
      <span class="muted">共 {{ total }} 张</span>
      <el-pagination
        v-model:current-page="page"
        layout="prev, pager, next"
        :page-size="pageSize"
        :total="total"
        @current-change="load"
      />
    </div>

    <el-dialog
      v-model="visible"
      :title="dialogTitle"
      width="440px"
      @closed="onDialogClosed"
    >
      <!-- 核销成功：商家扫码后由状态轮询触发 -->
      <div v-if="phase === 'redeemed'" class="success-wrap">
        <el-result icon="success" title="核销成功" sub-title="商家已完成扫码核销，本券已使用">
          <template #extra>
            <el-button type="primary" @click="closeAfterSuccess">完成</el-button>
          </template>
        </el-result>
        <p class="muted center" v-if="current">
          {{ current.template_name }} · {{ current.merchant_name }}
        </p>
      </div>

      <!-- 终态：已作废 / 已过期（轮询发现后展示） -->
      <div v-else-if="phase === 'gone'" class="success-wrap">
        <el-result icon="warning" :title="`本券${couponStatusText(goneReason)}`" sub-title="动态码已不能出示">
          <template #extra>
            <el-button @click="visible = false">关闭</el-button>
          </template>
        </el-result>
      </div>

      <template v-else>
        <el-alert
          type="info"
          :closable="false"
          title="动态码约 30 秒刷新一次。店员扫码核销后，本页会立即显示成功，无需等待刷新。"
          style="margin-bottom:12px"
        />

        <!-- 断网 / 刷新失败：保留上次有效动态码（若未过期）+ 重试入口 -->
        <el-alert
          v-if="offline"
          type="error"
          :closable="false"
          style="margin-bottom:12px"
          title="网络连接不稳定"
          :description="live ? '正在自动重试；下方动态码在过期前仍可出示。' : '正在自动重试，也可手动重试。'"
        >
          <el-button size="small" type="primary" plain :loading="refreshing" @click="manualRetry">
            立即重试
          </el-button>
        </el-alert>

        <div v-if="live" class="live-wrap" :class="{ 'is-stale': offline }">
          <QrCode :value="live.live_code" :size="200" :key="live.live_code" />
          <div class="countdown">
            <span v-if="remain > 0">剩余 {{ remain }} 秒后自动刷新</span>
            <span v-else>
              <el-icon class="is-loading" style="vertical-align:-2px"><Loading /></el-icon>
              正在获取新动态码…
            </span>
          </div>
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
          </div>
          <p class="muted center" style="margin-top:8px">
            无摄像头时店员可手动输入动态码核销；永久编号已不能用于核销
          </p>
        </div>
        <!-- 首次加载 / 无有效动态码：骨架屏 -->
        <el-skeleton v-else animated :rows="4" />
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import api from '../../api'
import QrCode from '../../components/QrCode.vue'
import EmptyState from '../../components/EmptyState.vue'
import StatusTag from '../../components/StatusTag.vue'
import { couponStatusText, couponStatusType, formatTime } from '../../utils/format'

const route = useRoute()
const router = useRouter()

const items = ref([])
const status = ref('')
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const visible = ref(false)
const current = ref(null)
const live = ref(null)
const remain = ref(0)
/** loading → ready；redeemed / gone 为终态（T16 条款 1） */
const phase = ref('loading')
const goneReason = ref('')
/** 网络不可用 / 刷新失败（T16 条款 4：退避 + 手动重试） */
const offline = ref(false)
const refreshing = ref(false)

const dialogTitle = computed(() => {
  if (phase.value === 'redeemed') return '核销成功'
  if (phase.value === 'gone') return '动态码不可用'
  return '到店出示动态券码'
})

let refreshTimer = null
let tickTimer = null
let pollTimer = null
let retryTimer = null
/** 服务端校准的动态码到期时刻（ms）：每次签发按 expires_in 重新锚定，
 * 倒计时从 deadline 推算而非每秒递减，后台节流/休眠后自动对齐（T16 条款 2） */
let deadlineMs = 0
/** 请求代次：开窗/切券/回到前台/手动重试时递增；晚到响应按代次丢弃（T16 条款 3） */
let gen = 0
/** 轮询与刷新单飞标志（T16 条款 4） */
let pollInFlight = false
let refreshInFlight = false
/** 网络错误退避序列（秒） */
let backoffIdx = 0
let abortCtrl = null

const BACKOFF_STEPS_MS = [1000, 2000, 4000, 8000, 10000]

async function load() {
  const res = await api.get('/coupons/my', {
    params: {
      status: status.value || undefined,
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    },
  })
  items.value = res.data.items
  total.value = res.data.total
  return res.data
}

// 筛选切换回第一页
function onStatusChange() {
  page.value = 1
  load()
}

async function openFromQuery() {
  const openId = route.query.open
  if (!openId || typeof openId !== 'string') return
  const data = items.value.length ? { items: items.value } : await load()
  const hit = (data.items || []).find((c) => c.id === openId && c.status === 'unused')
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
  if (retryTimer) clearTimeout(retryTimer)
  refreshTimer = null
  tickTimer = null
  pollTimer = null
  retryTimer = null
}

function abortInflight() {
  if (abortCtrl) {
    abortCtrl.abort()
    abortCtrl = null
  }
}

/** 递增代次并断开在途请求：调用方保证随后发起新一代请求 */
function nextGen() {
  gen += 1
  abortInflight()
  pollInFlight = false
  refreshInFlight = false
  return gen
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
  nextGen()
  clearTimers()
  live.value = null
  remain.value = 0
  phase.value = 'loading'
  goneReason.value = ''
  offline.value = false
  refreshing.value = false
  current.value = null
}

function closeAfterSuccess() {
  visible.value = false
  onDialogClosed()
  load()
}

function onRedeemedSuccess() {
  if (phase.value === 'redeemed') return
  phase.value = 'redeemed'
  offline.value = false
  nextGen()
  clearTimers()
  ElMessage.success('商家已核销成功')
  // 后台列表同步
  load()
}

/** 轮询单券轻量状态（T18）：成本不随用户券数增长；核销 → 成功，作废/过期 → 终态。 */
async function checkRedeemed() {
  const g = gen
  if (!current.value || pollInFlight || phase.value === 'redeemed' || phase.value === 'gone') return
  pollInFlight = true
  try {
    const res = await api.get(`/coupons/instances/${current.value.id}/status`, { silent: true })
    if (g !== gen) return
    const st = res.data.status
    if (st === 'used') {
      onRedeemedSuccess()
      return
    }
    if (st === 'void' || st === 'expired') {
      phase.value = 'gone'
      goneReason.value = st
      nextGen()
      clearTimers()
      return
    }
  } catch {
    // 404 可能是轮询间隙状态变更，不打断；其余由下一轮覆盖
  } finally {
    if (g === gen) pollInFlight = false
  }
}

function startTick() {
  if (tickTimer) clearInterval(tickTimer)
  tickTimer = setInterval(() => {
    remain.value = Math.max(0, Math.ceil((deadlineMs - Date.now()) / 1000))
  }, 500)
}

function scheduleRefresh(g) {
  const waitSec = Math.max(3, Math.ceil((deadlineMs - Date.now()) / 1000) - 3)
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => {
    if (g === gen) refreshLive()
  }, waitSec * 1000)
}

async function refreshLive() {
  const g = gen
  if (!current.value || refreshInFlight) return
  if (phase.value === 'redeemed' || phase.value === 'gone') return
  // 刷新前先看是否已核销/终态
  await checkRedeemed()
  if (g !== gen || phase.value === 'redeemed' || phase.value === 'gone') return
  refreshInFlight = true
  refreshing.value = true
  abortCtrl = new AbortController()
  try {
    const res = await api.get(`/coupons/instances/${current.value.id}/live-code`, {
      silent: true,
      signal: abortCtrl.signal,
    })
    if (g !== gen) return
    backoffIdx = 0
    offline.value = false
    live.value = res.data
    // 服务端校准：以响应到达时刻 + 服务端剩余秒数重锚定 deadline
    deadlineMs = Date.now() + res.data.expires_in * 1000
    remain.value = res.data.expires_in
    phase.value = 'ready'
    startTick()
    scheduleRefresh(g)
  } catch (e) {
    if (g !== gen) return
    if (e?.code === 'ERR_CANCELED') return
    const status_ = e?.response?.status
    const detail = e?.response?.data?.detail || ''
    if (status_ === 400) {
      // 核销后 live-code 返回「当前状态不可出示：used」
      if (String(detail).includes('used')) {
        onRedeemedSuccess()
        return
      }
      if (String(detail).includes('expired') || String(detail).includes('void')) {
        phase.value = 'gone'
        goneReason.value = String(detail).includes('void') ? 'void' : 'expired'
        nextGen()
        clearTimers()
        return
      }
    }
    // 401 会话失效由 api.js 拦截器统一跳登录（T05 全局行为）
    // 其它（网络/5xx）：退避重试，不清弹窗
    offline.value = true
    const delay = BACKOFF_STEPS_MS[Math.min(backoffIdx, BACKOFF_STEPS_MS.length - 1)]
    backoffIdx += 1
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => {
      if (g === gen) refreshLive()
    }, delay)
  } finally {
    if (g === gen) {
      refreshInFlight = false
      refreshing.value = false
    }
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
  nextGen()
  current.value = c
  phase.value = 'loading'
  visible.value = true
  live.value = null
  remain.value = 0
  offline.value = false
  clearTimers()
  startStatusPoll()
  await refreshLive()
  if (gen > 0 && phase.value === 'loading' && !live.value && !offline.value) {
    // 首签发失败且非终态时兜底关窗，避免空壳弹窗
    visible.value = false
  }
}

function manualRetry() {
  if (!current.value || phase.value === 'redeemed' || phase.value === 'gone') return
  backoffIdx = 0
  offline.value = false
  const g = nextGen()
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => {
    if (g === gen) refreshLive()
  }, 0)
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

function onVisibilityChange() {
  if (!visible.value || phase.value === 'redeemed' || phase.value === 'gone') return
  if (document.visibilityState === 'hidden') {
    // 页面隐藏：暂停倒计时与轮询（定时器被浏览器节流不可靠）
    if (refreshTimer) clearTimeout(refreshTimer)
    if (pollTimer) clearInterval(pollTimer)
    refreshTimer = null
    pollTimer = null
    if (tickTimer) clearInterval(tickTimer)
    tickTimer = null
    return
  }
  // 回到前台：重新同步——先查状态再重签动态码（不依赖本地倒计时）
  const g = nextGen()
  deadlineMs = 0
  remain.value = 0
  startTick()
  checkRedeemed()
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => {
    if (g === gen) refreshLive()
  }, 0)
  startStatusPoll()
}

onMounted(async () => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  await load()
  await openFromQuery()
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  nextGen()
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
.live-wrap.is-stale {
  opacity: 0.72;
}
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
.pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
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
