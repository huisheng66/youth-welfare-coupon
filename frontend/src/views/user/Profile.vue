<template>
  <div class="page-card">
    <h2 class="page-title">我的资料</h2>
    <p class="page-desc">保存资料后再提交核验；驳回后可修改并重新提交</p>
    <el-form label-width="100px" style="max-width:520px">
      <el-form-item label="昵称"><el-input v-model="form.display_name" /></el-form-item>
      <el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item>
      <el-form-item label="真实姓名"><el-input v-model="form.real_name" /></el-form-item>
      <el-form-item label="证件脱敏"><el-input v-model="form.id_number_masked" placeholder="如 110***********1234" /></el-form-item>
      <el-form-item label="单位/组织"><el-input v-model="form.organization" /></el-form-item>
      <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" /></el-form-item>
      <el-form-item>
        <el-button type="primary" @click="save">保存资料</el-button>
      </el-form-item>
    </el-form>

    <el-divider />
    <h3>提交核验</h3>
    <p class="muted">当前状态：{{ statusText }}</p>
    <el-alert
      v-if="verifyStatus === 'rejected'"
      type="error"
      :closable="false"
      title="上次申请已驳回，请修改资料后重新提交"
      style="margin-bottom:12px"
    />
    <el-input
      v-model="material"
      type="textarea"
      rows="4"
      placeholder="请说明身份材料或核验说明，例如：社区青年名单第12号"
      :disabled="!canSubmit"
    />
    <el-button style="margin-top:12px" type="success" :disabled="!canSubmit" @click="submit">提交审核</el-button>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const form = reactive({
  display_name: '',
  phone: '',
  real_name: '',
  id_number_masked: '',
  organization: '',
  remark: '',
})
const verifyStatus = ref('draft')
const material = ref('')
const statusText = computed(() => ({ draft: '未提交', pending: '审核中', approved: '已通过', rejected: '已驳回' }[verifyStatus.value]))
const canSubmit = computed(() => ['draft', 'rejected'].includes(verifyStatus.value))

async function load() {
  const res = await api.get('/users/me/profile')
  Object.assign(form, {
    display_name: res.data.display_name || '',
    phone: res.data.phone || '',
    real_name: res.data.real_name || '',
    id_number_masked: res.data.id_number_masked || '',
    organization: res.data.organization || '',
    remark: res.data.remark || '',
  })
  verifyStatus.value = res.data.verify_status
}

async function save() {
  await api.put('/users/me/profile', form)
  ElMessage.success('资料已保存')
  load()
}

async function submit() {
  if (!form.real_name.trim()) {
    ElMessage.warning('请先填写真实姓名并保存')
    return
  }
  if (!material.value.trim()) {
    ElMessage.warning('请填写核验说明')
    return
  }
  await api.put('/users/me/profile', form)
  await api.post('/users/me/verifications', { material_note: material.value })
  ElMessage.success('已提交审核')
  material.value = ''
  load()
}

onMounted(load)
</script>
