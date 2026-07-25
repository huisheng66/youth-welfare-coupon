<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">志愿服务时长</h2>
        <p class="page-desc">为已核验用户入账时长（小时），用户可在前端自助兑换优惠券</p>
      </div>
    </div>

    <el-form label-width="100px" style="max-width:520px" @submit.prevent="grant">
      <el-form-item label="用户">
        <el-select v-model="form.user_id" filterable style="width:100%" placeholder="选择已通过用户">
          <el-option
            v-for="u in users"
            :key="u.id"
            :label="`${u.username} / ${u.real_name || u.display_name}`"
            :value="u.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="时长(小时)">
        <el-input-number v-model="form.amount" :min="1" :max="1000" />
      </el-form-item>
      <el-form-item label="说明">
        <el-input v-model="form.reason" placeholder="如：社区志愿服务 2026-07-26" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading">确认入账</el-button>
        <el-button @click="queryBalance" :disabled="!form.user_id">查询余额</el-button>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="balanceText"
      type="success"
      :closable="false"
      :title="balanceText"
      style="max-width:520px"
    />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const users = ref([])
const loading = ref(false)
const balanceText = ref('')
const form = reactive({ user_id: '', amount: 2, reason: '志愿服务时长入账' })

async function loadUsers() {
  const res = await api.get('/users', { params: { verify_status: 'approved', limit: 100 } })
  users.value = res.data.items
  if (!form.user_id && users.value[0]) form.user_id = users.value[0].id
}

async function queryBalance() {
  const res = await api.get(`/points/users/${form.user_id}`)
  balanceText.value = `当前余额：${res.data.balance} 小时`
}

async function grant() {
  if (!form.user_id) {
    ElMessage.warning('请选择用户')
    return
  }
  if (!form.reason.trim()) {
    ElMessage.warning('请填写入账说明')
    return
  }
  loading.value = true
  try {
    const res = await api.post('/points/grant', form)
    balanceText.value = `入账成功，当前余额：${res.data.balance} 小时`
    ElMessage.success('已入账')
  } finally {
    loading.value = false
  }
}

onMounted(loadUsers)
</script>
