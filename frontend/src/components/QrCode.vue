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

async function render() {
  const el = canvas.value
  if (!el || !props.value) return
  const ctx = el.getContext('2d')
  ctx.clearRect(0, 0, props.size, props.size)
  // 券码是敏感凭据，只在本机 canvas 渲染，绝不发往第三方服务
  const mod = await import('qrcode')
  await mod.default.toCanvas(el, props.value, {
    width: props.size,
    margin: 1,
    color: { dark: '#0f172a', light: '#ffffff' },
  })
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
