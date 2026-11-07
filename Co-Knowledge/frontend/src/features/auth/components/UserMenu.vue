<template>
  <el-popover
    v-model:visible="open"
    placement="top-start"
    trigger="click"
    :width="212"
    :offset="10"
    popper-class="user-menu-popover"
  >
    <template #reference>
      <button
        type="button"
        class="user-trigger"
        :aria-label="displayName"
        :title="displayName"
        :aria-expanded="open"
      >
        <span class="user-avatar" aria-hidden="true">{{ initials }}</span>
      </button>
    </template>
    <div class="user-panel">
      <div class="user-head">
        <span class="user-avatar user-avatar--lg" aria-hidden="true">{{ initials }}</span>
        <div class="user-head-copy">
          <b>{{ displayName }}</b>
          <small>{{ username }}</small>
        </div>
      </div>
      <button type="button" class="user-item" @click="openPassword">
        <Key aria-hidden="true" />{{ $t('modules.auth.userMenu.changePassword') }}
      </button>
      <button type="button" class="user-item user-item--danger" @click="logout">
        <SwitchButton aria-hidden="true" />{{ $t('modules.auth.userMenu.logout') }}
      </button>
    </div>
  </el-popover>

  <el-dialog
    v-model="passwordOpen"
    :title="$t('modules.auth.changePassword.title')"
    width="420px"
    align-center
  >
    <ChangePasswordForm @success="passwordOpen = false" />
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { Key, SwitchButton } from '@/shared/lib/icons'
import { $t as translate } from '@/app/i18n/i18n.js'
import message from '@/shared/lib/message'
import { currentUser, signOut } from '@/features/auth/session'
import ChangePasswordForm from '@/features/auth/components/ChangePasswordForm.vue'

const router = useRouter()
const open = ref(false)
const passwordOpen = ref(false)

const username = computed(() => currentUser.value?.username || '')
const displayName = computed(() => currentUser.value?.displayName || username.value)
const initials = computed(() => (displayName.value || '?').slice(0, 1).toUpperCase())

function openPassword () {
  open.value = false
  passwordOpen.value = true
}

async function logout () {
  open.value = false
  await signOut()
  message.success(translate('modules.auth.userMenu.logoutSuccess'))
  router.replace({ name: 'login' })
}
</script>

<style scoped>
.user-trigger{border:0;background:transparent;width:28px;height:30px;display:inline-flex;align-items:center;justify-content:center;border-radius:5px;padding:4px}
.user-trigger:hover{background:var(--rs-bg-selected)}
.user-avatar{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--rs-primary);color:#fff;font-size:11px;font-weight:650;line-height:1;text-transform:uppercase}
.user-avatar--lg{width:32px;height:32px;font-size:14px}
.user-panel{padding:2px}
.user-head{display:flex;align-items:center;gap:10px;padding:4px 6px 11px;border-bottom:1px solid var(--rs-border-soft);margin-bottom:6px}
.user-head-copy{min-width:0}
.user-head-copy b{display:block;font-size:13px;color:var(--rs-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.user-head-copy small{display:block;font-size:11px;color:var(--rs-text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.user-item{display:flex;align-items:center;gap:8px;width:100%;padding:8px 8px;border:0;border-radius:6px;background:transparent;color:var(--rs-text-2);font-size:13px;text-align:left}
.user-item:hover{background:var(--rs-bg-hover);color:var(--rs-primary)}
.user-item svg{width:15px;height:15px}
.user-item--danger:hover{color:var(--rs-danger);background:color-mix(in srgb,var(--rs-danger) 8%,transparent)}
</style>
