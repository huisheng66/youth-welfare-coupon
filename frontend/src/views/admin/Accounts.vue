<template>
  <div>
    <div class="page-card" style="margin-bottom:16px">
      <div class="page-header">
        <div>
          <h2 class="page-title">账号列表</h2>
          <p class="page-desc">查看、重置密码、启停账号（超级管理员）</p>
        </div>
        <div class="filters">
          <el-select v-model="role" clearable placeholder="角色" style="width:140px" @change="load">
            <el-option label="超级管理员" value="super_admin" />
            <el-option label="发券管理员" value="issue_admin" />
            <el-option label="商家" value="merchant" />
            <el-option label="青年用户" value="user" />
          </el-select>
          <el-input
            v-model="q"
            clearable
            placeholder="用户名 / 昵称 / 手机"
            style="width:200px"
            @keyup.enter="load"
          />
          <el-button type="primary" @click="load">查询</el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="items" stripe empty-text="暂无账号">
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip />
        <el-table-column prop="display_name" label="昵称" min-width="120" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">{{ roleLabel(row.role) }}</template>
        </el-table-column>
        <el-table-column prop="phone" label="手机" width="130" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <StatusTag :text="row.is_active ? '正常' : '停用'" :type="row.is_active ? 'success' : 'danger'" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openReset(row)">重置密码</el-button>
            <el-button
              link
              :type="row.is_active ? 'danger' : 'success'"
              @click="toggleActive(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="muted" style="margin-top:10px">共 {{ total }} 个账号</div>
    </div>

    <div class="page-card">
      <h2 class="page-title">创建账号</h2>
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <h3 class="sub-title">发券管理员</h3>
          <el-form label-width="80px" @submit.prevent="createIssuer">
            <el-form-item label="用户名"><el-input v-model="issuer.username" /></el-form-item>
            <el-form-item label="密码"><el-input v-model="issuer.password" type="password" show-password /></el-form-item>
            <el-form-item label="昵称"><el-input v-model="issuer.display_name" /></el-form-item>
            <el-button type="primary" native-type="submit">创建</el-button>
          </el-form>
        </el-col>
        <el-col :xs="24" :md="12">
          <h3 class="sub-title">商家账号</h3>
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

    <el-dialog v-model="resetVisible" title="重置密码" width="400px" @closed="resetPwd = ''">
      <p class="muted" style="margin-top:0">账号：{{ resetTarget?.username }}</p>
      <el-input v-model="resetPwd" type="password" show-password placeholder="新密码（至少 8 位）" />
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="confirmReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'
import StatusTag from '../../components/StatusTag.vue'
import { roleLabel } from '../../utils/format'

const merchants = ref([])
const items = ref([])
const total = ref(0)
const loading = ref(false)
const role = ref('')
const q = ref('')
const issuer = reactive({ username: '', password: '', display_name: '' })
const merchantAcc = reactive({ username: '', password: '', display_name: '', merchant_id: '' })

const resetVisible = ref(false)
const resetTarget = ref(null)
const resetPwd = ref('')
const resetting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await api.get('/auth/accounts', {
      params: {
        role: role.value || undefined,
        q: q.value || undefined,
        limit: 100,
      },
    })
    items.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

async function createIssuer() {
  await api.post('/auth/issue-admins', issuer)
  ElMessage.success('发券管理员已创建')
  Object.assign(issuer, { username: '', password: '', display_name: '' })
  load()
}

async function createMerchantAcc() {
  await api.post('/auth/merchant-accounts', merchantAcc)
  ElMessage.success('商家账号已创建')
  Object.assign(merchantAcc, {
    username: '',
    password: '',
    display_name: '',
    merchant_id: merchants.value[0]?.id || '',
  })
  load()
}

function openReset(row) {
  resetTarget.value = row
  resetPwd.value = ''
  resetVisible.value = true
}

async function confirmReset() {
  if (!resetPwd.value || resetPwd.value.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  resetting.value = true
  try {
    await api.post(`/auth/accounts/${resetTarget.value.id}/reset-password`, {
      new_password: resetPwd.value,
    })
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } finally {
    resetting.value = false
  }
}

async function toggleActive(row) {
  const next = !row.is_active
  await ElMessageBox.confirm(
    next ? `确认启用账号「${row.username}」？` : `确认停用账号「${row.username}」？停用后将无法登录。`,
    '提示',
    { type: 'warning' },
  )
  await api.post(`/auth/accounts/${row.id}/set-active`, { is_active: next })
  ElMessage.success(next ? '已启用' : '已停用')
  load()
}

onMounted(async () => {
  const res = await api.get('/merchants', { params: { limit: 100 } })
  merchants.value = res.data.items
  merchantAcc.merchant_id = merchants.value[0]?.id || ''
  load()
})
</script>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.sub-title {
  margin: 0 0 12px;
  font-size: 1rem;
  font-weight: 600;
}
</style>
