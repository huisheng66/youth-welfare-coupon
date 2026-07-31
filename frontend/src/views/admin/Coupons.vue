<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">券列表</h2>
        <p class="page-desc">查看已发放券，可作废未使用券或导出</p>
      </div>
      <div class="filters">
        <el-select v-model="status" clearable placeholder="状态" style="width:120px" @change="onFilter">
          <el-option label="未使用" value="unused" />
          <el-option label="已使用" value="used" />
          <el-option label="已作废" value="void" />
          <el-option label="已过期" value="expired" />
        </el-select>
        <el-select v-model="merchantId" clearable filterable placeholder="商家" style="width:160px" @change="onFilter">
          <el-option v-for="m in merchants" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-input
          v-model="q"
          clearable
          placeholder="券码 / 用户名"
          style="width:180px"
          @keyup.enter="onFilter"
          @clear="onFilter"
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="发放起"
          end-placeholder="发放止"
          value-format="YYYY-MM-DD"
          style="width:260px"
          @change="onFilter"
        />
        <el-button type="primary" @click="onFilter">查询</el-button>
        <el-button @click="onExport">导出 CSV</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="items" stripe empty-text="暂无优惠券">
      <el-table-column prop="code" label="券码" width="140" />
      <el-table-column prop="username" label="用户" width="120" />
      <el-table-column prop="template_name" label="模板" min-width="120" />
      <el-table-column prop="merchant_name" label="指定商家" min-width="120" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <StatusTag :text="couponStatusText(row.status)" :type="couponStatusType(row.status)" />
        </template>
      </el-table-column>
      <el-table-column label="过期时间" width="160">
        <template #default="{ row }">{{ formatTime(row.expires_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" :disabled="row.status !== 'unused'" @click="voidCoupon(row)">作废</el-button>
        </template>
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
import StatusTag from '../../components/StatusTag.vue'
import { couponStatusText, couponStatusType, formatTime } from '../../utils/format'

const items = ref([])
const merchants = ref([])
const status = ref()
const merchantId = ref()
const q = ref('')
const dateRange = ref(null)
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

async function load() {
  loading.value = true
  try {
    const res = await api.get('/coupons/instances', {
      params: {
        status: status.value || undefined,
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
  if (status.value) params.set('status', status.value)
  if (merchantId.value) params.set('merchant_id', merchantId.value)
  const dr = dateRangeParams(dateRange.value)
  if (dr.date_from) params.set('date_from', dr.date_from)
  if (dr.date_to) params.set('date_to', dr.date_to)
  const qs = params.toString()
  await downloadFile(`/export/coupons${qs ? `?${qs}` : ''}`, 'coupons.csv')
  ElMessage.success('已开始下载')
}

async function voidCoupon(row) {
  const { value } = await ElMessageBox.prompt('请输入作废原因（可选）', '作废优惠券', {
    inputPlaceholder: '原因',
    confirmButtonText: '作废',
    cancelButtonText: '取消',
  }).catch(() => ({ value: null }))
  if (value === null) return
  await api.post(`/coupons/instances/${row.id}/void`, { reason: value || '' })
  ElMessage.success('已作废')
  load()
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
