<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">本店核销记录</h2>
        <p class="page-desc">仅显示本店相关流水</p>
      </div>
      <div class="filters">
        <el-select v-model="result" clearable placeholder="结果" style="width:120px" @change="onFilter">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-input
          v-model="q"
          clearable
          placeholder="券码"
          style="width:140px"
          @keyup.enter="onFilter"
          @clear="onFilter"
        />
        <el-button type="primary" @click="onFilter">查询</el-button>
        <el-button @click="onExport">导出 CSV</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="items" stripe>
      <template #empty>
        <EmptyState title="暂无核销记录" description="完成一次核销后，成功与失败记录都会出现在这里" />
      </template>
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
import api, { downloadFile } from '../../api'
import StatusTag from '../../components/StatusTag.vue'
import { formatTime, redeemResultType } from '../../utils/format'

const items = ref([])
const loading = ref(false)
const result = ref()
const q = ref('')
const total = ref(0)
const page = ref(1)
const pageSize = 20

async function load() {
  loading.value = true
  try {
    const res = await api.get('/coupons/redemptions', {
      params: {
        result: result.value || undefined,
        q: q.value || undefined,
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

async function onExport() {
  const params = new URLSearchParams()
  if (result.value) params.set('result', result.value)
  const qs = params.toString()
  await downloadFile(`/export/redemptions${qs ? `?${qs}` : ''}`, 'merchant_redemptions.csv')
  ElMessage.success('已开始下载')
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
