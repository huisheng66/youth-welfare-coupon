<template>
  <div class="page-card">
    <h2 class="page-title">账号管理</h2>
    <el-row :gutter="16">
      <el-col :span="12">
        <h3>创建发券管理员</h3>
        <el-form label-width="80px" @submit.prevent="createIssuer">
          <el-form-item label="用户名"><el-input v-model="issuer.username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="issuer.password" type="password" show-password /></el-form-item>
          <el-form-item label="昵称"><el-input v-model="issuer.display_name" /></el-form-item>
          <el-button type="primary" native-type="submit">创建</el-button>
        </el-form>
      </el-col>
      <el-col :span="12">
        <h3>创建商家账号</h3>
        <el-form label-width="80px" @submit.prevent="createMerchantAcc">
          <el-form-item label="用户名"><el-input v-model="merchantAcc.username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="merchantAcc.password" type="password" show-password /></el-form-item>
          <el-form-item label="昵称"><el-input v-model="merchantAcc.display_name" /></el-form-item>
          <el-form-item label="商家">
            <el-select v-model="merchantAcc.merchant_id" style="width:100%" filterable>
              <el-option v-for="m in merchants" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>
          </el-form-item>
          <el-button type="primary" native-type="submit">创建</el-button>
        </el-form>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const merchants = ref([])
const issuer = reactive({ username: '', password: '', display_name: '' })
const merchantAcc = reactive({ username: '', password: '', display_name: '', merchant_id: '' })

async function createIssuer() {
  await api.post('/auth/issue-admins', issuer)
  ElMessage.success('发券管理员已创建')
  Object.assign(issuer, { username: '', password: '', display_name: '' })
}

async function createMerchantAcc() {
  await api.post('/auth/merchant-accounts', merchantAcc)
  ElMessage.success('商家账号已创建')
  Object.assign(merchantAcc, { username: '', password: '', display_name: '', merchant_id: merchants.value[0]?.id || '' })
}

onMounted(async () => {
  const res = await api.get('/merchants', { params: { limit: 100 } })
  merchants.value = res.data.items
  merchantAcc.merchant_id = merchants.value[0]?.id || ''
})
</script>
