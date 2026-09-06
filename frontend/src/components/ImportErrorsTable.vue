<template>
  <el-table :data="errors" size="small" max-height="300" border>
    <el-table-column prop="row" label="行号" width="70" />
    <el-table-column prop="identifier" label="标识" min-width="120" show-overflow-tooltip />
    <el-table-column v-if="showStatus" label="状态" width="110">
      <template #default="{ row }">
        <el-tag :type="row.status === 'precheck_failed' ? 'info' : 'danger'" effect="light" size="small">
          {{ statusText(row.status) }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
  </el-table>
</template>

<script setup>
defineProps({
  errors: { type: Array, default: () => [] },
  showStatus: { type: Boolean, default: false },
})

function statusText(status) {
  return (
    {
      precheck_failed: '预检失败',
      failed: '执行失败',
      pending: '待执行',
      running: '执行中',
      ok: '成功',
    }[status] || status
  )
}
</script>
