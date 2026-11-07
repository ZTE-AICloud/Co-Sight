<template>
  <main class="login-page">
    <section class="login-story" aria-labelledby="login-story-title">
      <RouterLink class="login-brand" to="/login">
        <BrandMark /><span><b>Knowledge Studio</b><small>{{ $t('brand.subtitle') }}</small></span>
      </RouterLink>
      <div class="login-story-content">
        <div class="story-eyebrow">
          <span /> YOUR KNOWLEDGE. CONNECTED.
        </div>
        <h1 id="login-story-title">
          {{ $t('modules.auth.login.storyTitleLead') }}<br><em>{{ $t('modules.auth.login.storyTitleAccent') }}</em>
        </h1>
        <p class="story-description">
          {{ $t('modules.auth.login.storyLine1') }}<br>{{ $t('modules.auth.login.storyLine2') }}
        </p>
        <LoginIllustration />
      </div>
      <div class="story-footer">
        <span><FolderOpened /> {{ $t('modules.auth.login.featureManage') }}</span><i /><span><Connection /> {{ $t('modules.auth.login.featureOrchestrate') }}</span><i /><span><ChatDotRound /> {{ $t('modules.auth.login.featureChat') }}</span>
      </div>
    </section>

    <section class="login-main" aria-labelledby="login-title">
      <header class="login-topbar">
        <RouterLink class="login-mobile-brand" to="/login">
          <BrandMark /><b>Knowledge Studio</b>
        </RouterLink>
        <el-popover
          v-model:visible="languageOpen"
          placement="bottom-end"
          trigger="click"
          :width="176"
          :offset="8"
          popper-class="login-language-popover"
        >
          <template #reference>
            <button
              type="button"
              class="login-language"
              :title="$t('nav.switchLanguage')"
              :aria-expanded="languageOpen"
              aria-controls="login-language-options"
            >
              <GlobeIcon /><span>{{ isZh ? $t('nav.langZh') : $t('nav.langEn') }}</span>
            </button>
          </template>
          <div id="login-language-options" class="login-language-options" role="group" :aria-label="$t('nav.interfaceLanguage')">
            <button
              type="button"
              :class="['login-language-option', { 'is-current': isZh }]"
              :aria-label="isZh ? $t('nav.langZhCurrent') : $t('nav.langZh')"
              @click="selectLanguage('zh-CN')"
            >
              <span>{{ $t('nav.langZh') }}</span><Check v-if="isZh" aria-hidden="true" />
            </button>
            <button
              type="button"
              :class="['login-language-option', { 'is-current': !isZh }]"
              :aria-label="!isZh ? $t('nav.langEnCurrent') : $t('nav.langEn')"
              @click="selectLanguage('en-US')"
            >
              <span>{{ $t('nav.langEn') }}</span><Check v-if="!isZh" aria-hidden="true" />
            </button>
          </div>
        </el-popover>
        <span class="topbar-divider" />
        <button
          type="button" class="login-theme" :aria-label="theme === 'dark' ? $t('nav.switchToLight') : $t('nav.switchToDark')" :title="theme === 'dark' ? $t('nav.switchToLight') : $t('nav.switchToDark')" :aria-pressed="theme === 'dark'"
          @click="toggleTheme"
        >
          <Sunny v-if="theme === 'dark'" /><Moon v-else />
        </button>
      </header>

      <div class="login-form-area">
        <div class="login-welcome-mark">
          <BrandMark />
        </div>
        <div class="login-overline">
          WELCOME TO YOUR WORKSPACE
        </div>
        <h2 id="login-title">
          {{ $t('modules.auth.login.welcomeTitle') }}
        </h2>
        <p class="login-subtitle">
          {{ $t('modules.auth.login.welcomeSubtitle') }}
        </p>

        <div v-if="authUnavailable" class="login-unavailable" role="alert">
          <h3>{{ $t('modules.auth.login.unavailableTitle') }}</h3>
          <p>{{ $t('modules.auth.login.unavailableBody') }}</p>
          <button type="button" class="login-demo-button" @click="retryStatus">
            {{ $t('modules.auth.login.retry') }}<Right />
          </button>
        </div>

        <template v-else>
          <p v-if="mode === 'none'" class="login-mode-note">
            {{ $t('modules.auth.login.notEnabled') }}
          </p>
          <p v-else-if="mode === 'gateway'" class="login-mode-note">
            {{ $t('modules.auth.login.gatewayNotice') }}
          </p>
          <p v-else-if="mode === 'local' && !authState.initialized" class="login-mode-note login-mode-note--error">
            {{ $t('modules.auth.login.unavailableBody') }}
          </p>

          <form class="login-form" novalidate @submit.prevent="submitLogin">
            <div class="login-field">
              <label for="login-account">{{ $t('modules.auth.login.accountLabel') }}</label>
              <div :class="['login-input', { 'has-error': errors.account }]">
                <User aria-hidden="true" />
                <input
                  id="login-account" ref="accountInput" v-model="account" name="username" autocomplete="username"
                  :placeholder="$t('modules.auth.login.accountPlaceholder')" :aria-invalid="!!errors.account" :aria-describedby="errors.account ? 'login-account-error' : undefined" :disabled="submitting || !formEnabled" @input="errors.account = ''"
                >
              </div>
              <p v-if="errors.account" id="login-account-error" class="login-error" role="alert">
                {{ errors.account }}
              </p>
            </div>
            <div class="login-field">
              <label for="login-password">{{ $t('modules.auth.login.passwordLabel') }}</label>
              <div :class="['login-input', { 'has-error': errors.password }]">
                <Lock aria-hidden="true" />
                <input
                  id="login-password" ref="passwordInput" v-model="password" :type="showPassword ? 'text' : 'password'" name="password"
                  autocomplete="current-password" :placeholder="$t('modules.auth.login.passwordPlaceholder')" :aria-invalid="!!errors.password" :aria-describedby="errors.password ? 'login-password-error' : undefined" :disabled="submitting || !formEnabled"
                  @input="errors.password = ''"
                >
                <button type="button" class="password-toggle" :aria-label="showPassword ? $t('modules.auth.login.hidePassword') : $t('modules.auth.login.showPassword')" :aria-pressed="showPassword" @click="showPassword = !showPassword">
                  <Hide v-if="showPassword" /><View v-else />
                </button>
              </div>
              <p v-if="errors.password" id="login-password-error" class="login-error" role="alert">
                {{ errors.password }}
              </p>
            </div>
            <div class="login-options">
              <label class="remember-account"><input v-model="rememberAccount" type="checkbox" :disabled="submitting || !formEnabled"><span>{{ $t('modules.auth.login.remember') }}</span></label><button type="button" class="login-text-button" @click="helpOpen = true">
                {{ $t('modules.auth.login.forgot') }}
              </button>
            </div>
            <p v-if="formError" class="login-error login-form-error" role="alert">
              {{ formError }}
            </p>
            <button type="submit" class="login-submit" :disabled="submitting || !formEnabled">
              <span v-if="submitting" class="login-spinner" aria-hidden="true" />{{ submitting ? $t('modules.auth.login.submitting') : $t('modules.auth.login.submit') }}<Right v-if="!submitting" />
            </button>
            <p v-if="mode !== 'local'" class="login-demo-note">
              <InfoFilled /> {{ $t('modules.auth.login.demoNote') }}
            </p>
          </form>

          <template v-if="mode === 'none'">
            <div class="login-divider">
              <span>{{ $t('modules.auth.login.previewPrompt') }}</span>
            </div>
            <button type="button" class="login-demo-button" :disabled="submitting" @click="enterWorkspace">
              <Compass /> {{ $t('modules.auth.login.enterWorkspace') }}<Right />
            </button>
          </template>
          <template v-else-if="mode === 'gateway' && appState.loginUrl">
            <div class="login-divider">
              <span>{{ $t('modules.auth.login.unifiedAuth') }}</span>
            </div>
            <button type="button" class="login-demo-button" @click="goGateway">
              <Compass /> {{ $t('modules.auth.login.goGateway') }}<Right />
            </button>
          </template>

          <p class="login-support">
            {{ $t('modules.auth.login.noAccount') }}<button type="button" class="login-text-button" @click="helpOpen = true">
              {{ $t('modules.auth.login.contactAdmin') }}<TopRight />
            </button>
          </p>
        </template>
      </div>

      <footer class="login-footer">
        <span>© {{ new Date().getFullYear() }} Knowledge Studio</span><span class="login-footer-dot">·</span><span>{{ $t('modules.auth.login.footerTagline') }}</span>
      </footer>
    </section>

    <el-dialog v-model="helpOpen" :title="$t('modules.auth.login.helpTitle')" width="420px" class="login-help-dialog" align-center>
      <div class="login-help-content">
        <span class="login-help-icon"><User /></span><h3>{{ $t('modules.auth.login.contactAdmin') }}</h3><p>{{ $t('modules.auth.login.helpBody') }}</p><div v-if="mode !== 'local'" class="login-help-demo">
          <InfoFilled /><p>{{ $t('modules.auth.login.helpDemo') }}</p>
        </div>
      </div>
      <template #footer>
        <el-button @click="helpOpen = false">
          {{ $t('public.confirm') }}
        </el-button><el-button v-if="mode === 'none'" type="primary" @click="enterWorkspace">
          {{ $t('modules.auth.login.enterWorkspace') }}<Right />
        </el-button>
      </template>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Check, TopRight, ChatDotRound, Compass, Connection, FolderOpened, Hide, InfoFilled, Lock, Moon, Right, Sunny, User, View } from '@/shared/lib/icons'
import BrandMark from '@/shared/ui/BrandMark.vue'
import LoginIllustration from '@/shared/ui/LoginIllustration.vue'
import { GlobeIcon } from '@/shared/ui/icons'
import { isChineseLanguage, switchLanguage } from '@/shared/lib/language'
import { useTheme } from '@/shared/lib/theme'
import appState from '@/app/state'
import { $t as translate } from '@/app/i18n/i18n.js'
import message from '@/shared/lib/message'
import { authState, ensureStatus, signIn } from '@/features/auth/session'
import { safeRedirect } from '@/features/auth/guard'

const route = useRoute()
const router = useRouter()
const { theme, toggleTheme } = useTheme()
const rememberedAccountKey = 'rag-studio-remembered-account'
let savedAccount = ''
try {
  savedAccount = localStorage.getItem(rememberedAccountKey) || ''
} catch {
  // The form also works without browser storage.
}
const account = ref(savedAccount)
const password = ref('')
const rememberAccount = ref(!!savedAccount)
const showPassword = ref(false)
const submitting = ref(false)
const helpOpen = ref(false)
const authUnavailable = ref(false)
const formError = ref('')
const accountInput = ref(null)
const passwordInput = ref(null)
const errors = reactive({ account: '', password: '' })
const languageOpen = ref(false)

// 语言判定与切换走 `@/shared/lib/language`（与左栏偏好设置同源）。
const isZh = isChineseLanguage()

function selectLanguage (language) {
  languageOpen.value = false
  switchLanguage(language)
}

const mode = computed(() => authState.mode)
const formEnabled = computed(() => mode.value === 'local' && authState.initialized)

function focusField (field) {
  ;(field === 'account' ? accountInput : passwordInput).value?.focus()
}

async function loadStatus (force = false) {
  try {
    await ensureStatus({ force })
    authUnavailable.value = false
  } catch {
    authUnavailable.value = true
  }
}

function retryStatus () {
  formError.value = ''
  loadStatus(true)
}

function rememberAccountValue () {
  try {
    if (rememberAccount.value) {
      localStorage.setItem(rememberedAccountKey, account.value.trim())
    } else {
      localStorage.removeItem(rememberedAccountKey)
    }
  } catch {
    // Remembering the account is optional. Passwords are never stored.
  }
}

function mapLoginError (error) {
  const detail = error?.detail || ''
  switch (error?.code) {
    case 'invalid_credentials':
      errors.password = detail || translate('modules.auth.login.invalidCredentials')
      focusField('password')
      break
    case 'account_disabled':
      formError.value = detail || translate('modules.auth.login.accountDisabled')
      break
    case 'login_rate_limited':
    case 'rate_limited':
      formError.value = detail || translate('modules.auth.login.rateLimited')
      break
    case 'auth_not_initialized':
    case 'service_unavailable':
      formError.value = detail || translate('modules.auth.login.serviceUnavailable')
      break
    case 'auth_not_enabled':
      formError.value = detail || translate('modules.auth.login.notEnabled')
      break
    default:
      formError.value = detail || translate('public.networkError')
  }
}

async function submitLogin () {
  if (submitting.value || !formEnabled.value) {
    return
  }
  errors.account = account.value.trim() ? '' : translate('modules.auth.login.accountPlaceholder')
  errors.password = password.value.trim() ? '' : translate('modules.auth.login.passwordPlaceholder')
  formError.value = ''
  if (errors.account || errors.password) {
    focusField(errors.account ? 'account' : 'password')
    return
  }
  rememberAccountValue()
  submitting.value = true
  try {
    const user = await signIn(account.value.trim(), password.value)
    message.success(translate('modules.auth.login.success'))
    const target = safeRedirect(route.query.redirect)
    if (user?.mustChangePassword) {
      router.replace(target
        ? { name: 'changePassword', query: { redirect: target } }
        : { name: 'changePassword' })
    } else {
      router.replace(target || { name: 'knowledge' })
    }
  } catch (error) {
    mapLoginError(error)
  } finally {
    submitting.value = false
  }
}

function enterWorkspace () {
  helpOpen.value = false
  router.replace({ name: 'knowledge' })
}

function goGateway () {
  if (appState.loginUrl) {
    window.location.assign(appState.loginUrl)
  }
}

onMounted(() => {
  loadStatus()
})
</script>

<style scoped>
.login-page{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,1fr);min-height:100svh;padding:16px;background:var(--rs-bg-page)}
.login-story{position:relative;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--rs-border-soft);border-radius:18px;padding:31px 40px 30px;background:radial-gradient(ellipse at 90% 72%,color-mix(in srgb,var(--rs-primary) 7%,transparent),transparent 65%),linear-gradient(145deg,var(--rs-bg-soft),var(--rs-bg-selected));min-height:820px}
.login-story::after{content:'';position:absolute;inset:0;z-index:0;pointer-events:none;opacity:.45;background-image:radial-gradient(var(--rs-primary-border) .7px,transparent .7px);background-size:22px 22px;mask-image:linear-gradient(180deg,transparent 24%,#000 75%,transparent 100%)}
.login-brand{display:flex;align-items:center;gap:12px;color:var(--rs-text);align-self:flex-start;position:relative;z-index:1}
.login-brand>.brand-mark{width:40px;height:40px}
.login-brand b{display:block;font-size:22px;font-weight:750;letter-spacing:-.6px}
.login-brand small{display:block;font-size:9px;color:var(--rs-text-3);margin-top:3px;letter-spacing:.15px}
.login-story-content{position:relative;z-index:1;display:flex;flex-direction:column;justify-content:center;flex:1;max-width:560px;width:100%;margin:36px auto 22px}
.story-eyebrow{display:flex;align-items:center;gap:9px;font-size:10px;font-weight:600;letter-spacing:2.1px;color:var(--rs-primary);margin-bottom:22px}
.story-eyebrow>span{width:18px;height:2px;background:var(--rs-primary)}
.login-story h1{margin:0;font-size:46px;font-weight:650;letter-spacing:-1.5px;line-height:1.45}
.login-story h1 em{font-style:normal;color:var(--rs-primary)}
.story-description{font-size:var(--rs-font-size-secondary);line-height:1.95;color:var(--rs-text-2);margin:20px 0 32px}
.knowledge-illustration{margin-left:-12px}
.story-footer{display:flex;align-items:center;justify-content:center;gap:19px;position:relative;z-index:1;color:var(--rs-text-2);font-size:10px;white-space:nowrap}
.story-footer>span{display:flex;align-items:center;gap:7px}
.story-footer svg{width:14px;height:14px;color:var(--rs-primary)}
.story-footer>i{width:1px;height:11px;background:var(--rs-primary-border)}
.login-main{display:flex;flex-direction:column;min-width:0;padding:15px 32px 10px}
.login-topbar{display:flex;align-items:center;justify-content:flex-end;gap:18px;height:34px}
.login-language{display:flex;align-items:center;gap:7px;padding:4px 6px;margin-right:-6px;border:0;border-radius:6px;background:transparent;color:var(--rs-text-2);font-size:var(--rs-font-size-caption)}
.login-language:hover{color:var(--rs-primary);background:var(--rs-bg-selected)}
.login-language svg{width:15px;height:15px}
.login-language-options{display:flex;flex-direction:column;gap:4px}
.login-language-option{width:100%;height:34px;padding:0 9px;border:0;border-radius:6px;display:flex;align-items:center;justify-content:space-between;background:transparent;color:var(--rs-text-2);font-size:var(--rs-font-size-secondary);text-align:left}
.login-language-option:hover{background:var(--rs-bg-soft)}
.login-language-option.is-current{color:var(--rs-primary);background:var(--rs-bg-selected)}
.login-language-option svg{width:15px;height:15px}
.topbar-divider{height:13px;width:1px;background:var(--rs-border)}
.login-theme{display:grid;place-items:center;width:30px;height:30px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--rs-text-2)}
.login-theme:hover{color:var(--rs-primary);background:var(--rs-bg-selected)}
.login-theme svg{width:17px;height:17px}
.login-mobile-brand{display:none}
.login-form-area{width:100%;max-width:380px;margin:auto; padding:50px 0 42px}
.login-welcome-mark{display:grid;place-items:center;width:51px;height:54px;border:1px solid var(--rs-border);border-radius:13px;background:linear-gradient(145deg,var(--rs-bg-card),var(--rs-bg-selected));margin-bottom:25px}
.login-welcome-mark .brand-mark{width:38px;height:38px}
.login-overline{font-size:9px;letter-spacing:1.7px;font-weight:550;color:var(--rs-text-3);margin-bottom:12px}
.login-form-area h2{font-size:28px;line-height:1.4;font-weight:650;letter-spacing:-.8px;margin:0;text-wrap:balance}
.login-subtitle{font-size:var(--rs-font-size-secondary);color:var(--rs-text-2);margin:12px 0 33px;line-height:1.7}
.login-form{display:flex;flex-direction:column;gap:21px}
.login-field>label{display:block;font-size:var(--rs-font-size-secondary);font-weight:550;margin-bottom:10px}
.login-input{display:flex;align-items:center;height:48px;gap:11px;padding:0 14px;border:1px solid var(--rs-border);border-radius:7px;background:var(--rs-bg-card);transition:border-color .18s,box-shadow .18s}
.login-input:hover{border-color:var(--rs-primary-border)}
.login-input:focus-within{border-color:var(--rs-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--rs-primary) 9%,transparent)}
.login-input>svg{color:var(--rs-text-3);width:17px;height:17px}
.login-input>input{width:100%;min-width:0;height:100%;border:0;outline:0;background:transparent;color:var(--rs-text);font-size:var(--rs-font-size-secondary);padding:0}
.login-input input::placeholder{color:var(--rs-text-3);font-size:var(--rs-font-size-caption)}
.login-input:has(input:disabled){opacity:.65}
.password-toggle{display:grid;place-items:center;flex-shrink:0;background:transparent;border:0;color:var(--rs-text-3);padding:6px;margin-right:-6px;border-radius:4px}
.password-toggle:hover{color:var(--rs-primary);background:var(--rs-bg-soft)}
.password-toggle svg{width:17px;height:17px}
.login-input.has-error{border-color:var(--rs-danger)}
.login-error{color:var(--rs-danger);font-size:var(--rs-font-size-caption);line-height:1.5;margin:7px 0 -3px}
.login-form-error{margin:-6px 0 0;text-align:left}
.login-mode-note{margin:-14px 0 24px;padding:10px 12px;border:1px solid var(--rs-border-soft);border-radius:7px;background:var(--rs-bg-soft);color:var(--rs-text-2);font-size:var(--rs-font-size-caption);line-height:1.7}
.login-mode-note--error{border-color:color-mix(in srgb,var(--rs-danger) 30%,transparent);color:var(--rs-danger)}
.login-unavailable{display:flex;flex-direction:column;gap:14px;padding:18px 0}
.login-unavailable h3{margin:0;font-size:var(--rs-font-size-section-title);color:var(--rs-text)}
.login-unavailable p{margin:0;color:var(--rs-text-2);font-size:var(--rs-font-size-secondary);line-height:1.8}
.login-options{display:flex;align-items:center;justify-content:space-between;margin-top:-3px}
.remember-account{display:flex;align-items:center;gap:7px;color:var(--rs-text-2);font-size:var(--rs-font-size-caption);cursor:pointer}
.remember-account input{width:14px;height:14px;accent-color:var(--rs-primary);margin:0;cursor:pointer}
.login-text-button{border:0;background:transparent;padding:0;color:var(--rs-primary-text);font-size:var(--rs-font-size-caption);line-height:1.6;display:inline-flex;align-items:center;gap:4px}
.login-text-button:hover{color:var(--rs-primary);text-decoration:underline;text-underline-offset:3px}
.login-text-button svg{width:12px;height:12px}
.login-submit{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;height:48px;padding:0 20px;border:1px solid #1677ff;border-radius:7px;background:linear-gradient(100deg,#2585ff,#1670f0);box-shadow:0 4px 10px #1677ff15;color:#fff;font-size:var(--rs-font-size-body);font-weight:550;transition:background .18s,box-shadow .18s}
.login-submit>svg{width:16px;height:16px;margin-left:4px}
.login-submit:hover:not(:disabled){background:linear-gradient(100deg,#4096ff,#2585ff);box-shadow:0 5px 15px #1677ff28}
.login-submit:disabled{opacity:.7;cursor:wait}
.login-demo-note{display:flex;align-items:flex-start;justify-content:center;gap:6px;font-size:10px;line-height:1.7;color:var(--rs-text-3);margin:-8px 0 0}
.login-demo-note svg{width:12px;height:12px;margin-top:2px}
.login-divider{display:flex;align-items:center;gap:16px;color:var(--rs-text-3);font-size:10px;margin:29px 0 20px}
.login-divider::before,.login-divider::after{content:'';height:1px;background:var(--rs-border-soft);flex:1}
.login-demo-button{width:100%;height:44px;display:flex;align-items:center;justify-content:center;gap:9px;border:1px solid var(--rs-border);border-radius:7px;background:var(--rs-bg-card);color:var(--rs-text-2);font-size:var(--rs-font-size-secondary);transition:border-color .18s,background .18s}
.login-demo-button:hover:not(:disabled){border-color:var(--rs-primary-border);background:var(--rs-bg-hover);color:var(--rs-primary)}
.login-demo-button:disabled{opacity:.65;cursor:wait}
.login-demo-button svg{width:16px;height:16px}
.login-demo-button svg:last-child{width:13px;height:13px;margin-left:4px}
.login-support{display:flex;justify-content:center;align-items:center;gap:5px;margin:25px 0 0;font-size:var(--rs-font-size-caption);color:var(--rs-text-3)}
.login-footer{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:12px;color:var(--rs-text-3);font-size:10px;line-height:1.8;padding:12px 0 2px}
.login-footer-dot{opacity:.5}
.login-spinner{width:15px;height:15px;border:2px solid #ffffff55;border-top-color:#fff;border-radius:50%;animation:login-spin .7s linear infinite}
.login-help-content{text-align:center;padding:10px 8px}
.login-help-icon{display:grid;place-items:center;width:48px;height:48px;margin:0 auto;background:var(--rs-bg-selected);color:var(--rs-primary);border-radius:12px}
.login-help-icon svg{width:23px;height:23px}
.login-help-content h3{color:var(--rs-text);font-size:var(--rs-font-size-section-title);margin:18px 0 10px}
.login-help-content>p{font-size:var(--rs-font-size-secondary);color:var(--rs-text-2);line-height:1.9;margin:0}
.login-help-demo{display:flex;align-items:flex-start;gap:8px;padding:12px;border-radius:7px;background:var(--rs-bg-soft);text-align:left;margin-top:22px;color:var(--rs-text-2)}
.login-help-demo>svg{width:15px;height:15px;color:var(--rs-primary);margin-top:3px}
.login-help-demo p{margin:0;font-size:var(--rs-font-size-caption);line-height:1.8}
@keyframes login-spin{to{transform:rotate(360deg)}}
@media(min-width:1600px){.login-story{padding:40px 52px}.login-story-content{max-width:580px}.login-story h1{font-size:52px}.story-description{font-size:var(--rs-font-size-body);margin-bottom:42px}.knowledge-illustration{margin-left:0}.login-form-area{max-width:400px}.login-form-area h2{font-size:30px}}
@media(max-width:1190px){.login-story{padding:28px;min-height:790px}.login-story h1{font-size:40px}.story-eyebrow{font-size:9px;letter-spacing:1.4px}.knowledge-illustration{zoom:.82;margin-left:-12px}.story-footer{gap:12px;font-size:9px}.story-footer svg{width:12px;height:12px}.story-footer>span{gap:5px}.login-main{padding-inline:28px}.login-form-area h2{font-size:25px}}
@media(max-width:900px){.login-page{grid-template-columns:minmax(0,.9fr) minmax(0,1fr);padding:12px}.login-story{padding:24px;min-height:780px}.login-story h1{font-size:34px}.story-description{font-size:12px}.knowledge-illustration{zoom:.65;margin-left:-14px;margin-top:20px}.story-footer{gap:10px;flex-wrap:wrap}.story-footer>i{display:none}.story-footer>span:last-child{display:none}.login-main{padding-inline:24px}.login-form-area h2{font-size:23px}}
@media(min-width:901px) and (max-height:880px){.login-story{min-height:calc(100svh - 32px);padding-block:26px}.login-story-content{margin-block:24px 16px}.story-eyebrow{margin-bottom:16px}.login-story h1{font-size:38px}.story-description{margin:14px 0 22px}.knowledge-illustration{zoom:.78}.login-form-area{padding-block:24px}.login-welcome-mark{width:45px;height:48px;margin-bottom:18px}.login-overline{margin-bottom:9px}.login-subtitle{margin-bottom:27px}.login-form{gap:18px}.login-divider{margin-top:24px}.login-support{margin-top:20px}}
@media(max-width:700px){.login-page{display:block;padding:0}.login-story{display:none}.login-main{min-height:100svh;padding:24px}.login-topbar{gap:12px}.login-mobile-brand{display:flex;align-items:center;gap:8px;margin-right:auto;color:var(--rs-text)}.login-mobile-brand>.brand-mark{width:30px;height:30px}.login-mobile-brand b{font-size:17px;font-weight:750;letter-spacing:-.4px}.login-language{font-size:11px;gap:5px}.login-language svg{width:13px;height:13px}.login-theme{width:26px}.login-form-area{max-width:380px;padding:56px 0 36px}.login-form-area h2{font-size:27px}.login-welcome-mark{margin-bottom:23px}.login-footer{padding-top:24px}.login-help-dialog{max-width:calc(100vw - 32px)}}
@media(max-width:370px){.login-main{padding:20px}.login-topbar{gap:8px}.login-language{font-size:10px}.login-mobile-brand b{font-size:15px}.login-form-area h2{font-size:24px}.login-demo-note{font-size:9px}}
@media(prefers-reduced-motion:reduce){.login-spinner{animation:none}.login-submit,.login-input,.login-demo-button{transition:none}}
/* 工程适配：App.vue 的 .saas 是 height:100%;overflow:hidden，
   矮视口/小屏下登录页会高于视口，底部按钮会被裁掉。页面根自带 height:100%，
   这里只开内部滚动，不改变原有视觉/布局声明。 */
.login-page{overflow-y:auto}
/* 工程适配：lib.css 的全局 h1..h6 颜色（#13161A）会压过 body 继承色，
   这里用 --rs-text 修正登录标题。
   另：旧主题有 `html.dark a { color: accent }`，品牌链接要保持在
   深色下仍是 --rs-text，否则整块品牌字会变蓝。 */
.login-page .login-story h1,.login-page .login-form-area h2{color:var(--rs-text)}
html.dark .login-page .login-brand,html.dark .login-page .login-mobile-brand{color:var(--rs-text)}
</style>
