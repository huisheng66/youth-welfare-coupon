<template>
  <div class="empty-hint">
    <strong>{{ title }}</strong>
    <div v-if="description">{{ description }}</div>
    <div v-if="$slots.default" style="margin-top:12px">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
})
</script>
