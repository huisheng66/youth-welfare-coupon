<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">核销流水</h2>
        <p class="page-desc">成功与失败记录均可追溯，支持筛选导出 CSV</p>
      </div>
      <div class="filters">
        <el-select v-model="result" clearable placeholder="结果" style="width:120px" @change="onFilter">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-select v-model="merchantId" clearable filterable placeholder="商家" style="width:160px" @change="onFilter">
          <el-option v-for="m in merchants" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-input
          v-model="q"
          clearable
          placeholder="券码 / 说明"
          style="width:160px"
          @keyup.enter="onFilter"
          @clear="onFilter"
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="核销起"
          end-placeholder="核销止"
          value-format="YYYY-MM-DD"
          style="width:260px"
          @change="onFilter"
        />
        <el-button type="primary" @click="onFilter">查询</el-button>
        <el-button @click="onExport">导出 CSV</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="items" stripe>
      <template #empty>
        <EmptyState title="暂无核销记录" description="核销成功与失败记录都会出现在这里；当前筛选条件下暂无数据" />
      </template>
      <el-table-column prop="code" label="券码" min-width="140" show-overflow-tooltip />
      <el-table-column prop="merchant_name" label="商家" min-width="120" />
      <el-table-column prop="username" label="用户" width="110" />
      <el-table-column prop="operator_name" label="操作员" width="110" />
      <el-table-column label="结果" width="100">
        <template #default="{ row }">
          <StatusTag
            :text="row.result === 'success' ? '成功' : '失败'"
            :type="redeemResultType(row.result)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="message" label="说明" min-width="140" show-overflow-tooltip />
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <span class="muted">共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        layout="prev, pager, next, sizes"
        :total="total"
        :page-sizes="[20, 50, 100]"
        @current-change="load"
        @size-change="onFilter"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api, { dateRangeParams, downloadFile } from '../../api'
import EmptyState from '../../components/EmptyState.vue'
import StatusTag from '../../components/StatusTag.vue'
import { formatTime, redeemResultType } from '../../utils/format'

const items = ref([])
const merchants = ref([])
const loading = ref(false)
const result = ref()
const merchantId = ref()
const q = ref('')
const dateRange = ref(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

async function load() {
  loading.value = true
  try {
    const res = await api.get('/coupons/redemptions', {
      params: {
        result: result.value || undefined,
        merchant_id: merchantId.value || undefined,
        q: q.value || undefined,
        ...dateRangeParams(dateRange.value),
        skip: (page.value - 1) * pageSize.value,
        limit: pageSize.value,
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

async function onExport() {
  const params = new URLSearchParams()
  if (result.value) params.set('result', result.value)
  if (merchantId.value) params.set('merchant_id', merchantId.value)
  const dr = dateRangeParams(dateRange.value)
  if (dr.date_from) params.set('date_from', dr.date_from)
  if (dr.date_to) params.set('date_to', dr.date_to)
  const qs = params.toString()
  await downloadFile(`/export/redemptions${qs ? `?${qs}` : ''}`, 'redemptions.csv')
  ElMessage.success('已开始下载')
}

onMounted(async () => {
  const m = await api.get('/merchants', { params: { limit: 100 } })
  merchants.value = m.data.items
  load()
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
