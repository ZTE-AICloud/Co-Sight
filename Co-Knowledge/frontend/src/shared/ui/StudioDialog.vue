<template>
  <el-dialog v-model="open" :class="['studio-dialog', dialogClass]" :style="{ '--studio-dialog-width': width }" align-center append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @opened="$emit('opened')">
    <template #header="{ titleId }"><div class="studio-dialog-heading"><span class="studio-dialog-icon"><component :is="icon"/></span><div><h2 :id="titleId">{{ title }}</h2><p class="text-secondary">{{ subtitle }}</p></div></div></template>
    <slot/>
    <template #footer><div class="studio-dialog-footer"><span v-if="hint" class="studio-footer-hint text-caption"><InfoFilled/>{{ hint }}</span><div class="studio-footer-actions"><slot name="actions"/></div></div></template>
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
<style scoped>
/* 没有 hint 时页脚只剩操作按钮：全局 `.studio-dialog-footer` 是 space-between，
   会把它留在左侧，这里推回右端（与有 hint 时的位置一致）。 */
.studio-footer-actions:only-child { margin-inline-start: auto; }
</style>
