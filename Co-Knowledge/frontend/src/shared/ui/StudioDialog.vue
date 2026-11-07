<template>
  <el-dialog v-model="open" :class="['studio-dialog', dialogClass]" :style="{ '--studio-dialog-width': width }" align-center append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @opened="$emit('opened')">
    <template #header="{ titleId }"><div class="studio-dialog-heading"><span class="studio-dialog-icon"><component :is="icon"/></span><div><h2 :id="titleId">{{ title }}</h2><p class="text-secondary">{{ subtitle }}</p></div></div></template>
    <slot/>
    <template #footer><div class="studio-dialog-footer"><span class="studio-footer-hint text-caption"><InfoFilled/>{{ hint }}</span><div class="studio-footer-actions"><slot name="actions"/></div></div></template>
  </el-dialog>
</template>
<script setup>
import { InfoFilled } from '@element-plus/icons-vue'
// busy：提交/测试请求在飞时禁止 ESC / 右上角关闭，避免「关掉再打开」把旧请求的
// 结果写进新会话（session token 仍会兜底丢弃，但先不让用户制造这个竞态）。
defineProps({ title: String, subtitle: String, icon: [Object, Function], hint: String, width: { type: String, default: '760px' }, dialogClass: String, busy: Boolean })
defineEmits(['opened'])
const open = defineModel({ type: Boolean, default: false })
</script>
