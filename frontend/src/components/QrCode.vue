<template>
  <canvas ref="canvas" :width="size" :height="size" class="qr"></canvas>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  value: { type: String, required: true },
  size: { type: Number, default: 180 },
})

const canvas = ref(null)

/** Minimal QR-like matrix via external image fallback if canvas fails: draw using API-free simple pattern.
 *  Prefer qrcode lib when available; else draw text-backed placeholder + fetch image.
 */
async function render() {
  const el = canvas.value
  if (!el || !props.value) return
  const ctx = el.getContext('2d')
  ctx.clearRect(0, 0, props.size, props.size)
  try {
    const mod = await import('qrcode')
    await mod.default.toCanvas(el, props.value, {
      width: props.size,
      margin: 1,
      color: { dark: '#0f172a', light: '#ffffff' },
    })
  } catch {
    // Fallback: use public QR image service (dev convenience)
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      ctx.drawImage(img, 0, 0, props.size, props.size)
    }
    img.src = `https://api.qrserver.com/v1/create-qr-code/?size=${props.size}x${props.size}&data=${encodeURIComponent(props.value)}`
  }
}

onMounted(render)
watch(() => props.value, render)
</script>

<style scoped>
.qr {
  display: block;
  margin: 0 auto;
  border-radius: 8px;
  background: #fff;
}
</style>
