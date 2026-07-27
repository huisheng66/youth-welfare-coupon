<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">审计日志</h2>
        <p class="page-desc">发券、审核、核销、入账等敏感操作记录</p>
      </div>
      <div class="filters">
        <el-select v-model="action" clearable filterable allow-create placeholder="动作" style="width:180px" @change="onFilter">
          <el-option v-for="a in actionOptions" :key="a" :label="a" :value="a" />
        </el-select>
        <el-input
          v-model="q"
          clearable
          placeholder="关键字"
          style="width:180px"
          @keyup.enter="onFilter"
          @clear="onFilter"
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="起"
          end-placeholder="止"
          value-format="YYYY-MM-DD"
          style="width:260px"
          @change="onFilter"
        />
        <el-button type="primary" @click="onFilter">查询</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="items" stripe empty-text="暂无审计记录">
      <el-table-column prop="actor_name" label="操作人" width="120" />
      <el-table-column prop="action" label="动作" width="160" />
      <el-table-column prop="target_type" label="对象类型" width="110" />
      <el-table-column prop="target_id" label="对象ID" min-width="160" show-overflow-tooltip />
      <el-table-column prop="detail" label="详情" min-width="160" show-overflow-tooltip />
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <span class="muted">共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        layout="prev, pager, next"
        :page-size="pageSize"
        :total="total"
        @current-change="load"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api, { dateRangeParams } from '../../api'
import { formatTime } from '../../utils/format'

const items = ref([])
const loading = ref(false)
const action = ref()
const q = ref('')
const dateRange = ref(null)
const total = ref(0)
const page = ref(1)
const pageSize = 50
const actionOptions = [
  'user_register',
  'submit_verification',
  'approve_verification',
  'reject_verification',
  'create_template',
  'update_template',
  'issue_coupon',
  'void_coupon',
  'redeem_coupon',
  'grant_points',
  'adjust_points',
  'change_password',
  'reset_password',
  'set_account_active',
  'create_merchant',
  'update_merchant',
  'create_merchant_account',
  'create_issue_admin',
]

async function load() {
  loading.value = true
  try {
    const res = await api.get('/audit-logs', {
      params: {
        action: action.value || undefined,
        q: q.value || undefined,
        ...dateRangeParams(dateRange.value),
        skip: (page.value - 1) * pageSize,
        limit: pageSize,
      },
    })
    items.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

function onFilter() {
  page.value = 1
  load()
}

onMounted(load)
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
