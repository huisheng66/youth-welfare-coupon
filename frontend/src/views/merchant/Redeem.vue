<template>
  <div class="redeem-page">
    <div class="page-card stats-card" style="margin-bottom:16px">
      <h2 class="page-title">{{ stats?.merchant_name || '本店' }}</h2>
      <p class="page-desc">仅可核销本店适用券；支持扫用户动态二维码或粘贴券码</p>
      <el-skeleton v-if="!stats" animated :rows="2" />
      <div v-else class="stat-grid">
        <div class="stat-item is-accent">
          <div class="label">今日核销</div>
          <div class="value">{{ stats.today_success }}</div>
        </div>
        <div class="stat-item">
          <div class="label">累计核销</div>
          <div class="value">{{ stats.total_success }}</div>
        </div>
        <div class="stat-item">
          <div class="label">本店未使用券</div>
          <div class="value">{{ stats.unused_for_store }}</div>
        </div>
        <div class="stat-item">
          <div class="label">本店已核销券</div>
          <div class="value">{{ stats.used_for_store }}</div>
        </div>
      </div>
    </div>

    <div class="page-card scan-card" style="margin-bottom:16px">
      <div class="page-header">
        <div>
          <h2 class="page-title">扫码核销</h2>
          <p class="page-desc">手机后置摄像头对准用户屏幕上的二维码</p>
        </div>
        <el-switch
          v-model="autoRedeem"
          active-text="扫码后自动核销"
          inactive-text="扫码后仅预览"
        />
      </div>
      <QrScanner ref="scannerRef" @scan="onScanned" />
    </div>

    <div class="page-card code-card">
      <h2 class="page-title">券码核销</h2>
      <p class="page-desc">也可手动粘贴用户出示的动态码（永久编号已不能核销）</p>
      <el-input
        v-model="code"
        size="large"
        type="textarea"
        :rows="3"
        placeholder="粘贴动态券码（Ctrl+Enter 预览）"
        clearable
        @keydown.ctrl.enter.prevent="onPreview"
      />
      <div class="quick-actions">
        <el-button size="large" @click="onPreview" :loading="previewing">预览券信息</el-button>
        <el-button type="primary" size="large" :loading="loading" :disabled="!canRedeem" @click="onRedeem">
          确认核销
        </el-button>
        <el-button size="large" @click="reset">清空</el-button>
        <el-button v-if="result?.ok" size="large" type="success" plain @click="continueScan">
          继续扫下一张
        </el-button>
      </div>

      <el-descriptions v-if="preview" :column="1" border class="section-gap">
        <el-descriptions-item label="模板">{{ preview.template_name }}</el-descriptions-item>
        <el-descriptions-item label="用户">{{ preview.username }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <StatusTag :text="couponStatusText(preview.status)" :type="couponStatusType(preview.status)" />
        </el-descriptions-item>
        <el-descriptions-item label="过期时间">{{ formatTime(preview.expires_at) }}</el-descriptions-item>
      </el-descriptions>

      <el-result
        v-if="result"
        class="section-gap"
        :icon="result.icon"
        :title="result.title"
        :sub-title="result.sub"
      >
        <template v-if="result.icon === 'warning'" #extra>
          <el-button type="primary" :loading="loading" @click="queryRedeemResult">查询结果</el-button>
          <el-button @click="$router.push('/merchant/logs')">查看核销记录</el-button>
        </template>
      </el-result>
    </div>

    <div class="page-card recent-card" style="margin-top:16px">
      <div class="page-header">
        <div>
          <h2 class="page-title">今日 / 近期核销</h2>
          <p class="page-desc">最近 8 条本店流水，完整记录见「核销记录」</p>
        </div>
        <el-button link type="primary" @click="$router.push('/merchant/logs')">全部记录</el-button>
      </div>
      <el-table :data="recent" size="small" stripe empty-text="暂无记录">
        <el-table-column prop="code" label="券码" min-width="120" show-overflow-tooltip />
        <el-table-column prop="username" label="用户" width="100" />
        <el-table-column label="结果" width="80">
          <template #default="{ row }">
            <StatusTag
              :text="row.result === 'success' ? '成功' : '失败'"
              :type="row.result === 'success' ? 'success' : 'danger'"
            />
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import api from '../../api'
import QrScanner from '../../components/QrScanner.vue'
import StatusTag from '../../components/StatusTag.vue'
import { couponStatusText, couponStatusType, formatTime } from '../../utils/format'
import { newIdempotencyKey, idempotencyHeader } from '../../utils/idempotency'

const code = ref('')
const loading = ref(false)
const previewing = ref(false)
const preview = ref(null)
const result = ref(null)
const stats = ref(null)
const recent = ref([])
const autoRedeem = ref(false)
const scannerRef = ref(null)
const handling = ref(false)
/** T16 条款 5：预览锁定——扫码/输入与预览对应同一券码时才可核销 */
const lockedCode = ref('')
/** T16 条款 7：核销请求在途时的幂等键（超时后同 key 查询/重试） */
let redeemKey = ''
/** 结果确认请求单飞 */
let confirmInFlight = false

const canRedeem = computed(
  () =>
    !!code.value.trim() &&
    !!preview.value &&
    preview.value.status === 'unused' &&
    lockedCode.value === code.value.trim(),
)

// 输入变化即清理旧预览/旧结果：预览只对应锁定时的券码（T16 条款 5）
watch(code, () => {
  if (lockedCode.value && lockedCode.value !== code.value.trim()) {
    preview.value = null
    result.value = null
    lockedCode.value = ''
    redeemKey = ''
  }
})

async function loadStats() {
  const res = await api.get('/merchant-dashboard')
  stats.value = res.data
}

async function loadRecent() {
  try {
    const res = await api.get('/coupons/redemptions', { params: { limit: 8 }, silent: true })
    recent.value = res.data.items || []
  } catch {
    recent.value = []
  }
}

function reset() {
  code.value = ''
  preview.value = null
  result.value = null
  lockedCode.value = ''
  redeemKey = ''
}

async function continueScan() {
  reset()
  try {
    await scannerRef.value?.start?.()
  } catch {
    // ignore
  }
}

async function onScanned(text) {
  if (handling.value) return
  handling.value = true
  try {
    // 新扫码：清理旧预览与旧结果，锁定到新码（T16 条款 5）
    preview.value = null
    result.value = null
    redeemKey = ''
    code.value = text
    lockedCode.value = ''
    ElMessage.success('已识别二维码')
    // pause camera to avoid multi-fire while processing
    await scannerRef.value?.stop?.()
    const ok = await onPreview()
    if (ok && autoRedeem.value && preview.value?.status === 'unused') {
      await onRedeem()
    }
  } finally {
    handling.value = false
  }
}

async function onPreview() {
  if (!code.value.trim()) {
    ElMessage.warning('请输入券码')
    return false
  }
  previewing.value = true
  preview.value = null
  result.value = null
  lockedCode.value = ''
  redeemKey = ''
  // 锁定发起请求时的输入；响应回来时输入已变则丢弃（T16 条款 3/5）
  const sentCode = code.value.trim()
  try {
    const res = await api.post('/coupons/preview', { code: sentCode })
    if (code.value.trim() !== sentCode) {
      return false
    }
    preview.value = res.data
    lockedCode.value = sentCode
    if (res.data.status !== 'unused') {
      ElMessage.warning(`当前状态：${couponStatusText(res.data.status)}，不可核销`)
      return false
    }
    return true
  } catch {
    preview.value = null
    return false
  } finally {
    previewing.value = false
  }
}

async function onRedeem() {
  if (!canRedeem.value) {
    ElMessage.warning('请先预览券信息，且输入与预览一致后再核销')
    return
  }
  // 确认前重新验证：动态码可能在预览后过期/被作废（T16 条款 5）
  const ok = await onPreview()
  if (!ok) return
  try {
    const who = preview.value
      ? `${preview.value.template_name || '优惠券'} · ${preview.value.username || ''}`
      : '该券'
    await ElMessageBox.confirm(`确认核销「${who}」？核销后不可撤销。`, '确认核销', {
      type: 'warning',
      confirmButtonText: '确认核销',
    })
  } catch {
    return
  }
  loading.value = true
  result.value = null
  // 一次核销意图一个幂等 key；超时重试复用同一 key
  redeemKey = newIdempotencyKey()
  try {
    const res = await api.post('/coupons/redeem', { code: code.value.trim() }, {
      headers: idempotencyHeader(redeemKey),
      timeout: 20000,
    })
    result.value = {
      icon: 'success',
      title: '核销成功',
      sub: `${res.data.coupon.template_name || ''} · 用户 ${res.data.coupon.username || ''}`,
    }
    code.value = ''
    preview.value = null
    lockedCode.value = ''
    redeemKey = ''
    ElMessage.success('核销成功')
    loadStats()
    loadRecent()
  } catch (e) {
    if (e?.code === 'ECONNABORTED' || e?.message === 'Network Error' || !e?.response) {
      // 超时/断网：请求可能已成功，不能把重试报「已使用」当失败（T16 条款 7）
      result.value = {
        icon: 'warning',
        title: '结果确认中',
        sub: '核销请求超时，结果未知。请点击「查询结果」确认，不要重复扫码核销。',
      }
    } else {
      result.value = {
        icon: 'error',
        title: '核销失败',
        sub: e.response?.data?.detail || e.message,
      }
      redeemKey = ''
    }
  } finally {
    loading.value = false
  }
}

/** 结果确认：先查本店流水，无记录再用同 key 重试核销（服务端幂等重放原结果） */
async function queryRedeemResult() {
  if (!redeemKey || confirmInFlight) return
  confirmInFlight = true
  loading.value = true
  try {
    const res = await api.get('/coupons/redemptions', {
      params: { result: 'success', limit: 20 },
      silent: true,
    })
    const hit = (res.data?.items || []).find(
      (r) => r.code && preview.value && r.code === (preview.value.code || '').slice(0, 32),
    )
    if (hit) {
      result.value = { icon: 'success', title: '核销成功', sub: '已在核销记录中确认本次核销结果' }
      loadStats()
      loadRecent()
      return
    }
    // 无成功记录：同 key 重试（若首次实际已成功，服务端幂等重放；若未到达，正常执行）
    const retry = await api.post('/coupons/redeem', { code: code.value.trim() }, {
      headers: idempotencyHeader(redeemKey),
      timeout: 20000,
    })
    result.value = {
      icon: 'success',
      title: '核销成功',
      sub: `${retry.data.coupon.template_name || ''} · 用户 ${retry.data.coupon.username || ''}`,
    }
    code.value = ''
    preview.value = null
    lockedCode.value = ''
    redeemKey = ''
    loadStats()
    loadRecent()
  } catch (e) {
    result.value = {
      icon: 'error',
      title: '核销未成功',
      sub: e?.response?.data?.detail || '确认失败，请到核销记录中人工核对后再操作',
    }
    redeemKey = ''
  } finally {
    loading.value = false
    confirmInFlight = false
  }
}

onMounted(() => {
  loadStats()
  loadRecent()
})
onBeforeUnmount(() => {
  // 离开页面：关闭摄像头，防止残留（T16 验收：页面切换后无残留摄像头）
  try {
    scannerRef.value?.stop?.()
  } catch {
    // ignore
  }
})
</script>

<style scoped>
/* 手机端商家打开页面即扫：扫码核销 → 券码核销 → 数据看板 → 近期核销；
 * 桌面端保持原顺序（数据看板 → 扫码核销 → 券码核销 → 近期核销） */
@media (max-width: 640px) {
  .redeem-page {
    display: flex;
    flex-direction: column;
  }

  .scan-card {
    order: 1;
  }

  .code-card {
    order: 2;
    margin-bottom: 16px;
  }

  .stats-card {
    order: 3;
  }

  .recent-card {
    order: 4;
    /* stats-card 的 margin-bottom 已提供 16px 间距；flex 容器内边距不折叠，
     * !important 用于覆盖内联 margin-top 避免叠加成 32px */
    margin-top: 0 !important;
  }
}
</style>
