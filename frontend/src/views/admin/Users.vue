<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">用户核验</h2>
        <p class="page-desc">审核身份材料，通过后可发券或入账志愿时长</p>
      </div>
      <div class="filters">
        <el-select v-model="status" clearable placeholder="核验状态" style="width:140px" @change="onFilter">
          <el-option label="未提交" value="draft" />
          <el-option label="待审核" value="pending" />
          <el-option label="已通过" value="approved" />
          <el-option label="已驳回" value="rejected" />
        </el-select>
        <el-input v-model="q" placeholder="用户名 / 昵称 / 手机 / 学号" clearable style="width:220px" @keyup.enter="onFilter" />
        <el-button type="primary" @click="onFilter">查询</el-button>
        <el-button type="success" :disabled="!selectedApproved.length" @click="openBatchIssue">
          批量发券 ({{ selectedApproved.length }})
        </el-button>
        <el-button @click="openImportUsers">导入名单</el-button>
        <el-button @click="openImportIssue">按名单发券</el-button>
        <el-button @click="onExportUsers">导出用户</el-button>
      </div>
    </div>

    <div v-if="pendingList.length" class="pending-box">
      <div class="pending-head">
        <div>
          <strong>待审核申请（{{ pendingList.length }}）</strong>
          <span class="muted" style="margin-left:8px">可批量通过 / 驳回</span>
        </div>
        <div class="filters">
          <el-button
            type="success"
            size="small"
            :disabled="!selectedPending.length"
            :loading="batchReviewing"
            @click="doBatchReview(true)"
          >
            批量通过 ({{ selectedPending.length }})
          </el-button>
          <el-button
            type="danger"
            size="small"
            plain
            :disabled="!selectedPending.length"
            :loading="batchReviewing"
            @click="openBatchReject"
          >
            批量驳回 ({{ selectedPending.length }})
          </el-button>
        </div>
      </div>
      <el-table
        :data="pendingList"
        size="small"
        stripe
        max-height="280"
        @selection-change="onPendingSelect"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column prop="username" label="用户名" width="120" />
        <el-table-column prop="display_name" label="昵称" width="110" show-overflow-tooltip />
        <el-table-column prop="real_name" label="姓名" width="100" />
        <el-table-column prop="phone" label="手机" width="130" />
        <el-table-column prop="student_no" label="学号" width="120" show-overflow-tooltip />
        <el-table-column prop="organization" label="单位/组织" min-width="140" show-overflow-tooltip />
        <el-table-column prop="material_note" label="本次核验材料" min-width="220" show-overflow-tooltip />
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="openReviewByPending(row)">审核</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-table v-loading="loading" :data="items" stripe empty-text="暂无用户" @selection-change="onSelect">
      <el-table-column type="selection" width="48" :selectable="(row) => row.verify_status === 'approved'" />
      <el-table-column prop="real_name" label="姓名" width="100" />
      <el-table-column prop="username" label="用户名" width="120" />
      <el-table-column prop="student_no" label="学号" width="120" show-overflow-tooltip />
      <el-table-column label="银行卡" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.bank_card_bound ? (row.bank_card_masked || '已绑定') : '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="phone" label="手机" width="130" />
      <el-table-column prop="organization" label="单位/组织" min-width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <StatusTag :text="verifyStatusText(row.verify_status)" :type="verifyStatusType(row.verify_status)" />
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        :width="actionColumnWidth"
        fixed="right"
        class-name="action-column"
        label-class-name="action-column"
      >
        <template #default="{ row }">
          <div class="row-actions">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button link type="primary" @click="openIssue(row)" :disabled="row.verify_status !== 'approved'">发券</el-button>
            <el-button link type="success" @click="openReview(row)" :disabled="row.verify_status !== 'pending'">审核</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <span class="muted">共 {{ total }} 人</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        layout="prev, pager, next, sizes"
        :total="total"
        :page-sizes="[20, 50, 100]"
        @current-change="load"
        @size-change="() => { page = 1; load() }"
      />
    </div>

    <el-dialog v-model="detailVisible" title="用户详情" width="760px">
      <el-descriptions v-if="current" :column="1" border>
        <el-descriptions-item label="用户名">{{ current.username }}</el-descriptions-item>
        <el-descriptions-item label="昵称">{{ current.display_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="姓名">{{ current.real_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="手机">{{ current.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="学号">{{ current.student_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="组织">{{ current.organization || '-' }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ formatTime(current.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="银行卡">
          <span v-if="current.bank_card_bound">
            {{ current.bank_card_masked || '已绑定' }}
            <span v-if="current.bank_card_bank_name" class="muted"> · {{ current.bank_card_bank_name }}</span>
          </span>
          <span v-else class="muted">未绑定</span>
          <el-button
            v-if="isSuperAdmin && current.bank_card_bound"
            link
            type="warning"
            style="margin-left:8px"
            :loading="revealing"
            @click="revealCard"
          >
            查看完整卡号
          </el-button>
        </el-descriptions-item>
        <el-descriptions-item v-if="revealedCard" label="完整卡号">
          <code>{{ revealedCard }}</code>
          <span class="muted" style="margin-left:8px">（已记审计，请勿截图传播）</span>
        </el-descriptions-item>
        <el-descriptions-item label="绑卡时间">{{ formatTime(current.bank_card_bound_at) }}</el-descriptions-item>
        <el-descriptions-item label="备注">{{ current.remark || '-' }}</el-descriptions-item>
        <el-descriptions-item label="核验状态">
          <StatusTag :text="verifyStatusText(current.verify_status)" :type="verifyStatusType(current.verify_status)" />
        </el-descriptions-item>
        <el-descriptions-item label="最近材料">{{ current.latest_material_note || '-' }}</el-descriptions-item>
      </el-descriptions>
      <h3 style="margin:16px 0 8px;font-size:1rem">核验历史</h3>
      <el-table :data="detailHistory" size="small" stripe empty-text="暂无记录" max-height="240">
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <StatusTag :text="verifyStatusText(row.status)" :type="verifyStatusType(row.status)" />
          </template>
        </el-table-column>
        <el-table-column prop="material_note" label="材料" min-width="120" show-overflow-tooltip />
        <el-table-column prop="review_note" label="审核备注" min-width="100" show-overflow-tooltip />
        <el-table-column label="提交" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="reviewer_name" label="审核人" width="110" show-overflow-tooltip />
        <el-table-column label="审核时间" width="150">
          <template #default="{ row }">{{ formatTime(row.reviewed_at) }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="reviewVisible" title="审核用户" width="760px">
      <el-descriptions :column="compactViewport ? 1 : 2" border style="margin-bottom:12px">
        <el-descriptions-item label="用户名">{{ current?.username || '-' }}</el-descriptions-item>
        <el-descriptions-item label="昵称">{{ current?.display_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="姓名">{{ current?.real_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="手机">{{ current?.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="学号">{{ current?.student_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="单位/组织">{{ current?.organization || '-' }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ formatTime(current?.account_created_at) }}</el-descriptions-item>
        <el-descriptions-item label="当前状态">
          <StatusTag :text="verifyStatusText(current?.verify_status)" :type="verifyStatusType(current?.verify_status)" />
        </el-descriptions-item>
        <el-descriptions-item label="银行卡">
          <span v-if="current?.bank_card_bound">
            {{ current.bank_card_masked || '已绑定' }}
            <span v-if="current.bank_card_bank_name" class="muted"> · {{ current.bank_card_bank_name }}</span>
          </span>
          <span v-else class="muted">未绑定</span>
        </el-descriptions-item>
        <el-descriptions-item label="绑定时间">{{ formatTime(current?.bank_card_bound_at) }}</el-descriptions-item>
        <el-descriptions-item label="个人备注" :span="compactViewport ? 1 : 2">
          <span class="review-material">{{ current?.remark || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="本次核验材料" :span="compactViewport ? 1 : 2">
          <span class="review-material">{{ reviewMaterial || '-' }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <h3 class="review-section-title">历史申请与审核记录</h3>
      <el-table :data="detailHistory" size="small" stripe empty-text="暂无记录" max-height="240">
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <StatusTag :text="verifyStatusText(row.status)" :type="verifyStatusType(row.status)" />
          </template>
        </el-table-column>
        <el-table-column prop="material_note" label="材料说明" min-width="190" show-overflow-tooltip />
        <el-table-column prop="review_note" label="审核备注" min-width="150" show-overflow-tooltip />
        <el-table-column label="提交时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="reviewer_name" label="审核人" width="110" show-overflow-tooltip />
        <el-table-column label="审核时间" width="150">
          <template #default="{ row }">{{ formatTime(row.reviewed_at) }}</template>
        </el-table-column>
      </el-table>
      <h3 class="review-section-title">本次审核意见</h3>
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

    <el-dialog v-model="importUsersVisible" title="导入用户名单" width="560px">
      <el-alert type="info" :closable="false" style="margin-bottom:12px"
        title="支持 .xlsx / .csv / .txt / .docx；列：姓名、学号、用户名、手机、邮箱（可选）、组织、备注（首行可为表头）"
        description="导入用户直接视为核验通过（可直接发券/入账时长），统一初始密码见导入结果。用户名缺省时自动用学号或手机号；名单含邮箱且系统已配置 SMTP 时可自动发送开通邮件。"
      />
      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.csv,.txt,.docx"
        :on-change="onImportUsersFile"
        :on-remove="() => (importUsersFile = null)"
      >
        <div class="el-upload__text">拖拽文件到此处或 <em>点击选择</em></div>
      </el-upload>
      <div style="margin-top:12px">
        <el-checkbox v-model="importDryRun">仅校验不写入（试运行）</el-checkbox>
        <el-checkbox v-model="importNotify">向含邮箱的用户发送开通邮件</el-checkbox>
      </div>
      <template #footer>
        <el-button @click="downloadUsersTemplate">下载模板</el-button>
        <el-button type="primary" :loading="importing" :disabled="!importUsersFile" @click="doImportUsers">
          {{ importDryRun ? '开始校验' : '开始导入' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importIssueVisible" title="按名单发券" width="560px">
      <el-alert type="info" :closable="false" style="margin-bottom:12px"
        title="文件每行一个用户标识（用户名 / 邮箱 / 手机 / 学号）"
        description="仅核验通过的用户可发券；查无此人、未核验的行会跳过并在结果中说明。"
      />
      <el-form label-width="90px">
        <el-form-item label="券模板">
          <el-select v-model="importIssueForm.template_id" style="width:100%" filterable>
            <el-option
              v-for="t in templates"
              :key="t.id"
              :label="`${t.name}（${t.merchant_name}）`"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="每人数量">
          <el-input-number v-model="importIssueForm.quantity" :min="1" :max="10" />
        </el-form-item>
      </el-form>
      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.csv,.txt,.docx"
        :on-change="onImportIssueFile"
        :on-remove="() => (importIssueFile = null)"
      >
        <div class="el-upload__text">拖拽文件到此处或 <em>点击选择</em></div>
      </el-upload>
      <template #footer>
        <el-button @click="downloadIssueTemplate">下载模板</el-button>
        <el-button
          type="primary"
          :loading="importing"
          :disabled="!importIssueFile || !importIssueForm.template_id"
          @click="doImportIssue"
        >
          开始发放
        </el-button>
      </template>
    </el-dialog>

    <ImportResultDialog v-model="importResultVisible" :result="importResult" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import api, { downloadFile } from '../../api'
import { useAuth } from '../../auth'
import ImportResultDialog from '../../components/ImportResultDialog.vue'
import StatusTag from '../../components/StatusTag.vue'
import { formatTime, verifyStatusText, verifyStatusType } from '../../utils/format'

const auth = useAuth()
const isSuperAdmin = computed(() => auth.account?.role === 'super_admin')

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
const selectedPending = ref([])
const batchReviewing = ref(false)
const detailHistory = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const revealing = ref(false)
const revealedCard = ref('')
const selectedApproved = computed(() => selected.value.filter((r) => r.verify_status === 'approved'))
const compactViewport = ref(false)
const viewportWidth = ref(0)
const actionColumnWidth = computed(() => {
  // Keep desktop spacious; only tighten on compact viewports.
  if (!compactViewport.value) return 240
  return Math.min(132, Math.max(108, Math.round(viewportWidth.value * 0.34)))
})
let compactMedia = null

function syncCompactViewport() {
  compactViewport.value = compactMedia?.matches ?? window.innerWidth <= 768
  viewportWidth.value = window.innerWidth
}

function onSelect(rows) {
  selected.value = rows
}

function onPendingSelect(rows) {
  selectedPending.value = rows
}

async function load() {
  loading.value = true
  try {
    const [usersRes, pendingRes] = await Promise.all([
      api.get('/users', {
        params: {
          verify_status: status.value || undefined,
          q: q.value || undefined,
          skip: (page.value - 1) * pageSize.value,
          limit: pageSize.value,
        },
      }),
      api.get('/users/pending-verifications'),
    ])
    items.value = usersRes.data.items
    total.value = usersRes.data.total
    pendingList.value = pendingRes.data
  } finally {
    loading.value = false
  }
}

function onFilter() {
  page.value = 1
  load()
}

async function onExportUsers() {
  const qs = status.value ? `?verify_status=${status.value}` : ''
  await downloadFile(`/export/users${qs}`, 'users.csv')
  ElMessage.success('已开始下载')
}

async function loadTemplates() {
  const res = await api.get('/coupons/templates', { params: { active_only: true, limit: 100 } })
  templates.value = res.data.items
}

async function revealCard() {
  if (!current.value?.id) return
  try {
    await ElMessageBox.confirm(
      '将解密查看完整银行卡号，操作会记入审计日志。确认继续？',
      '敏感操作',
      { type: 'warning' },
    )
  } catch {
    return
  }
  revealing.value = true
  try {
    const { data } = await api.get(`/users/${current.value.id}/bank-card`)
    revealedCard.value = data.card_number
  } finally {
    revealing.value = false
  }
}

async function openDetail(row) {
  revealedCard.value = ''
  const res = await api.get(`/users/${row.id}`)
  current.value = res.data
  try {
    const h = await api.get(`/users/${row.id}/verifications`)
    detailHistory.value = h.data || []
  } catch {
    detailHistory.value = []
  }
  detailVisible.value = true
}

async function openReview(row) {
  reviewNote.value = ''
  const detail = await api.get(`/users/${row.id}/verifications`)
  detailHistory.value = detail.data || []
  const pending = detail.data.find((v) => v.status === 'pending')
  if (!pending) {
    ElMessage.warning('未找到待审记录')
    return
  }
  current.value = { ...row, ...pending, id: row.id }
  pendingMap.value[row.id] = pending.id
  reviewMaterial.value = pending.material_note || row.latest_material_note || ''
  reviewVisible.value = true
}

async function openReviewByPending(row) {
  current.value = { ...row, id: row.user_id }
  reviewNote.value = ''
  pendingMap.value[row.user_id] = row.id
  reviewMaterial.value = row.material_note || ''
  try {
    const history = await api.get(`/users/${row.user_id}/verifications`)
    detailHistory.value = history.data || []
  } catch {
    detailHistory.value = [row]
  }
  reviewVisible.value = true
}

async function doReview(approve) {
  if (!approve && !reviewNote.value.trim()) {
    ElMessage.warning('驳回时请填写原因，方便用户修改后重提')
    return
  }
  const vid = pendingMap.value[current.value.id]
  if (!vid) {
    ElMessage.warning('未找到待审记录')
    return
  }
  await api.post(`/users/verifications/${vid}/review`, { approve, review_note: reviewNote.value })
  ElMessage.success(approve ? '已通过' : '已驳回')
  reviewVisible.value = false
  load()
}

async function doBatchReview(approve, note = '') {
  if (!selectedPending.value.length) return
  if (!approve && !note.trim()) {
    ElMessage.warning('批量驳回请填写原因')
    return
  }
  if (approve) {
    try {
      await ElMessageBox.confirm(
        `确认批量通过 ${selectedPending.value.length} 条待审申请？`,
        '批量通过',
        { type: 'warning', confirmButtonText: '确认通过' },
      )
    } catch {
      return
    }
  }
  batchReviewing.value = true
  try {
    const res = await api.post('/users/verifications/batch-review', {
      verification_ids: selectedPending.value.map((p) => p.id),
      approve,
      review_note: note,
    })
    ElMessage.success(res.data.message || '批量处理完成')
    selectedPending.value = []
    load()
  } finally {
    batchReviewing.value = false
  }
}

async function openBatchReject() {
  const { value } = await ElMessageBox.prompt('请填写驳回原因（用户可见）', '批量驳回', {
    inputPlaceholder: '原因',
    confirmButtonText: '确认驳回',
    cancelButtonText: '取消',
    inputValidator: (v) => !!(v && v.trim()) || '请填写原因',
  }).catch(() => ({ value: null }))
  if (value === null) return
  await doBatchReview(false, value.trim())
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
  const t = templates.value.find((x) => x.id === issueForm.template_id)
  try {
    await ElMessageBox.confirm(
      `向「${current.value?.username}」发放 ${issueForm.quantity} 张「${t?.name || '券'}」？`,
      '确认发券',
      { type: 'warning' },
    )
  } catch {
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
  const n = selectedApproved.value.length
  const totalQty = n * issueForm.quantity
  try {
    await ElMessageBox.confirm(
      `向 ${n} 人各发 ${issueForm.quantity} 张，共约 ${totalQty} 张券，确认？`,
      '批量发券确认',
      { type: 'warning' },
    )
  } catch {
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

// ---- 批量导入（名单文件：xlsx / csv / txt / docx）----
const importUsersVisible = ref(false)
const importIssueVisible = ref(false)
const importResultVisible = ref(false)
const importUsersFile = ref(null)
const importIssueFile = ref(null)
const importDryRun = ref(false)
const importNotify = ref(true)
const importing = ref(false)
const importResult = ref(null)
const importIssueForm = reactive({ template_id: '', quantity: 1 })
const IMPORT_TIMEOUT = 60000

function onImportUsersFile(uploadFile) {
  importUsersFile.value = uploadFile?.raw || null
}

function onImportIssueFile(uploadFile) {
  importIssueFile.value = uploadFile?.raw || null
}

function openImportUsers() {
  importUsersFile.value = null
  importDryRun.value = false
  importUsersVisible.value = true
}

function openImportIssue() {
  importIssueFile.value = null
  importIssueForm.template_id = importIssueForm.template_id || templates.value[0]?.id || ''
  importIssueForm.quantity = 1
  importIssueVisible.value = true
}

function _downloadTextCsv(filename, lines) {
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

function downloadUsersTemplate() {
  _downloadTextCsv('用户名单模板.csv', [
    '姓名,学号,用户名,手机,邮箱,组织,备注',
    '张三,20260001,zhangsan,13800000001,zhangsan@example.com,某某大学,',
    '李四,20260002,,13800000002,,某某大学,班长',
  ])
}

function downloadIssueTemplate() {
  _downloadTextCsv('发券名单模板.csv', ['用户标识（用户名/邮箱/手机/学号）', 'youth1', '13800000001'])
}

function showImportResult(res) {
  importResult.value = res.data
  importResultVisible.value = true
}

async function doImportUsers() {
  const fd = new FormData()
  fd.append('file', importUsersFile.value)
  fd.append('dry_run', importDryRun.value ? 'true' : 'false')
  fd.append('notify', importNotify.value ? 'true' : 'false')
  importing.value = true
  try {
    const res = await api.post('/users/import', fd, { timeout: IMPORT_TIMEOUT })
    importUsersVisible.value = false
    showImportResult(res)
    if (!importDryRun.value && res.data.succeeded > 0) load()
  } finally {
    importing.value = false
  }
}

async function doImportIssue() {
  if (!importIssueForm.template_id) {
    ElMessage.warning('请选择模板')
    return
  }
  const fd = new FormData()
  fd.append('file', importIssueFile.value)
  fd.append('template_id', importIssueForm.template_id)
  fd.append('quantity', String(importIssueForm.quantity))
  importing.value = true
  try {
    const res = await api.post('/coupons/issue-import', fd, { timeout: IMPORT_TIMEOUT })
    importIssueVisible.value = false
    showImportResult(res)
    if (res.data.succeeded > 0) load()
  } finally {
    importing.value = false
  }
}

onMounted(async () => {
  compactMedia = window.matchMedia('(max-width: 768px)')
  syncCompactViewport()
  compactMedia.addEventListener?.('change', syncCompactViewport)
  window.addEventListener('resize', syncCompactViewport)
  await Promise.all([load(), loadTemplates()])
})

onBeforeUnmount(() => {
  compactMedia?.removeEventListener?.('change', syncCompactViewport)
  window.removeEventListener('resize', syncCompactViewport)
})
</script>

<style scoped>
.pending-box {
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--warning) 35%, var(--border));
  background: #fffbeb;
  border-radius: 10px;
}
.pending-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.review-section-title {
  margin: 16px 0 8px;
  font-size: 1rem;
}

.review-material {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.row-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: center;
  width: 100%;
}

.row-actions .el-button {
  min-width: 0;
  padding-inline: 2px;
}

.row-actions .el-button + .el-button {
  margin-left: 0;
}

:deep(.action-column .cell) {
  padding-inline: 4px;
}

@media (max-width: 768px) {
  .row-actions .el-button {
    font-size: var(--text-sm);
    min-height: 44px;
  }
}
</style>
