<template>
  <div class="page-card">
    <div class="page-header">
      <div>
        <h2 class="page-title">商家管理</h2>
        <p class="page-desc">维护合作门店；券模板与核销均按商家隔离</p>
      </div>
      <div class="filters">
        <el-input
          v-model="q"
          clearable
          placeholder="搜索商家名称"
          style="width:180px"
          @keyup.enter="onFilter"
          @clear="onFilter"
        />
        <el-select v-model="activeOnly" clearable placeholder="状态" style="width:120px" @change="onFilter">
          <el-option label="仅启用" :value="true" />
          <el-option label="全部" :value="false" />
        </el-select>
        <el-button type="primary" @click="onFilter">查询</el-button>
        <el-button type="primary" plain @click="openCreate">新增商家</el-button>
      </div>
    </div>
    <el-table v-loading="loading" :data="items" stripe>
      <template #empty>
        <EmptyState title="暂无商家" description="没有符合条件的商家；可调整搜索条件，或直接新增">
          <el-button type="primary" @click="openCreate">新增商家</el-button>
        </EmptyState>
      </template>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="contact_name" label="联系人" width="120" />
      <el-table-column prop="contact_phone" label="电话" width="140" />
      <el-table-column prop="address" label="地址" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <StatusTag :text="row.is_active ? '启用' : '停用'" :type="row.is_active ? 'success' : 'info'" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link :type="row.is_active ? 'danger' : 'success'" @click="toggle(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="muted" style="margin-top:10px">共 {{ total }} 家</div>

    <el-dialog v-model="visible" :title="form.id ? '编辑商家' : '新增商家'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="form.contact_name" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="form.contact_phone" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" /></el-form-item>
        <el-form-item label="简介"><el-input v-model="form.description" type="textarea" /></el-form-item>
        <el-form-item label="经纬度">
          <div class="coord-row">
            <el-input v-model="form.longitude" placeholder="经度，如 116.397428" />
            <el-input v-model="form.latitude" placeholder="纬度，如 39.909230" />
          </div>
          <div class="muted coord-hint">
            选填（GCJ-02）；填写后用户端「商家详情」可直接唤起地图导航，坐标可从
            <a href="https://lbs.amap.com/tools/picker" target="_blank" rel="noopener">高德坐标拾取器</a> 复制
          </div>
        </el-form-item>
        <el-form-item label="门头照">
          <div class="photo-edit">
            <img v-if="form.has_photo" class="photo-thumb" :src="photoPreviewUrl" alt="门头照" />
            <div class="photo-actions">
              <template v-if="form.id">
                <!-- 原生 label+input 触发文件选择：不依赖 JS click() 的用户激活判定，各浏览器行为一致 -->
                <label class="upload-btn" :class="{ 'is-uploading': uploading }">
                  <input
                    class="upload-input"
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    @change="onPickFile"
                  />
                  {{ uploading ? '上传中…' : form.has_photo ? '更换照片' : '上传门头照' }}
                </label>
                <el-button v-if="form.has_photo" size="small" type="danger" plain @click="removePhoto">
                  删除照片
                </el-button>
              </template>
              <span v-else class="muted">先保存商家，再上传门头照</span>
            </div>
          </div>
          <div class="muted coord-hint">支持 JPG / PNG / WebP，不超过 5MB；保存后在用户端详情页展示</div>
        </el-form-item>
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
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../../api'
import EmptyState from '../../components/EmptyState.vue'
import StatusTag from '../../components/StatusTag.vue'

const items = ref([])
const total = ref(0)
const visible = ref(false)
const loading = ref(false)
const q = ref('')
const activeOnly = ref(false)
const uploading = ref(false)
const form = reactive({
  id: '',
  name: '',
  contact_name: '',
  contact_phone: '',
  address: '',
  description: '',
  longitude: '',
  latitude: '',
  has_photo: false,
  photo_updated_at: null,
  is_active: true,
})

// ?v=照片更新时间：覆盖上传后立即取到新图，避开短缓存
const photoPreviewUrl = computed(() => {
  const v = form.photo_updated_at ? new Date(form.photo_updated_at).getTime() : ''
  return `/api/merchants/${form.id}/photo${v ? `?v=${v}` : ''}`
})

async function load() {
  loading.value = true
  try {
    const res = await api.get('/merchants', {
      params: {
        q: q.value || undefined,
        active_only: activeOnly.value === true ? true : undefined,
        limit: 100,
      },
    })
    items.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

function onFilter() {
  load()
}

function openCreate() {
  Object.assign(form, {
    id: '', name: '', contact_name: '', contact_phone: '', address: '', description: '',
    longitude: '', latitude: '', has_photo: false, photo_updated_at: null, is_active: true,
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
      longitude: form.longitude,
      latitude: form.latitude,
      is_active: form.is_active,
    })
  } else {
    await api.post('/merchants', {
      name: form.name,
      contact_name: form.contact_name,
      contact_phone: form.contact_phone,
      address: form.address,
      description: form.description,
      longitude: form.longitude,
      latitude: form.latitude,
    })
  }
  ElMessage.success('已保存')
  visible.value = false
  load()
}

// ---- 门头照（原生 <label>+<input type=file> 触发选择，不用 el-upload）----

async function onPickFile(e) {
  const file = e.target.files?.[0]
  e.target.value = '' // 允许再次选择同一文件
  if (!file) return
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.warning('图片不能超过 5MB')
    return
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await api.post(`/merchants/${form.id}/photo`, fd)
    form.has_photo = res.data.has_photo
    form.photo_updated_at = res.data.photo_updated_at
    ElMessage.success('门头照已更新')
  } finally {
    uploading.value = false
  }
}

async function removePhoto() {
  try {
    await ElMessageBox.confirm('确认删除该门店的门头照？删除后用户端详情页不再展示照片。', '提示', {
      type: 'warning',
    })
  } catch {
    return
  }
  const res = await api.delete(`/merchants/${form.id}/photo`)
  form.has_photo = res.data.has_photo
  form.photo_updated_at = res.data.photo_updated_at
  ElMessage.success('已删除门头照')
}

async function toggle(row) {
  const next = !row.is_active
  try {
    await ElMessageBox.confirm(
      next
        ? `确认启用商家「${row.name}」？`
        : `确认停用商家「${row.name}」？停用后不可再发该店券，已发未用券仍可能被核销。`,
      '提示',
      { type: 'warning' },
    )
  } catch {
    return
  }
  await api.put(`/merchants/${row.id}`, { is_active: next })
  ElMessage.success(next ? '已启用' : '已停用')
  load()
}

onMounted(load)
</script>

<style scoped>
.coord-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.coord-hint {
  font-size: 12px;
  line-height: 1.6;
  margin-top: 4px;
  width: 100%;
}

.coord-hint a {
  color: var(--brand);
}

.photo-edit {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.photo-thumb {
  width: 96px;
  height: 64px;
  object-fit: cover;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  flex: none;
}

/* 伪装成 el-button small 的原生 label：点击即打开系统文件选择 */
.upload-btn {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 11px;
  font-size: 12px;
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  user-select: none;
  transition: border-color 150ms ease, color 150ms ease;
}

.upload-btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}

.upload-btn.is-uploading {
  pointer-events: none;
  color: var(--muted);
}

.upload-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
</style>
