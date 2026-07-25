<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">商家管理</h2>
        <p class="page-desc">维护合作门店；券模板与核销均按商家隔离</p>
      </div>
      <el-button type="primary" @click="openCreate">新增商家</el-button>
    </div>
    <el-table v-loading="loading" :data="items" stripe empty-text="暂无商家">
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="contact_name" label="联系人" width="120" />
      <el-table-column prop="contact_phone" label="电话" width="140" />
      <el-table-column prop="address" label="地址" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <StatusTag :text="row.is_active ? '启用' : '停用'" :type="row.is_active ? 'success' : 'info'" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" :title="form.id ? '编辑商家' : '新增商家'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="form.contact_name" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="form.contact_phone" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" /></el-form-item>
        <el-form-item label="简介"><el-input v-model="form.description" type="textarea" /></el-form-item>
        <el-form-item v-if="form.id" label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存商家</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import StatusTag from '../../components/StatusTag.vue'

const items = ref([])
const visible = ref(false)
const loading = ref(false)
const form = reactive({
  id: '',
  name: '',
  contact_name: '',
  contact_phone: '',
  address: '',
  description: '',
  is_active: true,
})

async function load() {
  loading.value = true
  try {
    const res = await api.get('/merchants', { params: { limit: 100 } })
    items.value = res.data.items
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    id: '', name: '', contact_name: '', contact_phone: '', address: '', description: '', is_active: true,
  })
  visible.value = true
}

function openEdit(row) {
  Object.assign(form, row)
  visible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写商家名称')
    return
  }
  if (form.id) {
    await api.put(`/merchants/${form.id}`, {
      name: form.name,
      contact_name: form.contact_name,
      contact_phone: form.contact_phone,
      address: form.address,
      description: form.description,
      is_active: form.is_active,
    })
  } else {
    await api.post('/merchants', {
      name: form.name,
      contact_name: form.contact_name,
      contact_phone: form.contact_phone,
      address: form.address,
      description: form.description,
    })
  }
  ElMessage.success('已保存')
  visible.value = false
  load()
}

onMounted(load)
</script>
