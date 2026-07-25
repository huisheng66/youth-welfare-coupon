<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">用户核验</h2>
        <p class="page-desc">审核身份材料，通过后可发券或入账志愿时长</p>
      </div>
      <div class="filters">
        <el-select v-model="status" clearable placeholder="核验状态" style="width:140px" @change="load">
          <el-option label="未提交" value="draft" />
          <el-option label="待审核" value="pending" />
          <el-option label="已通过" value="approved" />
          <el-option label="已驳回" value="rejected" />
        </el-select>
        <el-input v-model="q" placeholder="用户名 / 昵称 / 手机" clearable style="width:200px" @keyup.enter="load" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button type="success" :disabled="!selectedApproved.length" @click="openBatchIssue">
          批量发券 ({{ selectedApproved.length }})
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="pendingList.length"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 12px"
      :title="`有 ${pendingList.length} 条待审核申请，请优先处理`"
    />

    <el-table v-loading="loading" :data="items" stripe empty-text="暂无用户" @selection-change="onSelect">
      <el-table-column type="selection" width="48" :selectable="(row) => row.verify_status === 'approved'" />
      <el-table-column prop="username" label="用户名" width="120" />
      <el-table-column prop="real_name" label="姓名" width="100" />
      <el-table-column prop="phone" label="手机" width="130" />
      <el-table-column prop="organization" label="单位/组织" min-width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <StatusTag :text="verifyStatusText(row.verify_status)" :type="verifyStatusType(row.verify_status)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <el-button link type="primary" @click="openIssue(row)" :disabled="row.verify_status !== 'approved'">发券</el-button>
          <el-button link type="success" @click="openReview(row)" :disabled="row.verify_status !== 'pending'">审核</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="detailVisible" title="用户详情" width="560px">
      <el-descriptions v-if="current" :column="1" border>
        <el-descriptions-item label="用户名">{{ current.username }}</el-descriptions-item>
        <el-descriptions-item label="姓名">{{ current.real_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="手机">{{ current.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="证件脱敏">{{ current.id_number_masked || '-' }}</el-descriptions-item>
        <el-descriptions-item label="组织">{{ current.organization || '-' }}</el-descriptions-item>
        <el-descriptions-item label="备注">{{ current.remark || '-' }}</el-descriptions-item>
        <el-descriptions-item label="核验状态">
          <StatusTag :text="verifyStatusText(current.verify_status)" :type="verifyStatusType(current.verify_status)" />
        </el-descriptions-item>
        <el-descriptions-item label="最近材料">{{ current.latest_material_note || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog v-model="reviewVisible" title="审核用户" width="520px">
      <el-descriptions :column="1" border style="margin-bottom:12px">
        <el-descriptions-item label="用户">{{ current?.username }} / {{ current?.real_name }}</el-descriptions-item>
        <el-descriptions-item label="组织">{{ current?.organization || '-' }}</el-descriptions-item>
        <el-descriptions-item label="核验材料">{{ reviewMaterial || '-' }}</el-descriptions-item>
      </el-descriptions>
      <el-input v-model="reviewNote" type="textarea" rows="3" placeholder="审核备注（驳回时建议填写原因）" />
      <template #footer>
        <el-button @click="doReview(false)">驳回</el-button>
        <el-button type="primary" @click="doReview(true)">通过</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="issueVisible" title="发放优惠券" width="480px">
      <el-form label-width="90px">
        <el-form-item label="用户">{{ current?.username }}</el-form-item>
        <el-form-item label="券模板">
          <el-select v-model="issueForm.template_id" style="width:100%" filterable>
            <el-option
              v-for="t in templates"
              :key="t.id"
              :label="`${t.name}（${t.merchant_name}）`"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="issueForm.quantity" :min="1" :max="50" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="issueVisible = false">取消</el-button>
        <el-button type="primary" @click="doIssue">确认发券</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchIssueVisible" title="批量发券" width="520px">
      <p class="muted">已选已通过用户 {{ selectedApproved.length }} 人</p>
      <el-form label-width="90px" style="margin-top:12px">
        <el-form-item label="券模板">
          <el-select v-model="issueForm.template_id" style="width:100%" filterable>
            <el-option
              v-for="t in templates"
              :key="t.id"
              :label="`${t.name}（${t.merchant_name}）`"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="每人数量">
          <el-input-number v-model="issueForm.quantity" :min="1" :max="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchIssueVisible = false">取消</el-button>
        <el-button type="primary" @click="doBatchIssue">确认批量发券</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import StatusTag from '../../components/StatusTag.vue'
import { verifyStatusText, verifyStatusType } from '../../utils/format'

const items = ref([])
const loading = ref(false)
const status = ref()
const q = ref('')
const reviewVisible = ref(false)
const issueVisible = ref(false)
const batchIssueVisible = ref(false)
const detailVisible = ref(false)
const current = ref(null)
const reviewNote = ref('')
const reviewMaterial = ref('')
const templates = ref([])
const issueForm = reactive({ template_id: '', quantity: 1 })
const pendingMap = ref({})
const pendingList = ref([])
const selected = ref([])
const selectedApproved = computed(() => selected.value.filter((r) => r.verify_status === 'approved'))

function onSelect(rows) {
  selected.value = rows
}

async function load() {
  loading.value = true
  try {
    const [usersRes, pendingRes] = await Promise.all([
      api.get('/users', { params: { verify_status: status.value || undefined, q: q.value || undefined, limit: 100 } }),
      api.get('/users/pending-verifications'),
    ])
    items.value = usersRes.data.items
    pendingList.value = pendingRes.data
  } finally {
    loading.value = false
  }
}

async function loadTemplates() {
  const res = await api.get('/coupons/templates', { params: { active_only: true, limit: 100 } })
  templates.value = res.data.items
}

async function openDetail(row) {
  const res = await api.get(`/users/${row.id}`)
  current.value = res.data
  detailVisible.value = true
}

async function openReview(row) {
  current.value = row
  reviewNote.value = ''
  const detail = await api.get(`/users/${row.id}/verifications`)
  const pending = detail.data.find((v) => v.status === 'pending')
  if (!pending) {
    ElMessage.warning('未找到待审记录')
    return
  }
  pendingMap.value[row.id] = pending.id
  reviewMaterial.value = pending.material_note || row.latest_material_note || ''
  reviewVisible.value = true
}

async function doReview(approve) {
  if (!approve && !reviewNote.value.trim()) {
    ElMessage.warning('驳回时请填写原因，方便用户修改后重提')
    return
  }
  const vid = pendingMap.value[current.value.id]
  await api.post(`/users/verifications/${vid}/review`, { approve, review_note: reviewNote.value })
  ElMessage.success(approve ? '已通过' : '已驳回')
  reviewVisible.value = false
  load()
}

function openIssue(row) {
  current.value = row
  issueForm.template_id = templates.value[0]?.id || ''
  issueForm.quantity = 1
  issueVisible.value = true
}

async function doIssue() {
  if (!issueForm.template_id) {
    ElMessage.warning('请选择模板')
    return
  }
  await api.post('/coupons/issue', {
    user_id: current.value.id,
    template_id: issueForm.template_id,
    quantity: issueForm.quantity,
  })
  ElMessage.success('发券成功')
  issueVisible.value = false
}

function openBatchIssue() {
  issueForm.template_id = templates.value[0]?.id || ''
  issueForm.quantity = 1
  batchIssueVisible.value = true
}

async function doBatchIssue() {
  if (!issueForm.template_id) {
    ElMessage.warning('请选择模板')
    return
  }
  const res = await api.post('/coupons/issue-batch', {
    user_ids: selectedApproved.value.map((u) => u.id),
    template_id: issueForm.template_id,
    quantity: issueForm.quantity,
  })
  const ok = res.data.issued?.length || 0
  const fail = res.data.failed?.length || 0
  ElMessage.success(`批量完成：生成 ${ok} 张券，失败 ${fail} 人`)
  batchIssueVisible.value = false
}

onMounted(async () => {
  await Promise.all([load(), loadTemplates()])
})
</script>
