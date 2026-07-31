<template>
  <div class="scanner">
    <div v-if="!secureContext" class="warn">
      <strong>当前不是安全环境，浏览器禁止网页直接开摄像头。</strong>
      <div class="warn-body">
        请用手机打开：
        <code>https://电脑IP:5173</code>
        （注意是 https，首次需点「继续访问 / 高级」信任证书）。
        也可先用下方「拍照 / 相册识别」，不依赖网页摄像头权限。
      </div>
      <div class="warn-url" v-if="httpsHint">建议地址：{{ httpsHint }}</div>
    </div>
    <div v-else class="ok-tip">已处于 HTTPS/安全环境，可打开摄像头扫码。</div>

    <div id="qr-reader" class="reader"></div>

    <div class="actions">
      <el-button v-if="!running && secureContext" type="primary" @click="start" :loading="starting">
        打开摄像头扫码
      </el-button>
      <el-button v-if="running" type="danger" plain @click="stop">关闭摄像头</el-button>

      <!-- capture：手机上可直接调系统相机拍照（多数机型在 HTTP 下也可用） -->
      <label class="file-btn">
        <input
          class="file-input"
          type="file"
          accept="image/*"
          capture="environment"
          @change="onNativeFile"
        />
        拍照识别
      </label>
      <label class="file-btn secondary">
        <input class="file-input" type="file" accept="image/*" @change="onNativeFile" />
        相册选图
      </label>
    </div>
    <p class="hint muted">对准用户「出示动态券码」中的二维码；识别成功后会自动填入并预览。</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Html5Qrcode } from 'html5-qrcode'

const emit = defineEmits(['scan'])

const secureContext = ref(typeof window !== 'undefined' && !!window.isSecureContext)
const running = ref(false)
const starting = ref(false)
let scanner = null
let lastText = ''
let lastAt = 0

const httpsHint = computed(() => {
  if (typeof window === 'undefined') return ''
  const { protocol, hostname, port } = window.location
  if (protocol === 'https:') return ''
  const p = port && port !== '80' ? `:${port}` : ':5173'
  if (hostname === 'localhost' || hostname === '127.0.0.1') return ''
  return `https://${hostname}${p}/`
})

function createScanner() {
  if (!scanner) {
    scanner = new Html5Qrcode('qr-reader', { verbose: false })
  }
  return scanner
}

async function start() {
  if (!secureContext.value) {
    ElMessage.warning('请改用 HTTPS 地址访问，或使用「拍照识别」')
    return
  }
  starting.value = true
  try {
    const s = createScanner()
    if (running.value) return
    await s.start(
      { facingMode: 'environment' },
      {
        fps: 10,
        qrbox: (viewW, viewH) => {
          const edge = Math.min(viewW, viewH)
          const size = Math.floor(edge * 0.72)
          return { width: size, height: size }
        },
        aspectRatio: 1,
      },
      onDecoded,
      () => {},
    )
    running.value = true
  } catch (e) {
    const msg = e?.message || String(e)
    if (/NotAllowedError|Permission/i.test(msg)) {
      ElMessage.error('摄像头权限被拒绝，请在浏览器设置中允许，或改用拍照识别')
    } else if (/NotFoundError|DevicesNotFound/i.test(msg)) {
      ElMessage.error('未检测到摄像头，请使用拍照 / 相册识别')
    } else {
      ElMessage.error(`无法打开摄像头：${msg}`)
    }
  } finally {
    starting.value = false
  }
}

async function stop() {
  if (!scanner || !running.value) return
  try {
    await scanner.stop()
    await scanner.clear()
  } catch {
    // ignore
  }
  running.value = false
}

function onDecoded(text) {
  const value = (text || '').trim()
  if (!value) return
  const now = Date.now()
  if (value === lastText && now - lastAt < 2500) return
  lastText = value
  lastAt = now
  emit('scan', value)
}

async function scanBlob(file) {
  if (!file) return
  try {
    const s = createScanner()
    if (running.value) await stop()
    const text = await s.scanFile(file, true)
    onDecoded(text)
  } catch {
    ElMessage.error('图片中未识别到二维码，请对准重拍或换一张更清晰的图')
  }
}

function onNativeFile(ev) {
  const file = ev.target?.files?.[0]
  // allow selecting same file again
  ev.target.value = ''
  scanBlob(file)
}

onMounted(() => {
  createScanner()
})

onBeforeUnmount(async () => {
  await stop()
  scanner = null
})

defineExpose({ start, stop })
</script>

<style scoped>
.scanner {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.reader {
  width: 100%;
  max-width: 420px;
  margin: 0 auto;
  min-height: 48px;
  border-radius: 12px;
  overflow: hidden;
  background: #0f172a;
}
.reader :deep(video) {
  border-radius: 12px;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  align-items: center;
}
.file-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 16px;
  border-radius: 8px;
  background: var(--brand, #0f6e6a);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  border: 1px solid transparent;
  user-select: none;
  min-height: 40px;
}
.file-btn.secondary {
  background: #fff;
  color: var(--ink, #15202b);
  border-color: var(--border, #d0dae2);
}
.file-input {
  display: none;
}
.hint {
  text-align: center;
  font-size: 0.8125rem;
  margin: 0;
}
.warn {
  background: #fff7ed;
  color: #9a3412;
  border: 1px solid #fdba74;
  border-radius: 10px;
  padding: 12px;
  font-size: 0.875rem;
  line-height: 1.5;
}
.warn-body { margin-top: 6px; }
.warn-url {
  margin-top: 8px;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  word-break: break-all;
  color: #7c2d12;
}
.ok-tip {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #6ee7b7;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 0.875rem;
}
code {
  font-size: 0.85em;
  background: rgba(0,0,0,0.06);
  padding: 1px 4px;
  border-radius: 4px;
}

@media (max-width: 480px) {
  .actions {
    align-items: stretch;
  }

  .actions > *,
  .file-btn {
    flex: 1 1 calc(50% - 4px);
    min-height: 44px;
  }

  .reader {
    border-radius: var(--radius-sm);
  }
}
</style>
