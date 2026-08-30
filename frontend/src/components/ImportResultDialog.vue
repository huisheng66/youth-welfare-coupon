<template>
  <el-dialog
    :model-value="modelValue"
    title="导入结果"
    width="640px"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <el-alert
      v-if="result"
      :type="result.failed ? 'warning' : 'success'"
      :closable="false"
      :title="result.message"
    />
    <div v-if="result?.default_password" class="pwd-line">
      初始密码：<code>{{ result.default_password }}</code>
      <span class="muted">（请分发给用户并提醒尽快修改密码）</span>
    </div>
    <div v-if="result?.email_queued" class="muted" style="margin-top:6px">
      已排队向 {{ result.email_queued }} 位用户发送开通邮件（含初始密码）
    </div>
    <el-table
      v-if="result?.errors?.length"
      :data="result.errors"
      size="small"
      stripe
      max-height="280"
      style="margin-top:12px"
    >
      <el-table-column prop="row" label="行号" width="70" />
      <el-table-column prop="identifier" label="标识" min-width="140" show-overflow-tooltip />
      <el-table-column prop="reason" label="失败原因" min-width="200" show-overflow-tooltip />
    </el-table>
    <template #footer>
      <el-button v-if="result?.errors?.length" @click="exportErrors">导出错误明细</el-button>
      <el-button type="primary" @click="emit('update:modelValue', false)">知道了</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  result: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

function exportErrors() {
  const errors = props.result?.errors || []
  if (!errors.length) return
  const rows = [
    ['行号', '标识', '失败原因'],
    ...errors.map((e) => [e.row, e.identifier || '', e.reason || '']),
  ]
  const csv = rows.map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '导入错误明细.csv'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
</script>

<style scoped>
.pwd-line {
  margin-top: 10px;
}
</style>
