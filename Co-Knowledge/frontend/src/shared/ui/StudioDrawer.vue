<template>
  <el-drawer v-model="open" class="studio-drawer text-body" :size="size" append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="closeOnPressEscape" :show-close="showClose">
    <template #header="{ titleId }"><h2 :id="titleId" class="workspace-panel-title text-section-title">{{ title }}</h2></template>
    <slot/>
    <template v-if="$slots.footer" #footer><slot name="footer"/></template>
  </el-drawer>
</template>
<script setup>
defineProps({ title: String, size: { type: String, default: 'min(720px, 100vw)' },
  showClose: { type: Boolean, default: true }, closeOnPressEscape: { type: Boolean, default: true } })
const open = defineModel({ type: Boolean, default: false })
</script>
