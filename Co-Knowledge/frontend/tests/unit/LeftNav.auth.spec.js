// @vitest-environment jsdom
// 本地账号登录后，左栏页脚用用户菜单替换登录入口；退出后回登录页。
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

import { flush, mountWithPlugins } from './helpers/mount'
import LeftNav from '@/app/layout/nav/LeftNav.vue'
import { authState, resetSessionState } from '@/features/auth/session'
import { logout } from '@/features/auth/api'

const ElPopoverStub = {
  name: 'ElPopover',
  props: ['visible'],
  emits: ['update:visible'],
  template: '<div class="el-popover-stub"><slot name="reference" />'
    + '<div class="el-popover-body"><slot /></div></div>'
}

async function mountNav () {
  return mountWithPlugins(LeftNav, {
    route: '/chat',
    global: { stubs: { ElPopover: ElPopoverStub } }
  })
}

beforeEach(() => {
  resetSessionState()
  logout.mockReset()
  logout.mockResolvedValue(null)
})

describe('LeftNav user menu', () => {
  it('已登录：显示用户菜单，不再显示登录入口', async () => {
    authState.mode = 'local'
    authState.user = { username: 'alice', displayName: 'Alice' }

    const wrapper = await mountNav()
    await flush()

    expect(wrapper.find('.user-trigger').exists()).toBe(true)
    expect(wrapper.find('.user-avatar').text()).toBe('A')
    expect(wrapper.find('.side-footer a[aria-label="登录入口"]').exists()).toBe(false)
    expect(wrapper.find('.user-panel').text()).toContain('修改密码')
    expect(wrapper.find('.user-panel').text()).toContain('退出登录')
  })

  it('点击退出：调用接口、清状态并回登录页', async () => {
    authState.mode = 'local'
    authState.user = { username: 'alice', displayName: 'Alice' }
    const wrapper = await mountNav()
    await flush()

    await wrapper.find('.user-item--danger').trigger('click')
    await flush()

    expect(logout).toHaveBeenCalledTimes(1)
    expect(authState.user).toBeNull()
    expect(wrapper.router.currentRoute.value.name).toBe('login')
  })

  it('mode=none：保持旧的登录入口', async () => {
    authState.mode = 'none'
    authState.user = null

    const wrapper = await mountNav()
    await flush()

    expect(wrapper.find('.user-trigger').exists()).toBe(false)
    expect(wrapper.find('.side-footer a[aria-label="登录入口"]').exists()).toBe(true)
  })
})
