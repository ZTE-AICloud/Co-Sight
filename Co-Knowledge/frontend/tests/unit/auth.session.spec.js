// @vitest-environment jsdom
import { vi } from 'vitest'

const { warningSpy } = vi.hoisted(() => ({ warningSpy: vi.fn() }))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    warning: warningSpy,
    info: vi.fn(),
    error: vi.fn(),
    closeAll: vi.fn()
  }
}))

vi.mock('@/app/i18n/i18n.js', () => ({
  $t: key => key,
  isGlobalZh: true,
  locale: 'zh'
}))

vi.mock('@/features/auth/api', () => ({
  fetchAuthStatus: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  fetchMe: vi.fn(),
  changePassword: vi.fn()
}))

import { flush, createTestRouter } from './helpers/mount'
import {
  authState,
  ensureStatus,
  handleUnauthorized,
  initSession,
  isAuthEnabled,
  isAuthenticated,
  resetSessionState,
  signIn,
  signOut
} from '@/features/auth/session'
import { fetchAuthStatus, login, logout } from '@/features/auth/api'
import appState from '@/app/state'

const Blank = { name: 'BlankView', render: () => null }
const ROUTES = [
  { path: '/', name: 'root', component: Blank },
  { path: '/knowledge', name: 'knowledge', component: Blank },
  { path: '/login', name: 'login', component: Blank }
]

function status (overrides = {}) {
  return {
    mode: 'local',
    initialized: true,
    authenticated: false,
    user: null,
    ...overrides
  }
}

beforeEach(() => {
  resetSessionState()
  fetchAuthStatus.mockReset()
  login.mockReset()
  logout.mockReset()
  warningSpy.mockClear()
})

describe('ensureStatus', () => {
  it('缓存状态：第二次不再请求', async () => {
    fetchAuthStatus.mockResolvedValue(status({ mode: 'none' }))

    await ensureStatus()
    await ensureStatus()

    expect(fetchAuthStatus).toHaveBeenCalledTimes(1)
    expect(authState.mode).toBe('none')
    expect(isAuthEnabled.value).toBe(false)
  })

  it('force=true 时重新请求', async () => {
    fetchAuthStatus.mockResolvedValue(status())

    await ensureStatus()
    await ensureStatus({ force: true })

    expect(fetchAuthStatus).toHaveBeenCalledTimes(2)
  })

  it('local 模式下保存用户并同步 appState', async () => {
    fetchAuthStatus.mockResolvedValue(status({
      authenticated: true,
      user: {
        username: 'alice', displayName: 'Alice', email: 'a@x.com',
        role: 'user', mustChangePassword: false
      }
    }))

    await ensureStatus()

    expect(isAuthEnabled.value).toBe(true)
    expect(isAuthenticated.value).toBe(true)
    expect(authState.user.username).toBe('alice')
    expect(appState.user.userName).toBe('alice')
    expect(appState.user.personName).toBe('Alice')
    expect(appState.user.authValue).toBe('')
  })

  it('未知 mode 视为错误（不静默关闭鉴权）', async () => {
    fetchAuthStatus.mockResolvedValue({ mode: 'something-else' })

    await expect(ensureStatus()).rejects.toThrow('invalid auth mode')
    expect(authState.statusLoaded).toBe(false)
  })

  it('失败后不缓存，下一次会重试', async () => {
    fetchAuthStatus.mockRejectedValueOnce(new Error('offline'))
    fetchAuthStatus.mockResolvedValueOnce(status({ mode: 'none' }))

    await expect(ensureStatus()).rejects.toThrow('offline')
    await ensureStatus()

    expect(fetchAuthStatus).toHaveBeenCalledTimes(2)
    expect(authState.mode).toBe('none')
  })
})

describe('signIn / signOut', () => {
  it('signIn 写入用户并同步 appState', async () => {
    login.mockResolvedValue({
      user: {
        username: 'alice', displayName: 'Alice', email: '',
        role: 'user', mustChangePassword: false
      }
    })

    const user = await signIn('alice', 'secret123')

    expect(login).toHaveBeenCalledWith('alice', 'secret123')
    expect(user.username).toBe('alice')
    expect(authState.mode).toBe('local')
    expect(appState.user.userName).toBe('alice')
  })

  it('signOut 即使接口失败也清空本地状态', async () => {
    authState.user = { username: 'alice', displayName: 'Alice' }
    logout.mockRejectedValue(new Error('network'))

    await signOut()

    expect(authState.user).toBeNull()
    expect(appState.user.userName).toBe('')
  })
})

describe('handleUnauthorized', () => {
  it('跳转登录页并带回跳地址，只提示一次', async () => {
    const router = await createTestRouter({ routes: ROUTES, initialRoute: '/knowledge' })
    initSession(router)
    authState.user = { username: 'alice', displayName: 'Alice' }

    handleUnauthorized()
    handleUnauthorized()
    await flush()

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/knowledge')
    expect(authState.user).toBeNull()
    expect(warningSpy).toHaveBeenCalledTimes(1)
  })

  it('已经在登录页时只清状态，不重复跳转', async () => {
    const router = await createTestRouter({ routes: ROUTES, initialRoute: '/login' })
    initSession(router)
    authState.user = { username: 'alice', displayName: 'Alice' }

    handleUnauthorized()
    await flush()

    expect(router.currentRoute.value.name).toBe('login')
    expect(warningSpy).not.toHaveBeenCalled()
  })
})
