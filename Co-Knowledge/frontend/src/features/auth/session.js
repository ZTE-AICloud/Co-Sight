/**
 * 登录会话的**前端唯一状态源**。
 *
 * - 模式来自后端 ``GET /auth/status``（同一份 web 构建支持 none/local/gateway）；
 * - 用户信息是 reactive 的，页面/左栏直接读这里；``appState`` 只做旧消费方同步
 *   （``X-Emp-No``、默认模板名），**token 永远不进 JS**（HttpOnly Cookie）；
 * - 401 统一由 ``handleUnauthorized`` 处理：清状态、提示一次、跳登录并带回跳地址。
 */
import { computed, reactive } from 'vue'

import appState, { updateAppState } from '@/app/state'
import { $t } from '@/app/i18n/i18n.js'
import message from '@/shared/lib/message'
import { setUnauthorizedHandler } from '@/shared/api/unauthorized'
import {
  changePassword as apiChangePassword,
  fetchAuthStatus,
  login as apiLogin,
  logout as apiLogout
} from '@/features/auth/api'

const KNOWN_MODES = ['none', 'local', 'gateway']

const state = reactive({
  mode: 'unknown',
  initialized: true,
  user: null,
  statusLoaded: false
})

let statusPromise = null
let routerRef = null
let redirecting = false

export const authState = state
export const isAuthEnabled = computed(() => state.mode === 'local')
export const isAuthenticated = computed(() => state.user !== null)
export const currentUser = computed(() => state.user)

function syncAppState (user) {
  const username = user?.username || ''
  const displayName = user?.displayName || ''
  updateAppState({
    user: {
      ...appState.user,
      userName: username,
      personName: displayName,
      displayLongName: displayName,
      email: user?.email || '',
      // 会话 token 只存在于 HttpOnly Cookie；这里保持空值，避免被误用。
      authValue: ''
    }
  })
}

function applyStatus (data) {
  const mode = data?.mode
  if (!KNOWN_MODES.includes(mode)) {
    throw new Error(`invalid auth mode: ${mode}`)
  }
  state.mode = mode
  state.initialized = data?.initialized !== false
  state.user = data?.user || null
  state.statusLoaded = true
  syncAppState(state.user)
  return state
}

/**
 * 读取认证模式（带缓存）。失败**不缓存**：下一次导航/重试会重新请求。
 * 失败时抛错，由守卫 fail-closed 地送到登录页。
 */
export function ensureStatus ({ force = false } = {}) {
  if (!force && state.statusLoaded) {
    return Promise.resolve(state)
  }
  if (!force && statusPromise) {
    return statusPromise
  }
  statusPromise = fetchAuthStatus()
    .then(applyStatus)
    .catch(error => {
      statusPromise = null
      state.statusLoaded = false
      throw error
    })
  return statusPromise
}

export async function signIn (username, password) {
  const data = await apiLogin(username, password)
  state.mode = 'local'
  state.initialized = true
  state.statusLoaded = true
  state.user = data?.user || null
  syncAppState(state.user)
  return state.user
}

export async function signOut () {
  try {
    await apiLogout()
  } catch {
    // 退出接口失败（网络/会话已过期）也必须清本地状态；Cookie 由后端尽力撤销。
  } finally {
    state.user = null
    syncAppState(null)
  }
}

export async function changePassword (currentPassword, newPassword) {
  await apiChangePassword(currentPassword, newPassword)
  if (state.user) {
    state.user = { ...state.user, mustChangePassword: false }
  }
}

export function handleUnauthorized () {
  if (redirecting) {
    return
  }
  state.user = null
  syncAppState(null)

  const route = routerRef?.currentRoute?.value
  if (!routerRef || !route || route.name === 'login') {
    return
  }

  redirecting = true
  message.warning($t('modules.auth.sessionExpired'))
  routerRef
    .replace({ name: 'login', query: { redirect: route.fullPath } })
    .finally(() => {
      // 同一 tick 内的并发 401 只跳一次；下一 tick 恢复。
      setTimeout(() => {
        redirecting = false
      }, 0)
    })
}

/** 启动时调用：注册全局 401 处理器。 */
export function initSession (router) {
  routerRef = router
  setUnauthorizedHandler(handleUnauthorized)
}

/** 测试用：重置模块内状态与处理器。 */
export function resetSessionState () {
  state.mode = 'unknown'
  state.initialized = true
  state.user = null
  state.statusLoaded = false
  statusPromise = null
  routerRef = null
  redirecting = false
  setUnauthorizedHandler(null)
  syncAppState(null)
}
