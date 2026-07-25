<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">本店核销记录</h2>
        <p class="page-desc">仅显示本店相关流水</p>
      </div>
      <el-button type="primary" @click="onExport">导出 CSV</el-button>
    </div>
    <el-table v-loading="loading" :data="items" stripe empty-text="暂无核销记录">
      <el-table-column prop="code" label="券码" min-width="140" show-overflow-tooltip />
      <el-table-column prop="username" label="用户" width="120" />
      <el-table-column label="结果" width="100">
        <template #default="{ row }">
          <StatusTag
            :text="row.result === 'success' ? '成功' : '失败'"
            :type="redeemResultType(row.result)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="message" label="说明" min-width="140" />
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api, { downloadFile } from '../../api'
import StatusTag from '../../components/StatusTag.vue'
import { formatTime, redeemResultType } from '../../utils/format'

const items = ref([])
const loading = ref(false)

async function onExport() {
  await downloadFile('/export/redemptions', 'merchant_redemptions.csv')
  ElMessage.success('已开始下载')
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await api.get('/coupons/redemptions', { params: { limit: 100 } })
    items.value = res.data.items
  } finally {
    loading.value = false
  }
})
</script>
