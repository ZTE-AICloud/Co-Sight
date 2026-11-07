// @vitest-environment jsdom
import { vi } from 'vitest'

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    warning: vi.fn(),
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

import { createTestRouter } from './helpers/mount'
import { installAuthGuard, safeRedirect } from '@/features/auth/guard'
import { resetSessionState } from '@/features/auth/session'
import { fetchAuthStatus } from '@/features/auth/api'

const Blank = { name: 'BlankView', render: () => null }
const ROUTES = [
  { path: '/knowledge', name: 'knowledge', component: Blank },
  { path: '/chat', name: 'chat', component: Blank },
  { path: '/login', name: 'login', component: Blank },
  { path: '/change-password', name: 'changePassword', component: Blank }
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

function user (overrides = {}) {
  return {
    username: 'alice',
    displayName: 'Alice',
    email: '',
    role: 'user',
    mustChangePassword: false,
    ...overrides
  }
}

async function makeRouter (initialRoute = '/login') {
  const router = await createTestRouter({ routes: ROUTES, initialRoute })
  installAuthGuard(router)
  return router
}

beforeEach(() => {
  resetSessionState()
  fetchAuthStatus.mockReset()
  fetchAuthStatus.mockResolvedValue(status())
})

describe('safeRedirect', () => {
  it('只放行站内普通路径', () => {
    expect(safeRedirect('/knowledge')).toBe('/knowledge')
    expect(safeRedirect('/chat?tab=1')).toBe('/chat?tab=1')
  })

  it('拒绝外站、协议相对、登录/改密自环与非字符串', () => {
    for (const value of [
      '//evil.com', 'https://evil.com', '/login', '/login?x=1',
      '/change-password', ['/knowledge'], null, undefined, 42
    ]) {
      expect(safeRedirect(value)).toBeNull()
    }
  })
})

describe('installAuthGuard', () => {
  it('未登录访问业务页 → 登录页并带 redirect', async () => {
    const router = await makeRouter()

    await router.push('/knowledge')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/knowledge')
  })

  it('已登录访问 /login → 回工作台', async () => {
    fetchAuthStatus.mockResolvedValue(status({
      authenticated: true, user: user()
    }))
    // 初始导航发生在安装守卫之前（停在 /knowledge）；再 push /login 才会触发守卫。
    const router = await makeRouter('/knowledge')

    await router.push('/login')

    expect(router.currentRoute.value.name).toBe('knowledge')
  })

  it('已登录且带合法 redirect → 回原地址', async () => {
    fetchAuthStatus.mockResolvedValue(status({
      authenticated: true, user: user()
    }))
    const router = await makeRouter()

    await router.push('/login?redirect=%2Fchat')

    expect(router.currentRoute.value.name).toBe('chat')
  })

  it('已登录但 redirect 是外站 → 忽略并回工作台', async () => {
    fetchAuthStatus.mockResolvedValue(status({
      authenticated: true, user: user()
    }))
    const router = await makeRouter()

    await router.push('/login?redirect=%2F%2Fevil.com')

    expect(router.currentRoute.value.name).toBe('knowledge')
  })

  it('must_change_password → 强制改密页并带 redirect', async () => {
    fetchAuthStatus.mockResolvedValue(status({
      authenticated: true, user: user({ mustChangePassword: true })
    }))
    const router = await makeRouter()

    await router.push('/knowledge')

    expect(router.currentRoute.value.name).toBe('changePassword')
    expect(router.currentRoute.value.query.redirect).toBe('/knowledge')
  })

  it('未登录访问改密页 → 先登录', async () => {
    const router = await makeRouter()

    await router.push('/change-password')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/change-password')
  })

  it('mode=none 完全放行', async () => {
    fetchAuthStatus.mockResolvedValue(status({ mode: 'none' }))
    const router = await makeRouter()

    await router.push('/knowledge')

    expect(router.currentRoute.value.name).toBe('knowledge')
  })

  it('mode=gateway 完全放行（由网关负责）', async () => {
    fetchAuthStatus.mockResolvedValue(status({ mode: 'gateway' }))
    const router = await makeRouter()

    await router.push('/knowledge')

    expect(router.currentRoute.value.name).toBe('knowledge')
  })

  it('认证状态接口失败 → fail-closed 到登录页并标记 unavailable', async () => {
    fetchAuthStatus.mockRejectedValue(new Error('offline'))
    const router = await makeRouter()

    await router.push('/knowledge')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/knowledge')
    expect(router.currentRoute.value.query.unavailable).toBe('1')
  })
})
