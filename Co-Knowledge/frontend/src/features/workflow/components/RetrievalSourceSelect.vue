<!-- 知识来源下拉（0.1.10）：按来源类型给标签与状态，只列当前类型可用的库。 -->
<template>
  <div class="retrieval-source-picker">
    <el-select
      v-model="selected"
      multiple
      filterable
      clearable
      collapse-tags
      collapse-tags-tooltip
      :max-collapse-tags="2"
      :aria-label="label || $t('modules.studioDialogs.createWorkflow.source')"
      :placeholder="$t('modules.studioDialogs.createWorkflow.sourcePlaceholderFor', { kind: kindName })"
      popper-class="retrieval-source-popper"
      :fit-input-width="true"
    >
      <template #prefix>
        <component :is="kind.icon" class="retrieval-select-icon" />
      </template>
      <el-option
        v-for="option in options"
        :key="option.id"
        :value="option.id"
        :label="option.name"
        :disabled="Boolean(option.disabled)"
      >
        <div class="retrieval-option-heading">
          <span class="retrieval-option-name">{{ option.name }}</span>
          <span :class="['tag-soft', kind.tone]">{{ $t(kind.shortKey) }}</span>
          <span :class="['retrieval-option-status', { ready: !option.disabled }]">{{ option.statusLabel || '' }}</span>
        </div>
        <div v-if="option.description" class="retrieval-option-description text-caption">{{ option.description }}</div>
      </el-option>
      <template #empty>
        <div class="retrieval-source-empty text-secondary">
          {{ options.length ? $t('modules.studioDialogs.createWorkflow.sourceFilteredEmpty') : $t('modules.studioDialogs.createWorkflow.sourceNone', { kind: kindName }) }}
        </div>
      </template>
    </el-select>
    <p class="retrieval-source-help text-caption">
      {{ $t('modules.studioDialogs.createWorkflow.sourceAvailable', { count: availableCount, kind: kindName }) }}<span v-if="unavailableCount">{{ $t('modules.studioDialogs.createWorkflow.sourceUnavailable', { count: unavailableCount }) }}</span>
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Document, Share, Coin } from '@element-plus/icons-vue'
import { $t } from '@/app/i18n/i18n.js'
import { sourceKindMeta } from '@/features/workflow/lib/retrievalSources'

const props = defineProps({
  /** 来源类型：knowledge / graph / database */
  sourceType: { type: String, default: 'knowledge' },
  /** 当前类型可选的来源：{ id, name, statusLabel, disabled, description } */
  options: { type: Array, default: () => [] },
  label: { type: String, default: '' }
})
const selected = defineModel({ type: Array, default: () => [] })

const KIND_ICONS = { knowledge: Document, graph: Share, database: Coin }
const meta = computed(() => sourceKindMeta(props.sourceType))
const kind = computed(() => ({ ...meta.value, icon: KIND_ICONS[meta.value.id] || Document }))
const kindName = computed(() => $t(meta.value.labelKey))
const availableCount = computed(() => props.options.filter(option => !option.disabled).length)
const unavailableCount = computed(() => props.options.length - availableCount.value)
</script>

<style>
.retrieval-source-picker { width: 100%; min-width: 0; }
.retrieval-select-icon { width: 16px; height: 16px; color: var(--rs-primary); }
.retrieval-source-help { margin: 7px 0 0; color: var(--rs-text-3); line-height: 1.6; }
.retrieval-source-popper { max-width: calc(100vw - 24px); }
.retrieval-source-popper .el-select-dropdown__item { height: auto; min-height: 60px; padding: 9px 14px; line-height: 1.5; }
.retrieval-option-heading { display: flex; align-items: center; gap: 8px; min-width: 0; }
.retrieval-option-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.retrieval-option-heading .tag-soft { flex-shrink: 0; font-size: 11px; padding: 1px 6px; }
.retrieval-option-status { flex-shrink: 0; color: var(--rs-text-3); font-size: var(--rs-font-size-caption); font-weight: 400; }
.retrieval-option-status.ready { color: var(--rs-success); }
.retrieval-option-description { overflow: hidden; text-overflow: ellipsis; color: var(--rs-text-3); margin-top: 4px; font-weight: 400; }
.retrieval-source-popper .is-disabled .retrieval-option-name { color: var(--rs-text-3); }
.retrieval-source-empty { white-space: normal; text-align: center; padding: 20px; line-height: 1.7; color: var(--rs-text-3); }
</style>
