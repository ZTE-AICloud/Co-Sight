<template>
  <el-dialog
    :model-value="modelValue"
    :title="$t('modules.workflow.editPrompt')"
    width="min(860px, calc(100vw - 32px))"
    class="flow-prompt-dialog"
    append-to-body
    :close-on-click-modal="false"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <p class="text-secondary fc-expanded-intro">{{ subtitle }}</p>
    <el-input
      v-model="draft"
      :aria-label="$t('modules.workflow.prompt')"
      type="textarea"
      resize="none"
    />
    <template #footer>
      <span class="text-caption fc-expanded-count">
        {{ $t('modules.workflow.characters', { count: draft.length }) }}
      </span>
      <el-button class="button-compact" @click="cancel">{{ $t('public.cancel') }}</el-button>
      <el-button class="button-compact" type="primary" @click="confirm">
        {{ $t('modules.workflow.doneEditing') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  text: { type: String, default: '' },
  subtitle: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue', 'confirm'])
const draft = ref(props.text || '')

watch(() => [props.modelValue, props.text], () => {
  if (props.modelValue) {
    draft.value = props.text || ''
  }
})

function cancel () {
  emit('update:modelValue', false)
}

function confirm () {
  emit('confirm', draft.value)
  emit('update:modelValue', false)
}
</script>
