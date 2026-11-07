<template>
  <div class="delete-confirm-verification">
    <div class="delete-confirm-label">
      <label :for="inputId" class="text-secondary text-label">{{ $t('public.deleteConfirm.verifyLabel') }}</label>
      <span class="text-caption">{{ $t('public.deleteConfirm.verifyDigits') }}</span>
    </div>
    <div class="delete-confirm-code-row">
      <el-input
        :id="inputId"
        ref="codeInput"
        v-model="answer"
        :aria-label="$t('public.deleteConfirm.verifyLabel')"
        :aria-describedby="helpId"
        :aria-invalid="hasError"
        :class="{ 'is-invalid': hasError }"
        inputmode="numeric"
        autocomplete="off"
        maxlength="4"
        :placeholder="$t('public.deleteConfirm.verifyPlaceholder')"
        @blur="touched = true"
        @input="touched = false"
        @keyup.enter="$emit('submit')"
      >
        <template #prefix>
          <Lock />
        </template>
        <template #suffix>
          <CircleCheck v-if="isVerified" class="delete-confirm-verified" />
        </template>
      </el-input>
      <div class="delete-confirm-challenge">
        <code :aria-label="$t('public.deleteConfirm.challenge')">{{ challenge }}</code>
        <button
          type="button"
          :aria-label="$t('public.deleteConfirm.refreshCode')"
          :title="$t('public.deleteConfirm.refreshCode')"
          @click="refreshCode(true)"
        >
          <RefreshRight />
        </button>
      </div>
    </div>
    <p
      :id="helpId"
      :class="['delete-confirm-help', 'text-caption', { 'has-error': hasError, 'is-verified': isVerified }]"
      aria-live="polite"
    >
      {{ hasError ? $t('public.deleteConfirm.verifyError') : isVerified ? $t('public.deleteConfirm.verifyOk') : $t('public.deleteConfirm.verifyHint') }}
    </p>
  </div>
</template>

<script setup>
// 删除操作的 4 位本地确认码（防误操作，不是安全认证）。
// 抽成组件供全局 DeleteConfirmDialog 与目录删除弹窗共用，避免两份实现漂移。
import { computed, ref, useId, watch } from 'vue'
import { Lock, CircleCheck, RefreshRight } from '@element-plus/icons-vue'
import { $t } from '@/app/i18n/i18n.js'

const emit = defineEmits(['update:verified', 'submit'])
const codeInput = ref()
const answer = ref('')
const challenge = ref('')
const touched = ref(false)
const inputId = useId()
const helpId = useId()

const isVerified = computed(() => challenge.value.length === 4 && answer.value === challenge.value)
const hasError = computed(() => !isVerified.value && answer.value.length > 0 && (touched.value || answer.value.length === 4))

function refreshCode (focus = false) {
  const next = String(Math.floor(Math.random() * 9000) + 1000)
  challenge.value = next === challenge.value
    ? String(1000 + (Number(next) - 999) % 9000)
    : next
  answer.value = ''
  touched.value = false
  if (focus) {
    codeInput.value?.focus()
  }
}

watch(isVerified, value => emit('update:verified', value), { immediate: true })

refreshCode()

defineExpose({
  focus: () => codeInput.value?.focus(),
  reset: () => refreshCode(),
  isVerified
})
</script>
