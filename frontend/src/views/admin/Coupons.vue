<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">券列表</h2>
        <p class="page-desc">查看已发放券，可作废未使用券或导出</p>
      </div>
      <div class="filters">
        <el-select v-model="status" clearable placeholder="状态" style="width:140px" @change="load">
          <el-option label="未使用" value="unused" />
          <el-option label="已使用" value="used" />
          <el-option label="已作废" value="void" />
          <el-option label="已过期" value="expired" />
        </el-select>
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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { downloadFile } from '../../api'
import StatusTag from '../../components/StatusTag.vue'
import { couponStatusText, couponStatusType, formatTime } from '../../utils/format'

const items = ref([])
const status = ref()
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await api.get('/coupons/instances', { params: { status: status.value || undefined, limit: 100 } })
    items.value = res.data.items
  } finally {
    loading.value = false
  }
}

async function onExport() {
  const q = status.value ? `?status=${status.value}` : ''
  await downloadFile(`/export/coupons${q}`, 'coupons.csv')
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

onMounted(load)
</script>
