<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">券模板</h2>
        <p class="page-desc">每张模板绑定指定商家；兑换时长大于 0 时用户可用志愿时长兑换</p>
      </div>
      <div class="filters">
        <el-select v-model="merchantFilter" clearable filterable placeholder="商家" style="width:160px" @change="load">
          <el-option v-for="m in merchants" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-select v-model="activeFilter" clearable placeholder="状态" style="width:120px" @change="load">
          <el-option label="仅启用" :value="true" />
        </el-select>
        <el-button type="primary" @click="openCreate">新建模板</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="items" stripe>
      <template #empty>
        <EmptyState title="暂无模板" description="创建模板后即可为已通过用户发券，或开放时长兑换">
          <el-button type="primary" @click="openCreate">新建模板</el-button>
        </EmptyState>
      </template>
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column prop="merchant_name" label="指定商家" min-width="120" />
      <el-table-column prop="valid_days" label="有效天数" width="100" />
      <el-table-column label="兑换时长" width="120">
        <template #default="{ row }">
          <span v-if="Number(row.cost_points) > 0">{{ formatHours(row.cost_points) }} 小时</span>
          <span v-else class="muted">不可兑换</span>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="140" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <StatusTag :text="row.is_active ? '启用' : '停用'" :type="row.is_active ? 'success' : 'info'" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="primary" @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" :title="form.id ? '编辑券模板' : '新建券模板'" width="520px">
      <el-form label-width="110px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item v-if="!form.id" label="指定商家">
          <el-select v-model="form.merchant_id" style="width:100%" filterable>
            <el-option v-for="m in merchants" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="有效天数"><el-input-number v-model="form.valid_days" :min="1" :max="3650" /></el-form-item>
        <el-form-item label="兑换时长">
          <el-input-number
            v-model="form.cost_points"
            :min="0"
            :max="100000"
            :step="0.01"
            :precision="2"
          />
          <span class="muted" style="margin-left:8px">小时，支持两位小数；0 表示不可兑换</span>
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存模板</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import api from '../../api'
import EmptyState from '../../components/EmptyState.vue'
import StatusTag from '../../components/StatusTag.vue'
import { formatHours } from '../../utils/format'

const items = ref([])
const merchants = ref([])
const visible = ref(false)
const loading = ref(false)
const merchantFilter = ref()
const activeFilter = ref()
const form = reactive({
  id: '',
  name: '',
  merchant_id: '',
  valid_days: 30,
  cost_points: 0,
  description: '',
})

async function load() {
  loading.value = true
  try {
    const [t, m] = await Promise.all([
      api.get('/coupons/templates', {
        params: {
          limit: 100,
          merchant_id: merchantFilter.value || undefined,
          active_only: activeFilter.value === true ? true : undefined,
        },
      }),
      api.get('/merchants', { params: { active_only: true, limit: 100 } }),
    ])
    items.value = t.data.items
    merchants.value = m.data.items
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    id: '',
    name: '',
    merchant_id: merchants.value[0]?.id || '',
    valid_days: 30,
    cost_points: 2,
    description: '',
  })
  visible.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    merchant_id: row.merchant_id,
    valid_days: row.valid_days,
    cost_points: row.cost_points || 0,
    description: row.description,
  })
  visible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (!form.id && !form.merchant_id) {
    ElMessage.warning('必须选择指定商家')
    return
  }
  if (form.id) {
    await api.put(`/coupons/templates/${form.id}`, {
      name: form.name,
      valid_days: form.valid_days,
      cost_points: form.cost_points,
      description: form.description,
    })
  } else {
    await api.post('/coupons/templates', {
      name: form.name,
      merchant_id: form.merchant_id,
      valid_days: form.valid_days,
      cost_points: form.cost_points,
      description: form.description,
    })
  }
  ElMessage.success('已保存')
  visible.value = false
  load()
}

async function toggle(row) {
  const next = !row.is_active
  try {
    await ElMessageBox.confirm(
      next ? `确认启用模板「${row.name}」？` : `确认停用模板「${row.name}」？停用后不可新发/兑换该券。`,
      '提示',
      { type: 'warning' },
    )
  } catch {
    return
  }
  await api.put(`/coupons/templates/${row.id}`, { is_active: next })
  ElMessage.success('已更新')
  load()
}

onMounted(load)
</script>
