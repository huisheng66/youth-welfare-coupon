<template>
  <el-skeleton v-if="loading" class="page-card" animated :rows="6" />
  <div v-else-if="!merchant" class="page-card">
    <h2 class="page-title">商家不存在</h2>
    <p class="page-desc">该门店可能已下架；可返回券列表查看其他指定商家。</p>
    <el-button type="primary" class="section-gap" @click="$router.push('/user/coupons')">返回我的优惠券</el-button>
  </div>
  <div v-else>
    <div class="back-row">
      <el-button link @click="goBack">← 返回</el-button>
    </div>

    <div class="page-card">
      <button
        v-if="merchant.has_photo"
        type="button"
        class="photo-btn"
        aria-label="查看门头照大图"
        @click="viewerOpen = true"
      >
        <img class="photo" :src="photoUrl" alt="门头照" />
      </button>
      <div v-else class="photo photo-placeholder">商家暂未上传门头照</div>
      <h2 class="page-title">{{ merchant.name }}</h2>
      <p v-if="merchant.description" class="page-desc">{{ merchant.description }}</p>
    </div>

    <div class="page-card section-gap">
      <div class="section-label">位置</div>
      <div class="info-row">
        <span class="info-text">{{ merchant.address || '暂未填写地址' }}</span>
        <button v-if="merchant.address" type="button" class="copy-btn" @click="copy(merchant.address, '地址已复制')">
          复制
        </button>
      </div>
      <div v-if="navLinks.length" class="nav-links">
        <a v-for="l in navLinks" :key="l.label" :href="l.href" target="_blank" rel="noopener">{{ l.label }}</a>
      </div>
      <p v-if="merchant.longitude && merchant.latitude" class="muted nav-hint">
        点击地图名称打开路线规划；手机端会尝试拉起对应地图 App
      </p>
    </div>

    <div class="page-card section-gap">
      <div class="section-label">联系电话</div>
      <div class="info-row">
        <a v-if="merchant.contact_phone" class="phone" :href="`tel:${merchant.contact_phone}`">
          {{ merchant.contact_phone }}
        </a>
        <span v-else class="info-text">暂未填写电话</span>
        <button
          v-if="merchant.contact_phone"
          type="button"
          class="copy-btn"
          @click="copy(merchant.contact_phone, '电话已复制')"
        >
          复制
        </button>
      </div>
      <p v-if="merchant.contact_phone" class="muted nav-hint">手机端点击号码可直接拨打</p>
    </div>

    <div v-if="viewerOpen" class="photo-viewer" role="dialog" aria-label="门头照大图" @click="viewerOpen = false">
      <img :src="photoUrl" alt="门头照大图" />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../api'
import { buildNavLinks } from '../../utils/geo'

const route = useRoute()
const router = useRouter()
const merchant = ref(null)
const loading = ref(true)
const viewerOpen = ref(false)

// ?v=照片更新时间：覆盖上传后 300s 内的短缓存也能立即失效
const photoUrl = computed(() => {
  const m = merchant.value
  if (!m?.has_photo) return ''
  const v = m.photo_updated_at ? new Date(m.photo_updated_at).getTime() : ''
  return `/api/merchants/${m.id}/photo${v ? `?v=${v}` : ''}`
})
const navLinks = computed(() => (merchant.value ? buildNavLinks(merchant.value) : []))

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/user/coupons')
}

async function copy(text, message) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  ElMessage.success(message)
}

function onKey(e) {
  if (e.key === 'Escape') viewerOpen.value = false
}

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  try {
    merchant.value = (await api.get(`/merchants/${route.params.id}`)).data
  } catch {
    merchant.value = null
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.back-row {
  margin-bottom: 12px;
}

.photo-btn {
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: none;
  cursor: zoom-in;
  border-radius: var(--radius);
}

.photo {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 14px;
}

.photo-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  background: var(--surface-2);
  border-style: dashed;
  margin-bottom: 14px;
}

.photo-btn:hover .photo {
  border-color: var(--brand);
  transition: border-color 150ms ease;
}

.info-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-top: 6px;
}

.info-text {
  color: var(--ink);
  font-size: var(--text-base);
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.copy-btn {
  flex: none;
  padding: 2px 10px;
  font-size: var(--text-sm);
  color: var(--brand);
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 150ms ease;
}

.copy-btn:hover {
  border-color: var(--brand);
}

.nav-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 14px;
}

.nav-links a {
  color: var(--brand);
  font-weight: 600;
  text-decoration: none;
  transition: color 150ms ease;
}

.nav-links a:hover {
  color: var(--brand-hover);
  text-decoration: underline;
}

.nav-hint {
  margin-top: 10px;
  font-size: var(--text-xs);
}

.phone {
  color: var(--brand);
  font-size: var(--text-base);
  font-weight: 600;
  text-decoration: none;
}

.phone:hover {
  text-decoration: underline;
}

.photo-viewer {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(21, 32, 43, 0.82);
  cursor: zoom-out;
}

.photo-viewer img {
  max-width: 94vw;
  max-height: 92vh;
  border-radius: var(--radius);
}

@media (max-width: 720px) {
  .info-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .copy-btn {
    align-self: flex-start;
  }
}
</style>
