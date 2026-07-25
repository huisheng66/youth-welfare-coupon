<template>
  <el-tag :type="type" size="small" effect="light" round>{{ text }}</el-tag>
</template>

<script setup>
defineProps({
  text: { type: String, required: true },
  type: { type: String, default: 'info' },
})
</script>
