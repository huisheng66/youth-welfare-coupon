<template>
  <el-dialog
    :model-value="modelValue"
    :title="meta.title"
    width="640px"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="reset"
  >
    <el-steps :active="stepIndex" simple style="margin-bottom:16px">
      <el-step title="上传预检" />
      <el-step title="确认执行" />
      <el-step title="批次结果" />
    </el-steps>

    <!-- 第 1 步：上传文件 + 参数 -->
    <div v-if="step === 'upload'">
      <el-alert type="info" :closable="false" style="margin-bottom:12px" :title="meta.hint" :description="meta.desc" />
      <el-form v-if="kind === 'issue'" label-width="90px">
        <el-form-item label="券模板">
          <el-select v-model="templateId" style="width:100%" filterable>
            <el-option
              v-for="t in templates"
              :key="t.id"
              :label="`${t.name}（${t.merchant_name}）`"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="每人数量">
          <el-input-number v-model="quantity" :min="1" :max="10" />
        </el-form-item>
      </el-form>
      <el-form v-else-if="kind === 'points'" label-width="90px">
        <el-form-item label="默认说明">
          <el-input v-model="reason" placeholder="行内未填说明时使用" maxlength="255" />
        </el-form-item>
      </el-form>
      <div v-else style="margin-bottom:8px">
        <el-checkbox v-model="notify">向含邮箱的用户发送激活邮件（一次性链接设置密码，需已配置 SMTP）</el-checkbox>
      </div>
      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.csv,.txt,.docx"
        :on-change="onFile"
        :on-remove="() => (file = null)"
      >
        <div class="el-upload__text">拖拽文件到此处或 <em>点击选择</em></div>
      </el-upload>
    </div>

    <!-- 第 2 步：预检结果确认 -->
    <div v-else-if="step === 'preview' && preview">
      <el-alert
        :type="preview.executable > 0 ? 'success' : 'warning'"
        :closable="false"
        style="margin-bottom:12px"
        :title="`共 ${preview.total} 行：可执行 ${preview.executable} 行，预检失败 ${preview.failed} 行`"
        description="预检未写入任何业务数据；执行时会重新校验资格与唯一冲突。"
      />
      <ImportErrorsTable v-if="preview.errors?.length" :errors="preview.errors" />
      <p v-if="preview.errors_truncated" class="muted" style="margin-top:8px">
        错误明细仅显示前 100 条，执行后可在批次结果下载全部逐行 CSV。
      </p>
    </div>

    <!-- 第 3 步：执行结果 -->
    <div v-else-if="step === 'result' && result">
      <el-alert
        :type="result.failed > 0 ? 'warning' : 'success'"
        :closable="false"
        style="margin-bottom:12px"
        :title="result.message || `执行完成：成功 ${result.succeeded} 行，失败 ${result.failed} 行`"
      />
      <el-alert
        v-if="result.credentials?.length"
        type="warning"
        :closable="false"
        style="margin-bottom:12px"
        title="个人初始凭证：仅本次显示，请立即分发给相应用户（关闭通知或无邮箱的用户）"
      >
        <div class="cred-list">
          <div v-for="c in result.credentials" :key="c.row" class="cred-item">
            <span class="cred-user">{{ c.username }}</span>
            <code>{{ c.password }}</code>
          </div>
        </div>
        <p class="cred-tip">初始密码仅在此出现一次，不保存历史；用户首次登录后将强制改密。</p>
      </el-alert>
      <p v-if="result.email_queued" class="muted" style="margin-bottom:12px">
        已为 {{ result.email_queued }} 名含邮箱的用户排队发送激活邮件（一次性链接设置密码）。
      </p>
      <el-alert
        v-if="result.smtp_unconfigured"
        type="warning"
        :closable="false"
        style="margin-bottom:12px"
        title="SMTP 未配置：激活邮件已入队暂无法投递，将在配置 SMTP 后由系统自动重发；也可联系超级管理员在邮件任务页处理。"
      />
      <ImportErrorsTable v-if="result.errors?.length" :errors="result.errors" show-status />
      <p v-if="result.errors_truncated" class="muted" style="margin-top:8px">
        错误明细仅显示前 100 条，点击下方「下载逐行 CSV」获取全部记录。
      </p>
    </div>

    <template #footer>
      <template v-if="step === 'upload'">
        <el-button @click="downloadTemplate">下载模板</el-button>
        <el-button
          type="primary"
          :loading="working"
          :disabled="!file || (kind === 'issue' && !templateId)"
          @click="doPreview"
        >
          开始预检
        </el-button>
      </template>
      <template v-else-if="step === 'preview'">
        <el-button :disabled="working" @click="step = 'upload'">上一步</el-button>
        <el-button type="primary" :loading="working" :disabled="!preview?.executable" @click="doExecute">
          确认执行 {{ preview?.executable || 0 }} 行
        </el-button>
      </template>
      <template v-else>
        <el-button @click="downloadCsv">下载逐行 CSV</el-button>
        <el-button v-if="result?.failed > 0" type="warning" :loading="working" @click="doExecute">
          重试失败行
        </el-button>
        <el-button type="primary" @click="close">完成</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import api, { downloadFile } from '../api'
import ImportErrorsTable from './ImportErrorsTable.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  kind: { type: String, required: true }, // users / issue / points
  templates: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'done'])

const META = {
  users: {
    title: '导入用户名单',
    hint: '支持 .xlsx / .csv / .txt / .docx；列：姓名、学号、用户名、手机、邮箱（可选）、组织、备注（首行可为表头）',
    desc: '导入用户直接视为核验通过。含邮箱的用户将收到一次性激活链接自行设置密码；无邮箱或关闭通知的用户使用个人初始凭证（仅执行结果中显示一次）。预检不写入任何数据，确认后逐行执行，失败行可重试。',
    templateLines: [
      '姓名,学号,用户名,手机,邮箱,组织,备注',
      '张三,20260001,zhangsan,13800000001,zhangsan@example.com,某某大学,',
      '李四,20260002,,13800000002,,某某大学,班长',
    ],
    templateName: '用户名单模板.csv',
  },
  issue: {
    title: '按名单发券',
    hint: '文件每行一个用户标识（用户名 / 邮箱 / 手机 / 学号）',
    desc: '仅核验通过的用户可发券；同一用户在文件内重复时保留首次出现的行。预检不写入任何数据。',
    templateLines: ['用户标识（用户名/邮箱/手机/学号）', 'youth1', '13800000001'],
    templateName: '发券名单模板.csv',
  },
  points: {
    title: '按名单调整时长',
    hint: '文件每行：用户标识、时长(小时)、说明(可选)；时长支持负数（扣减）',
    desc: '仅核验通过的用户可调整；同一用户在文件内重复时保留首次出现的行。预检不写入任何数据。',
    templateLines: [
      '用户标识（用户名/邮箱/手机/学号）,时长(小时),说明',
      'youth1,2.5,社区志愿服务',
      '13800000001,-1,',
    ],
    templateName: '时长导入模板.csv',
  },
}

const meta = computed(() => META[props.kind])

const step = ref('upload')
const stepIndex = computed(() => ({ upload: 0, preview: 1, result: 2 })[step.value])
const file = ref(null)
const templateId = ref('')
const quantity = ref(1)
const reason = ref('志愿服务时长入账')
const notify = ref(true)
const preview = ref(null)
const result = ref(null)
const working = ref(false)

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) reset()
  },
)

function reset() {
  step.value = 'upload'
  file.value = null
  templateId.value = props.templates[0]?.id || ''
  quantity.value = 1
  reason.value = '志愿服务时长入账'
  notify.value = true
  preview.value = null
  result.value = null
  working.value = false
}

function onFile(uploadFile) {
  file.value = uploadFile?.raw || null
}

function close() {
  emit('update:modelValue', false)
}

async function doPreview() {
  const fd = new FormData()
  fd.append('file', file.value)
  fd.append('kind', props.kind)
  if (props.kind === 'issue') {
    fd.append('template_id', templateId.value)
    fd.append('quantity', String(quantity.value))
  } else if (props.kind === 'points') {
    fd.append('reason', reason.value)
  } else {
    fd.append('notify', notify.value ? 'true' : 'false')
  }
  working.value = true
  try {
    const res = await api.post('/imports/preview', fd, { timeout: 60000 })
    preview.value = res.data
    step.value = 'preview'
  } finally {
    working.value = false
  }
}

async function doExecute() {
  const batchId = preview.value?.id || result.value?.id
  working.value = true
  try {
    const res = await api.post(`/imports/${batchId}/execute`, {
      file_sha256: preview.value?.file_sha256,
    })
    result.value = res.data
    step.value = 'result'
    if (res.data.succeeded > 0) emit('done', res.data)
  } finally {
    working.value = false
  }
}

async function downloadCsv() {
  const batchId = result.value?.id || preview.value?.id
  await downloadFile(`/imports/${batchId}/rows.csv`, `import_${props.kind}_rows.csv`)
}

function downloadTemplate() {
  const blob = new Blob(['﻿' + meta.value.templateLines.join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = meta.value.templateName
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
</script>

<style scoped>
.cred-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 4px 0;
}
.cred-item {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cred-user {
  min-width: 8em;
  font-weight: 600;
}
.cred-item code {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.9em;
  padding: 1px 8px;
  border-radius: 4px;
  background: color-mix(in srgb, currentColor 8%, transparent);
}
.cred-tip {
  margin: 6px 0 0;
  font-size: 0.8125rem;
  opacity: 0.85;
}
</style>
