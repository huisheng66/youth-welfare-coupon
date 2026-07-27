<template>
  <div>
    <div class="page-card" style="margin-bottom:16px">
      <h2 class="page-title">我的资料</h2>
      <p class="page-desc">保存资料后再提交核验；驳回后可修改并重新提交</p>

      <el-alert
        :type="statusAlertType"
        :closable="false"
        :title="`当前核验状态：${statusText}`"
        :description="statusHint"
        show-icon
        style="margin-bottom:16px"
      />

      <el-form label-width="100px" style="max-width:520px">
        <el-form-item label="昵称"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="用于联系，需唯一" />
        </el-form-item>
        <el-form-item label="真实姓名" required>
          <el-input v-model="form.real_name" placeholder="提交核验前必填" />
        </el-form-item>
        <el-form-item label="学号">
          <el-input v-model="form.student_no" placeholder="请填写学号" />
        </el-form-item>
        <el-form-item label="单位/组织"><el-input v-model="form.organization" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" /></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存资料</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="page-card" style="margin-bottom:16px">
      <h2 class="page-title">提交核验</h2>
      <p class="page-desc">说明身份材料来源，便于管理员审核</p>
      <el-input
        v-model="material"
        type="textarea"
        rows="4"
        placeholder="请说明身份材料或核验说明，例如：社区青年名单第12号"
        :disabled="!canSubmit"
      />
      <div class="quick-actions">
        <el-button type="success" :disabled="!canSubmit" :loading="submitting" @click="submit">
          提交审核
        </el-button>
        <span v-if="verifyStatus === 'pending'" class="muted">审核中，请耐心等待</span>
        <span v-else-if="verifyStatus === 'approved'" class="muted">已通过，可领券 / 兑换</span>
      </div>
    </div>

    <div class="page-card">
      <h2 class="page-title">核验历史</h2>
      <p class="page-desc">含审核备注（驳回原因会显示在此）</p>
      <el-table :data="history" stripe empty-text="暂无提交记录">
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <StatusTag :text="verifyStatusText(row.status)" :type="verifyStatusType(row.status)" />
          </template>
        </el-table-column>
        <el-table-column prop="material_note" label="材料说明" min-width="160" show-overflow-tooltip />
        <el-table-column prop="review_note" label="审核备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="审核时间" width="160">
          <template #default="{ row }">{{ formatTime(row.reviewed_at) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { useAuth } from '../../auth'
import StatusTag from '../../components/StatusTag.vue'
import { formatTime, verifyStatusText, verifyStatusType } from '../../utils/format'

const auth = useAuth()
const form = reactive({
  display_name: '',
  phone: '',
  real_name: '',
  student_no: '',
  organization: '',
  remark: '',
})
const verifyStatus = ref('draft')
const material = ref('')
const history = ref([])
const saving = ref(false)
const submitting = ref(false)

const statusText = computed(() => verifyStatusText(verifyStatus.value))
const canSubmit = computed(() => ['draft', 'rejected'].includes(verifyStatus.value))
const statusAlertType = computed(() => {
  const m = { draft: 'info', pending: 'warning', approved: 'success', rejected: 'error' }
  return m[verifyStatus.value] || 'info'
})
const statusHint = computed(() => {
  const m = {
    draft: '请完善资料并提交核验材料',
    pending: '管理员审核中，暂不可重复提交',
    approved: '已通过，可在「我的优惠券」「时长兑换」使用福利',
    rejected: '请根据审核备注修改资料后重新提交',
  }
  return m[verifyStatus.value] || ''
})

function syncAuth(profile) {
  if (!auth.account) return
  auth.account.display_name = profile.display_name
  auth.account.verify_status = profile.verify_status
  auth.account.phone = profile.phone
  localStorage.setItem('account', JSON.stringify(auth.account))
}

async function load() {
  const [profileRes, histRes] = await Promise.all([
    api.get('/users/me/profile'),
    api.get('/users/me/verifications'),
  ])
  Object.assign(form, {
    display_name: profileRes.data.display_name || '',
    phone: profileRes.data.phone || '',
    real_name: profileRes.data.real_name || '',
    student_no: profileRes.data.student_no || '',
    organization: profileRes.data.organization || '',
    remark: profileRes.data.remark || '',
  })
  verifyStatus.value = profileRes.data.verify_status
  history.value = histRes.data || []
  syncAuth(profileRes.data)
}

async function save() {
  saving.value = true
  try {
    await api.put('/users/me/profile', form)
    ElMessage.success('资料已保存')
    await load()
  } finally {
    saving.value = false
  }
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
  submitting.value = true
  try {
    await api.put('/users/me/profile', form)
    await api.post('/users/me/verifications', { material_note: material.value })
    ElMessage.success('已提交审核')
    material.value = ''
    await load()
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>
