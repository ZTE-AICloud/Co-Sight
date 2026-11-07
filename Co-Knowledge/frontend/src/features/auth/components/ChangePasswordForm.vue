<template>
  <form class="cp-form" novalidate @submit.prevent="submit">
    <div class="cp-field">
      <label for="cp-current">{{ $t('modules.auth.changePassword.current') }}</label>
      <input
        id="cp-current" v-model="currentPassword" type="password" autocomplete="current-password"
        :placeholder="$t('modules.auth.changePassword.currentPlaceholder')"
        :aria-invalid="!!errors.current" :aria-describedby="errors.current ? 'cp-current-error' : undefined"
        :disabled="submitting" @input="errors.current = ''"
      >
      <p v-if="errors.current" id="cp-current-error" class="cp-error" role="alert">{{ errors.current }}</p>
    </div>
    <div class="cp-field">
      <label for="cp-new">{{ $t('modules.auth.changePassword.next') }}</label>
      <input
        id="cp-new" v-model="newPassword" type="password" autocomplete="new-password"
        :placeholder="$t('modules.auth.changePassword.nextPlaceholder')"
        :aria-invalid="!!errors.next" :aria-describedby="errors.next ? 'cp-new-error' : undefined"
        :disabled="submitting" @input="errors.next = ''"
      >
      <p v-if="errors.next" id="cp-new-error" class="cp-error" role="alert">{{ errors.next }}</p>
    </div>
    <div class="cp-field">
      <label for="cp-confirm">{{ $t('modules.auth.changePassword.confirm') }}</label>
      <input
        id="cp-confirm" v-model="confirmPassword" type="password" autocomplete="new-password"
        :placeholder="$t('modules.auth.changePassword.confirmPlaceholder')"
        :aria-invalid="!!errors.confirm" :aria-describedby="errors.confirm ? 'cp-confirm-error' : undefined"
        :disabled="submitting" @input="errors.confirm = ''"
      >
      <p v-if="errors.confirm" id="cp-confirm-error" class="cp-error" role="alert">{{ errors.confirm }}</p>
    </div>
    <p v-if="errors.form" class="cp-error cp-form-error" role="alert">{{ errors.form }}</p>
    <button type="submit" class="cp-submit" :disabled="submitting">
      {{ submitting ? $t('modules.auth.changePassword.submitting') : $t('modules.auth.changePassword.submit') }}
    </button>
  </form>
</template>

<script setup>
import { reactive, ref } from 'vue'

import { $t as translate } from '@/app/i18n/i18n.js'
import message from '@/shared/lib/message'
import { changePassword } from '@/features/auth/session'

const emit = defineEmits(['success'])

const PASSWORD_MIN = 8
const PASSWORD_MAX = 128

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const submitting = ref(false)
const errors = reactive({ current: '', next: '', confirm: '', form: '' })

function validate () {
  errors.current = currentPassword.value
    ? ''
    : translate('modules.auth.changePassword.currentPlaceholder')
  errors.next = newPassword.value
    ? ''
    : translate('modules.auth.changePassword.nextPlaceholder')
  if (!errors.next
      && (newPassword.value.length < PASSWORD_MIN || newPassword.value.length > PASSWORD_MAX)) {
    errors.next = translate('modules.auth.changePassword.policy')
  }
  if (!confirmPassword.value) {
    errors.confirm = translate('modules.auth.changePassword.confirmPlaceholder')
  } else {
    errors.confirm = confirmPassword.value === newPassword.value
      ? ''
      : translate('modules.auth.changePassword.mismatch')
  }
  errors.form = ''
  return !errors.current && !errors.next && !errors.confirm
}

function mapError (error) {
  const detail = error?.detail || ''
  switch (error?.code) {
    case 'invalid_current_password':
      errors.current = detail || translate('modules.auth.changePassword.wrongCurrent')
      break
    case 'password_policy':
      errors.next = detail || translate('modules.auth.changePassword.policy')
      break
    case 'login_rate_limited':
    case 'rate_limited':
      errors.form = detail || translate('modules.auth.login.rateLimited')
      break
    default:
      errors.form = detail || translate('modules.auth.login.serviceUnavailable')
  }
}

async function submit () {
  if (submitting.value || !validate()) {
    return
  }
  submitting.value = true
  try {
    await changePassword(currentPassword.value, newPassword.value)
    message.success(translate('modules.auth.changePassword.success'))
    emit('success')
  } catch (error) {
    mapError(error)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.cp-form{display:flex;flex-direction:column;gap:18px}
.cp-field>label{display:block;font-size:var(--rs-font-size-secondary);font-weight:550;margin-bottom:9px;color:var(--rs-text)}
.cp-field>input{width:100%;height:44px;border:1px solid var(--rs-border);border-radius:7px;background:var(--rs-bg-card);color:var(--rs-text);font-size:var(--rs-font-size-secondary);padding:0 13px;outline:0;transition:border-color .18s,box-shadow .18s}
.cp-field>input:hover{border-color:var(--rs-primary-border)}
.cp-field>input:focus{border-color:var(--rs-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--rs-primary) 9%,transparent)}
.cp-field>input:disabled{opacity:.65;cursor:wait}
.cp-field>input[aria-invalid='true']{border-color:var(--rs-danger)}
.cp-error{color:var(--rs-danger);font-size:var(--rs-font-size-caption);line-height:1.5;margin:7px 0 -3px}
.cp-form-error{margin:-4px 0 0}
.cp-submit{height:46px;border:1px solid #1677ff;border-radius:7px;background:linear-gradient(100deg,#2585ff,#1670f0);color:#fff;font-size:var(--rs-font-size-body);font-weight:550;transition:background .18s,box-shadow .18s;box-shadow:0 4px 10px #1677ff15}
.cp-submit:hover:not(:disabled){background:linear-gradient(100deg,#4096ff,#2585ff);box-shadow:0 5px 15px #1677ff28}
.cp-submit:disabled{opacity:.7;cursor:wait}
@media(prefers-reduced-motion:reduce){.cp-field>input,.cp-submit{transition:none}}
</style>
