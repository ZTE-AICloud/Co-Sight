<template>
  <main class="cp-page">
    <header class="cp-topbar">
      <RouterLink class="cp-brand" :to="{ name: 'knowledge' }" aria-label="Knowledge Studio">
        <BrandMark /><b>Knowledge Studio</b>
      </RouterLink>
      <button
        type="button"
        class="cp-theme"
        :aria-label="theme === 'dark' ? $t('nav.switchToLight') : $t('nav.switchToDark')"
        :title="theme === 'dark' ? $t('nav.switchToLight') : $t('nav.switchToDark')"
        :aria-pressed="theme === 'dark'"
        @click="toggleTheme"
      >
        <Sunny v-if="theme === 'dark'" /><Moon v-else />
      </button>
    </header>

    <section class="cp-card" aria-labelledby="cp-title">
      <div class="cp-mark"><BrandMark /></div>
      <h1 id="cp-title">{{ $t('modules.auth.changePassword.title') }}</h1>
      <p class="cp-subtitle">{{ $t('modules.auth.changePassword.subtitle') }}</p>
      <ChangePasswordForm @success="onSuccess" />
      <RouterLink v-if="!forced" class="cp-back" :to="{ name: 'knowledge' }">
        {{ $t('modules.auth.changePassword.backToWorkbench') }}
      </RouterLink>
    </section>

    <footer class="cp-footer">© {{ new Date().getFullYear() }} Knowledge Studio</footer>
  </main>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BrandMark from '@/shared/ui/BrandMark.vue'
import { Moon, Sunny } from '@/shared/lib/icons'
import { useTheme } from '@/shared/lib/theme'
import { currentUser } from '@/features/auth/session'
import { safeRedirect } from '@/features/auth/guard'
import ChangePasswordForm from '@/features/auth/components/ChangePasswordForm.vue'

const route = useRoute()
const router = useRouter()
const { theme, toggleTheme } = useTheme()

const forced = computed(() => Boolean(currentUser.value?.mustChangePassword))

function onSuccess () {
  router.replace(safeRedirect(route.query.redirect) || { name: 'knowledge' })
}
</script>

<style scoped>
.cp-page{display:flex;flex-direction:column;min-height:100svh;padding:16px 24px;background:var(--rs-bg-page)}
.cp-topbar{display:flex;align-items:center;justify-content:space-between;max-width:1120px;width:100%;margin:0 auto;height:40px}
.cp-brand{display:flex;align-items:center;gap:10px;color:var(--rs-text);text-decoration:none}
.cp-brand>.brand-mark{width:30px;height:30px}
.cp-brand b{font-size:17px;font-weight:750;letter-spacing:-.4px}
.cp-theme{display:grid;place-items:center;width:30px;height:30px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--rs-text-2)}
.cp-theme:hover{color:var(--rs-primary);background:var(--rs-bg-selected)}
.cp-theme svg{width:17px;height:17px}
.cp-card{width:100%;max-width:420px;margin:auto;padding:36px 36px 32px;border:1px solid var(--rs-border-soft);border-radius:16px;background:var(--rs-bg-card);box-shadow:0 18px 50px color-mix(in srgb,var(--rs-text) 7%,transparent)}
.cp-mark{display:grid;place-items:center;width:48px;height:52px;border:1px solid var(--rs-border);border-radius:12px;background:linear-gradient(145deg,var(--rs-bg-card),var(--rs-bg-selected));margin-bottom:20px}
.cp-mark .brand-mark{width:34px;height:34px}
.cp-card h1{margin:0;font-size:25px;line-height:1.4;font-weight:650;letter-spacing:-.6px;color:var(--rs-text)}
.cp-subtitle{margin:10px 0 26px;color:var(--rs-text-2);font-size:var(--rs-font-size-secondary);line-height:1.75}
.cp-back{display:inline-block;margin-top:22px;color:var(--rs-primary);font-size:var(--rs-font-size-caption);text-decoration:none}
.cp-back:hover{text-decoration:underline;text-underline-offset:3px}
.cp-footer{text-align:center;color:var(--rs-text-3);font-size:10px;padding:14px 0 4px}
@media(max-width:520px){.cp-page{padding:12px 16px}.cp-card{padding:28px 22px 26px}}
@media(prefers-reduced-motion:reduce){.cp-theme{transition:none}}
</style>
