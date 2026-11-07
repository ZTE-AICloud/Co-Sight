<template>
  <section class="fc-operator">
    <header class="fc-operator-heading">
      <button
        type="button"
        class="icon-button"
        :aria-label="collapsed ? $t('modules.workflow.expandOperator', { index: index + 1 }) : $t('modules.workflow.collapseOperator', { index: index + 1 })"
        :aria-expanded="!collapsed"
        @click="$emit('toggle')"
      >
        <ArrowRight v-if="collapsed" />
        <ArrowDown v-else />
      </button>
      <span class="fc-step text-caption">{{ String(index + 1).padStart(2, '0') }}</span>
      <el-select
        v-if="selectable"
        :model-value="operator.operator"
        class="fc-operator-select"
        :aria-label="$t('modules.workflow.operatorType', { index: index + 1 })"
        @update:model-value="$emit('change', $event)"
      >
        <el-option
          v-for="option in options"
          :key="option.id"
          :label="option.label || option.name"
          :value="option.id"
        />
      </el-select>
      <span v-else class="fc-operator-custom text-secondary">{{ operator.operatorName || operator.operator }}</span>
      <div class="fc-order-actions">
        <button
          type="button"
          class="icon-button"
          :disabled="index === 0"
          :aria-label="$t('modules.workflow.moveOperatorUp', { index: index + 1 })"
          @click="$emit('move', -1)"
        >
          <Top />
        </button>
        <button
          type="button"
          class="icon-button"
          :disabled="last"
          :aria-label="$t('modules.workflow.moveOperatorDown', { index: index + 1 })"
          @click="$emit('move', 1)"
        >
          <Bottom />
        </button>
        <button
          type="button"
          class="icon-button danger-icon"
          :disabled="single"
          :aria-label="$t('modules.workflow.deleteOperator', { index: index + 1 })"
          @click="removeOperator"
        >
          <Delete />
        </button>
      </div>
    </header>
    <div v-show="!collapsed" class="fc-operator-body">
      <slot />
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowDown, ArrowRight, Bottom, Delete, Top } from '@/shared/lib/icons'
import { requestDeletion } from '@/shared/composables/deletion'
import { $t } from '@/app/i18n/i18n.js'

const props = defineProps({
  operator: { type: Object, required: true },
  index: { type: Number, required: true },
  options: { type: Array, default: () => [] },
  collapsed: { type: Boolean, default: false },
  last: { type: Boolean, default: false },
  single: { type: Boolean, default: false }
})

const selectable = computed(() => !props.operator.custom && props.options.some(option => option.id === props.operator.operator))

const emit = defineEmits(['toggle', 'move', 'remove', 'change'])

/** 0.1.7：删除算子也走统一确认；参数与提示词只影响当前草稿。 */
async function removeOperator () {
  if (props.single) {
    return
  }
  const confirmed = await requestDeletion({
    resourceType: $t('modules.workflow.resourceOperator'),
    title: $t('modules.workflow.removeOperatorTitle'),
    warning: $t('modules.workflow.removeOperatorWarning'),
    description: $t('modules.workflow.removeOperatorDescription'),
    items: [{
      id: props.operator.id || `operator-${props.index}`,
      name: props.operator.operatorName || props.operator.operator || '--',
      meta: $t('modules.workflow.operatorType', { index: props.index + 1 })
    }],
    verification: false,
    hint: $t('modules.workflow.removeOperatorHint'),
    confirmText: $t('modules.workflow.removeOperatorConfirm')
  })
  if (confirmed) {
    emit('remove')
  }
}
</script>

<style lang="less" scoped>
.fc-operator {
  border: 1px solid var(--rs-border);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 14px;
}
.fc-operator-heading {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 6px 12px;
  background: var(--rs-bg-soft);
  border-bottom: 1px solid var(--rs-border-soft);
}
.fc-step {
  color: var(--rs-text-3);
  font-family: var(--rs-font-family-mono);
}
.fc-operator-select {
  flex: 1;
  min-width: 0;
  :deep(.el-select__wrapper) {
    min-height: 32px;
    background: transparent;
    box-shadow: none;
    padding-left: 4px;
  }
  :deep(.el-select__selected-item) {
    color: var(--rs-text);
    font-weight: 600;
    font-size: var(--rs-font-size-secondary);
  }
}
.fc-operator-custom {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  padding-left: 4px;
}
.fc-order-actions {
  display: flex;
  margin-left: auto;
  flex-shrink: 0;
  button:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }
}
.fc-delete {
  color: var(--rs-danger) !important;
}
.fc-operator-body {
  padding: 12px 20px 0;
  :deep(.el-form-item) {
    margin-bottom: 12px;
  }
  :deep(.el-form-item__label) {
    font-size: var(--rs-font-size-secondary);
    color: var(--rs-text-2);
  }
  :deep(.el-select) {
    width: 100%;
  }
  :deep(.el-input-number) {
    max-width: 100%;
  }
}
@media (max-width: 540px) {
  .fc-operator-body {
    padding: 16px 12px 0;
  }
  .fc-operator-heading {
    padding: 8px;
    gap: 4px;
  }
  .fc-order-actions .icon-button {
    width: 24px;
  }
}
</style>
