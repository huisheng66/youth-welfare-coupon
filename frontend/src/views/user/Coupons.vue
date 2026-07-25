<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">我的优惠券</h2>
        <p class="page-desc">到店前打开动态券码，约 60 秒刷新一次</p>
      </div>
      <el-radio-group v-model="status" @change="load">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="unused">未使用</el-radio-button>
        <el-radio-button label="used">已使用</el-radio-button>
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

    <el-dialog v-model="visible" title="到店出示动态券码" width="440px" @closed="stopTimer">
      <el-alert
        type="info"
        :closable="false"
        title="动态码约 60 秒刷新一次，截图转卖会很快失效。店员请扫描或粘贴当前动态码核销。"
        style="margin-bottom:12px"
      />
      <div v-if="live">
        <QrCode :value="live.live_code" :size="200" :key="live.live_code" />
        <div class="countdown muted">剩余 {{ remain }} 秒后自动刷新</div>
        <el-input
          type="textarea"
          :rows="3"
          :model-value="live.live_code"
          readonly
          style="margin-top:10px"
        />
        <p class="muted" style="text-align:center;margin-top:10px">
          {{ live.template_name }} · 仅限「{{ live.merchant_name }}」
        </p>
        <div style="text-align:center;display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
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
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import QrCode from '../../components/QrCode.vue'
import EmptyState from '../../components/EmptyState.vue'
import StatusTag from '../../components/StatusTag.vue'
import { couponStatusText, couponStatusType, formatTime } from '../../utils/format'

const items = ref([])
const status = ref('')
const visible = ref(false)
const current = ref(null)
const live = ref(null)
const remain = ref(0)
const showPermanent = ref(false)
let timer = null
let tickTimer = null

async function load() {
  const res = await api.get('/coupons/my', { params: { status: status.value || undefined } })
  items.value = res.data
}

function stopTimer() {
  if (timer) clearTimeout(timer)
  if (tickTimer) clearInterval(tickTimer)
  timer = null
  tickTimer = null
  live.value = null
  remain.value = 0
}

async function refreshLive() {
  if (!current.value) return
  const res = await api.get(`/coupons/instances/${current.value.id}/live-code`)
  live.value = res.data
  remain.value = res.data.expires_in
  if (timer) clearTimeout(timer)
  if (tickTimer) clearInterval(tickTimer)
  tickTimer = setInterval(() => {
    remain.value = Math.max(0, remain.value - 1)
  }, 1000)
  // refresh a bit before expiry
  const waitMs = Math.max(5, res.data.expires_in - 5) * 1000
  timer = setTimeout(refreshLive, waitMs)
}

async function showCode(c) {
  current.value = c
  showPermanent.value = false
  visible.value = true
  live.value = null
  try {
    await refreshLive()
  } catch {
    visible.value = false
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

onMounted(load)
onBeforeUnmount(stopTimer)
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
.countdown { text-align: center; margin-top: 8px; font-weight: 600; color: #2563eb; }
</style>
