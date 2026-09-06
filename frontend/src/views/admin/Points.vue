<template>
  <div>
    <div class="page-card" style="margin-bottom:16px">
      <div class="page-header">
        <div>
          <h2 class="page-title">志愿服务时长</h2>
          <p class="page-desc">为正入账、为负扣减；可对多名已通过用户批量调整</p>
        </div>
        <div class="filters">
          <el-button type="primary" plain @click="openImportPoints">导入时长</el-button>
        </div>
      </div>

      <el-form label-width="100px" style="max-width:560px" @submit.prevent="grant">
        <el-form-item label="用户">
          <el-select
            v-model="form.user_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            style="width:100%"
            placeholder="选择已通过用户（可多选）"
          >
            <el-option
              v-for="u in users"
              :key="u.id"
              :label="`${u.username} / ${u.real_name || u.display_name}`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="时长(小时)">
          <el-input-number
            v-model="form.amount"
            :min="-1000"
            :max="1000"
            :step="0.01"
            :precision="2"
          />
          <span class="muted" style="margin-left:8px">支持两位小数；正数入账，负数扣减</span>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.reason" placeholder="如：社区志愿服务 2026-07-26" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">确认调整</el-button>
          <el-button @click="queryBalance" :disabled="form.user_ids.length !== 1">查询余额</el-button>
          <el-button @click="onExportLedger">导出流水</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="balanceText"
        type="success"
        :closable="false"
        :title="balanceText"
        style="max-width:560px"
      />
    </div>

    <div class="page-card">
      <div class="page-header">
        <div>
          <h2 class="page-title">最近时长流水</h2>
          <p class="page-desc">入账、扣减、兑换等变动</p>
        </div>
        <el-button @click="loadLedger" :loading="ledgerLoading">刷新</el-button>
      </div>
      <el-table v-loading="ledgerLoading" :data="ledger" stripe>
        <template #empty>
          <EmptyState title="暂无流水" description="入账、扣减、兑换变动都会记录在这里" />
        </template>
        <el-table-column label="用户" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ usernameOf(row.user_id) }}</template>
        </el-table-column>
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
        <el-table-column prop="reason" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column prop="ref_type" label="类型" width="100" />
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <span class="muted">共 {{ ledgerTotal }} 条</span>
        <el-pagination
          v-model:current-page="ledgerPage"
          layout="prev, pager, next"
          :page-size="ledgerPageSize"
          :total="ledgerTotal"
          @current-change="loadLedger"
        />
      </div>
    </div>

    <ImportWizard v-model="importPointsVisible" kind="points" @done="onImported" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import api, { downloadFile } from '../../api'
import ImportWizard from '../../components/ImportWizard.vue'
import { formatHours, formatTime } from '../../utils/format'
import { idempotencyHeader, newIdempotencyKey } from '../../utils/idempotency'

const users = ref([])
const loading = ref(false)
const balanceText = ref('')
const form = reactive({ user_ids: [], amount: 2, reason: '志愿服务时长入账' })
// 同一调整/导入意图复用同一幂等键；成功后重置，重新发起的独立业务用新 key
let grantKey = ''
const ledger = ref([])
const ledgerLoading = ref(false)
const ledgerTotal = ref(0)
const ledgerPage = ref(1)
const ledgerPageSize = 20
const userMap = ref({})

function usernameOf(id) {
  return userMap.value[id] || id.slice(0, 8)
}

async function loadUsers() {
  const res = await api.get('/users', { params: { verify_status: 'approved', limit: 100 } })
  users.value = res.data.items
  const map = {}
  for (const u of users.value) {
    map[u.id] = `${u.username}${u.real_name ? ' / ' + u.real_name : ''}`
  }
  userMap.value = map
}

async function queryBalance() {
  if (form.user_ids.length !== 1) return
  const res = await api.get(`/points/users/${form.user_ids[0]}`)
  balanceText.value = `当前余额：${formatHours(res.data.balance)} 小时`
}

async function grant() {
  if (!form.user_ids.length) {
    ElMessage.warning('请选择用户')
    return
  }
  if (!form.amount || form.amount === 0) {
    ElMessage.warning('请填写非零时长')
    return
  }
  if (!form.reason.trim()) {
    ElMessage.warning('请填写说明')
    return
  }
  const amt = Math.round(Number(form.amount) * 100) / 100
  const sign = amt > 0 ? `+${formatHours(amt)}` : formatHours(amt)
  const names = form.user_ids
    .slice(0, 5)
    .map((id) => userMap.value[id]?.split(' / ')[0] || id.slice(0, 8))
    .join('、')
  const more = form.user_ids.length > 5 ? ` 等 ${form.user_ids.length} 人` : ''
  try {
    await ElMessageBox.confirm(
      `对 ${names}${more} 调整 ${sign} 小时，说明「${form.reason.trim()}」，确认？`,
      '时长调整确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  loading.value = true
  // 同一调整意图复用同一幂等键：超时/失败后重试由服务端重放，不重复入账
  if (!grantKey) grantKey = newIdempotencyKey()
  try {
    if (form.user_ids.length === 1) {
      const res = await api.post(
        '/points/grant',
        {
          user_id: form.user_ids[0],
          amount: amt,
          reason: form.reason,
        },
        { headers: idempotencyHeader(grantKey) },
      )
      balanceText.value = `调整成功，当前余额：${formatHours(res.data.balance)} 小时`
      ElMessage.success('已调整')
    } else {
      const res = await api.post(
        '/points/grant-batch',
        {
          user_ids: form.user_ids,
          amount: amt,
          reason: form.reason,
        },
        { headers: idempotencyHeader(grantKey) },
      )
      balanceText.value = res.data.message
      ElMessage.success(res.data.message)
    }
    grantKey = ''
    loadLedger()
  } finally {
    loading.value = false
  }
}

async function loadLedger() {
  ledgerLoading.value = true
  try {
    const res = await api.get('/points/ledger', {
      params: { skip: (ledgerPage.value - 1) * ledgerPageSize, limit: ledgerPageSize },
    })
    ledger.value = res.data.items
    ledgerTotal.value = res.data.total
  } finally {
    ledgerLoading.value = false
  }
}

async function onExportLedger() {
  await downloadFile('/export/points-ledger', 'points_ledger.csv')
  ElMessage.success('已开始下载')
}

// ---- 统一导入（T14：预检 → 确认执行 → 逐行结果，见 ImportWizard）----
const importPointsVisible = ref(false)

function openImportPoints() {
  importPointsVisible.value = true
}

function onImported() {
  loadLedger()
  loadUsers()
}

onMounted(async () => {
  await loadUsers()
  loadLedger()
})
</script>

<style scoped>
.pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}
</style>
