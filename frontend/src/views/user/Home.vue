<template>
  <div>
    <div class="page-card">
      <h2 class="page-title">你好，{{ auth.account?.display_name || auth.account?.username }}</h2>
      <p class="page-desc">完成身份核验后，可获发券或用志愿服务时长兑换指定商家优惠券。</p>

      <el-skeleton v-if="loading" animated :rows="4" />
      <template v-else>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="核验状态">
            <StatusTag :text="statusText" :type="statusType" />
          </el-descriptions-item>
          <el-descriptions-item label="姓名">{{ profile?.real_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="组织">{{ profile?.organization || '-' }}</el-descriptions-item>
          <el-descriptions-item label="可用时长">{{ balance ?? 0 }} 小时</el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="profile?.verify_status === 'draft' || profile?.verify_status === 'rejected'"
          class="section-gap"
          type="warning"
          :closable="false"
          :title="profile?.verify_status === 'rejected' ? '上次申请已驳回，请修改后重新提交' : '请先完善资料并提交核验'"
        />

        <div class="quick-actions">
          <el-button type="primary" @click="$router.push('/user/profile')">资料 / 提交核验</el-button>
          <el-button @click="$router.push('/user/coupons')">我的优惠券</el-button>
          <el-button @click="$router.push('/user/points')">时长兑换</el-button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../../api'
import { useAuth } from '../../auth'
import StatusTag from '../../components/StatusTag.vue'
import { verifyStatusText, verifyStatusType } from '../../utils/format'

const auth = useAuth()
const profile = ref(null)
const balance = ref(null)
const loading = ref(true)
const statusText = computed(() => verifyStatusText(profile.value?.verify_status))
const statusType = computed(() => verifyStatusType(profile.value?.verify_status))

onMounted(async () => {
  try {
    const res = await api.get('/users/me/profile')
    profile.value = res.data
    try {
      const p = await api.get('/points/me')
      balance.value = p.data.balance
    } catch {
      balance.value = 0
    }
  } finally {
    loading.value = false
  }
})
</script>
