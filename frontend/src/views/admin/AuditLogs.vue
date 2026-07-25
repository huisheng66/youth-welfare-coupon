<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">审计日志</h2>
        <p class="page-desc">发券、审核、核销、入账等敏感操作记录</p>
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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '../../api'
import { formatTime } from '../../utils/format'

const items = ref([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const res = await api.get('/audit-logs', { params: { limit: 100 } })
    items.value = res.data.items
  } finally {
    loading.value = false
  }
})
</script>
