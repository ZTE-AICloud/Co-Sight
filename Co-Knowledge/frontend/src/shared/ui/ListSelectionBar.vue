<template>
  <div v-if="count" class="list-selection-bar text-secondary" role="group" :aria-label="$t('public.selection.group')">
    <span>{{ $t('public.selection.prefix') }}<b>{{ count }}</b>{{ $t('public.selection.suffix') }}</span>
    <div class="list-selection-actions">
      <slot />
    </div>
    <el-button link @click="$emit('clear')">{{ $t('public.selection.clear') }}</el-button>
  </div>
</template>

<script setup>
defineProps({ count: { type: Number, default: 0 } })
defineEmits(['clear'])
</script>

<style scoped>
.list-selection-bar { display: flex; align-items: center; gap: 12px 18px; flex-wrap: wrap; padding: 10px 14px; margin-bottom: 12px; border: 1px solid var(--rs-primary-border); border-radius: var(--rs-radius); background: var(--rs-bg-selected); color: var(--rs-text-2); }
.list-selection-bar b { color: var(--rs-primary); font-variant-numeric: tabular-nums; }
.list-selection-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.list-selection-bar > .el-button:last-child { margin-left: auto; color: var(--rs-text-3); }
</style>
