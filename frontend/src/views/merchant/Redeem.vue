<template>
  <div>
    <div class="page-card" style="margin-bottom:16px">
      <h2 class="page-title">{{ stats?.merchant_name || '本店' }}</h2>
      <p class="page-desc">仅可核销本店适用券，建议先预览再确认</p>
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

    <div class="page-card">
      <h2 class="page-title">优惠券核销</h2>
      <p class="page-desc">支持用户出示的动态券码或备用永久券码</p>
      <el-input
        v-model="code"
        size="large"
        type="textarea"
        :rows="3"
        placeholder="粘贴动态券码，或输入永久券码"
        clearable
      />
      <div class="quick-actions">
        <el-button size="large" @click="onPreview" :loading="previewing">预览券信息</el-button>
        <el-button type="primary" size="large" :loading="loading" :disabled="!canRedeem" @click="onRedeem">
          确认核销
        </el-button>
        <el-button size="large" @click="reset">清空</el-button>
      </div>

      <el-descriptions v-if="preview" :column="1" border class="section-gap">
        <el-descriptions-item label="券码">{{ preview.code }}</el-descriptions-item>
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
        :icon="result.ok ? 'success' : 'error'"
        :title="result.title"
        :sub-title="result.sub"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import StatusTag from '../../components/StatusTag.vue'
import { couponStatusText, couponStatusType, formatTime } from '../../utils/format'

const code = ref('')
const loading = ref(false)
const previewing = ref(false)
const preview = ref(null)
const result = ref(null)
const stats = ref(null)

const canRedeem = computed(() => !!code.value.trim() && preview.value?.status === 'unused')

async function loadStats() {
  const res = await api.get('/merchant-dashboard')
  stats.value = res.data
}

function reset() {
  code.value = ''
  preview.value = null
  result.value = null
}

async function onPreview() {
  if (!code.value.trim()) {
    ElMessage.warning('请输入券码')
    return
  }
  previewing.value = true
  preview.value = null
  result.value = null
  try {
    const res = await api.get('/coupons/preview', { params: { code: code.value.trim() } })
    preview.value = res.data
    if (res.data.status !== 'unused') {
      ElMessage.warning(`当前状态：${couponStatusText(res.data.status)}，不可核销`)
    }
  } catch {
    preview.value = null
  } finally {
    previewing.value = false
  }
}

async function onRedeem() {
  if (!code.value.trim()) {
    ElMessage.warning('请输入券码')
    return
  }
  loading.value = true
  result.value = null
  try {
    const res = await api.post('/coupons/redeem', { code: code.value.trim() })
    result.value = {
      ok: true,
      title: '核销成功',
      sub: `${res.data.coupon.template_name || ''} · 用户 ${res.data.coupon.username || ''}`,
    }
    code.value = ''
    preview.value = null
    ElMessage.success('核销成功')
    loadStats()
  } catch (e) {
    result.value = {
      ok: false,
      title: '核销失败',
      sub: e.response?.data?.detail || e.message,
    }
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)
</script>
