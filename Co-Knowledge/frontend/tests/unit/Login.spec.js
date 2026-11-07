// @vitest-environment jsdom
// 登录页（真实账号体系）：结构、空值校验、记住账号、
// 成功/失败/限流/未初始化、none 模式演示入口、gateway 提示、redirect 回跳。
import { h } from 'vue'
import { vi } from 'vitest'

const { successSpy } = vi.hoisted(() => ({ successSpy: vi.fn() }))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: successSpy,
    warning: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
    closeAll: vi.fn()
  }
}))

// 脚本侧文案只用于断言键（模板侧走 mount helper 的真词条）。
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

import { expectNoI18nMisses, flush, mountWithPlugins, textOf } from './helpers/mount'
import Login from '@/pages/login/LoginPage.vue'
import { applyTheme } from '@/shared/lib/theme'
import { fetchAuthStatus, login } from '@/features/auth/api'
import { resetSessionState } from '@/features/auth/session'

const REMEMBER_KEY = 'rag-studio-remembered-account'
const LANGUAGE_KEY = 'language-option'

// 语言切换的选项在 el-popover 的默认插槽里。测试脚手架没有注册 popper，
// 用一个透明占位件同时渲染 #reference 与默认插槽（与 LeftNav.spec 同法）。
const POPOVER_STUB = {
  name: 'ElPopover',
  props: ['visible', 'placement', 'trigger', 'width', 'offset', 'popperClass'],
  emits: ['update:visible'],
  setup (_props, { slots }) {
    return () => h('div', [slots.reference?.(), slots.default?.()])
  }
}

const Blank = { name: 'BlankView', render: () => null }
const ROUTES = [
  { path: '/login', name: 'login', component: Blank },
  { path: '/knowledge', name: 'knowledge', component: Blank },
  { path: '/chat', name: 'chat', component: Blank },
  { path: '/change-password', name: 'changePassword', component: Blank }
]

let wrapper = null

async function mountLogin (route = '/login', options = {}) {
  const { global: globalOptions = {}, ...rest } = options
  wrapper = await mountWithPlugins(Login, {
    route,
    routes: ROUTES,
    attachTo: document.body,
    ...rest,
    global: {
      ...globalOptions,
      components: { ElPopover: POPOVER_STUB, ...(globalOptions.components || {}) }
    }
  })
  await flush()
  return wrapper
}

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
  localStorage.clear()
  successSpy.mockClear()
  resetSessionState()
  fetchAuthStatus.mockReset()
  login.mockReset()
  fetchAuthStatus.mockResolvedValue(status())
  applyTheme('light')
})

afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
  document.body.innerHTML = ''
  applyTheme('light')
})

describe('Login 页面结构', () => {
  it('local 模式渲染真实表单，不显示演示入口', async () => {
    const page = await mountLogin()

    expect(page.classes()).toEqual(expect.arrayContaining(['login-page']))
    expect(page.find('.login-story').exists()).toBe(true)
    expect(page.find('#login-title').text()).toBe('欢迎回到 Knowledge Studio')
    expect(page.find('form.login-form').exists()).toBe(true)
    expect(page.find('.login-submit').text()).toContain('登录工作台')
    expect(page.find('.login-demo-note').exists()).toBe(false)
    expect(page.find('.login-demo-button').exists()).toBe(false)
    expect(page.find('#login-account').attributes('disabled')).toBeUndefined()
  })

  it('主题按钮跟随 useTheme 切换 html.dark', async () => {
    const page = await mountLogin()
    const button = page.find('.login-theme')

    expect(document.documentElement.classList.contains('dark')).toBe(false)
    await button.trigger('click')

    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('ragstudio-theme')).toBe('dark')
  })
})

describe('Login 表单校验与登录', () => {
  it('空账号与空密码：显示错误且不发请求、不跳转', async () => {
    const page = await mountLogin()

    await page.find('form.login-form').trigger('submit')
    await flush()

    expect(page.find('#login-account-error').text())
      .toBe('modules.auth.login.accountPlaceholder')
    expect(page.find('#login-password-error').text())
      .toBe('modules.auth.login.passwordPlaceholder')
    expect(login).not.toHaveBeenCalled()
    expect(page.router.currentRoute.value.name).toBe('login')
  })

  it('重新输入账号后只清掉账号错误', async () => {
    const page = await mountLogin()
    await page.find('form.login-form').trigger('submit')
    await flush()

    await page.find('#login-account').setValue('alice')

    expect(page.find('#login-account-error').exists()).toBe(false)
    expect(page.find('#login-password-error').exists()).toBe(true)
  })

  it('登录成功：写入记住账号、提示并跳转 /knowledge', async () => {
    login.mockResolvedValue({
      user: { username: 'alice', displayName: 'Alice', mustChangePassword: false }
    })
    const page = await mountLogin()
    await page.find('#login-account').setValue(' alice ')
    await page.find('#login-password').setValue('secret123')
    await page.find('.remember-account input').setValue(true)

    await page.find('form.login-form').trigger('submit')
    await flush()

    expect(login).toHaveBeenCalledWith('alice', 'secret123')
    expect(localStorage.getItem(REMEMBER_KEY)).toBe('alice')
    expect(Object.keys(localStorage)).not.toContain('password')
    expect(page.router.currentRoute.value.name).toBe('knowledge')
    expect(successSpy).toHaveBeenCalled()
  })

  it('登录成功但要求改密：跳到 /change-password', async () => {
    login.mockResolvedValue({
      user: { username: 'admin', displayName: 'Admin', mustChangePassword: true }
    })
    const page = await mountLogin()

    await page.find('#login-account').setValue('admin')
    await page.find('#login-password').setValue('initial-password')
    await page.find('form.login-form').trigger('submit')
    await flush()

    expect(page.router.currentRoute.value.name).toBe('changePassword')
  })

  it('带 redirect 登录：回到原地址', async () => {
    login.mockResolvedValue({
      user: { username: 'alice', displayName: 'Alice', mustChangePassword: false }
    })
    const page = await mountLogin('/login?redirect=%2Fchat')

    await page.find('#login-account').setValue('alice')
    await page.find('#login-password').setValue('secret123')
    await page.find('form.login-form').trigger('submit')
    await flush()

    expect(page.router.currentRoute.value.name).toBe('chat')
  })

  it('账号或密码错误：密码框下方内联错误，不跳转', async () => {
    login.mockRejectedValue({
      code: 'invalid_credentials',
      detail: '账号或密码不正确'
    })
    const page = await mountLogin()

    await page.find('#login-account').setValue('alice')
    await page.find('#login-password').setValue('wrong')
    await page.find('form.login-form').trigger('submit')
    await flush()

    expect(page.find('#login-password-error').text()).toBe('账号或密码不正确')
    expect(page.find('.login-form-error').exists()).toBe(false)
    expect(page.router.currentRoute.value.name).toBe('login')
  })

  it('限流错误显示在表单级，而不是密码框', async () => {
    login.mockRejectedValue({
      code: 'login_rate_limited',
      detail: '尝试次数过多，请稍后再试'
    })
    const page = await mountLogin()

    await page.find('#login-account').setValue('alice')
    await page.find('#login-password').setValue('secret123')
    await page.find('form.login-form').trigger('submit')
    await flush()

    expect(page.find('.login-form-error').text()).toBe('尝试次数过多，请稍后再试')
    expect(page.find('#login-password-error').exists()).toBe(false)
  })

  it('有历史账号时回填并勾选「记住账号」', async () => {
    localStorage.setItem(REMEMBER_KEY, 'saved-user')

    const page = await mountLogin()

    expect(page.find('#login-account').element.value).toBe('saved-user')
    expect(page.find('.remember-account input').element.checked).toBe(true)
  })

  it('不勾选「记住账号」时清掉历史账号', async () => {
    localStorage.setItem(REMEMBER_KEY, 'saved-user')
    login.mockResolvedValue({
      user: { username: 'alice', displayName: 'Alice', mustChangePassword: false }
    })
    const page = await mountLogin()
    await page.find('#login-account').setValue('alice')
    await page.find('#login-password').setValue('secret123')
    await page.find('.remember-account input').setValue(false)

    await page.find('form.login-form').trigger('submit')
    await flush()

    expect(localStorage.getItem(REMEMBER_KEY)).toBeNull()
  })
})

describe('Login 非 local 模式', () => {
  it('none 模式：表单禁用、显示演示入口，点击直接进工作台', async () => {
    fetchAuthStatus.mockResolvedValue(status({ mode: 'none' }))
    const page = await mountLogin()

    expect(page.find('#login-account').attributes('disabled')).toBeDefined()
    expect(page.find('.login-mode-note').text()).toContain('未启用登录')
    await page.find('.login-demo-button').trigger('click')
    await flush()

    expect(page.router.currentRoute.value.name).toBe('knowledge')
    expect(login).not.toHaveBeenCalled()
  })

  it('gateway 模式：显示网关提示，不显示演示入口', async () => {
    fetchAuthStatus.mockResolvedValue(status({ mode: 'gateway' }))
    const page = await mountLogin()

    expect(page.find('#login-account').attributes('disabled')).toBeDefined()
    expect(page.find('.login-mode-note').text()).toContain('统一认证网关')
    expect(page.find('.login-demo-button').exists()).toBe(false)
  })

  it('状态接口失败：显示不可用与重试；重试成功后恢复表单', async () => {
    fetchAuthStatus.mockRejectedValueOnce(new Error('offline'))
    const page = await mountLogin()

    expect(page.find('.login-unavailable').exists()).toBe(true)
    expect(textOf(page.find('.login-unavailable'))).toContain('认证服务不可用')

    fetchAuthStatus.mockResolvedValue(status())
    await page.find('.login-unavailable .login-demo-button').trigger('click')
    await flush()

    expect(page.find('.login-unavailable').exists()).toBe(false)
    expect(page.find('form.login-form').exists()).toBe(true)
  })
})

// 登录页的语言切换：顶栏不能只有一个静态的「简体中文」标签，
// 页面文案也不能写死在模板里 —— 否则切到英文后登录页仍是中文。
// 这里钉两件事：切语言会写存储并整页重载；英文环境下页面文案真的都是英文。
describe('Login 语言切换', () => {
  /** jsdom 没实现 location.reload；换成可写副本后才能断言「确实要求了整页重载」。 */
  async function withStubbedLocation (fn) {
    const original = window.location
    const reload = vi.fn()
    delete window.location
    window.location = { ...original, reload }
    try {
      await fn(reload)
    } finally {
      delete window.location
      window.location = original
    }
  }

  it('中文环境：顶栏显示当前语言，两个语言选项可选', async () => {
    localStorage.setItem(LANGUAGE_KEY, JSON.stringify('zh-CN'))

    const page = await mountLogin()

    expect(page.find('.login-language').text()).toContain('简体中文')
    const options = page.findAll('.login-language-option')
    expect(options.map(node => textOf(node))).toEqual(['简体中文', 'English'])
    expect(options[0].classes()).toContain('is-current')
    expect(options[1].classes()).not.toContain('is-current')
    expectNoI18nMisses(page)
  })

  it('点击 English：按 JSON 编码写入 localStorage，并整页重载', async () => {
    localStorage.setItem(LANGUAGE_KEY, JSON.stringify('zh-CN'))
    const page = await mountLogin()

    await withStubbedLocation(async reload => {
      await page.findAll('.login-language-option')[1].trigger('click')
      await flush()

      expect(localStorage.getItem(LANGUAGE_KEY)).toBe('"en-US"')
      expect(reload).toHaveBeenCalledTimes(1)
    })
  })

  it('点击当前语言：不写存储、不重载', async () => {
    localStorage.setItem(LANGUAGE_KEY, JSON.stringify('zh-CN'))
    const page = await mountLogin()

    await withStubbedLocation(async reload => {
      await page.findAll('.login-language-option')[0].trigger('click')
      await flush()

      expect(localStorage.getItem(LANGUAGE_KEY)).toBe('"zh-CN"')
      expect(reload).not.toHaveBeenCalled()
    })
  })

  it('英文环境：品牌故事、欢迎语与页脚全部渲染英文，不回落中文', async () => {
    localStorage.setItem(LANGUAGE_KEY, JSON.stringify('en-US'))

    const page = await mountLogin('/login', { locale: 'en' })

    expect(page.find('#login-title').text()).toBe('Welcome back to Knowledge Studio')
    expect(page.find('.story-description').text()).toContain('Turn scattered documents')
    expect(page.find('.story-footer').text()).toContain('Trustworthy AI Q&A')
    expect(page.find('.login-footer').text()).toContain('Knowledge as productivity')
    expect(page.find('#login-account').attributes('placeholder')).toBe('Enter your email or username')
    expectNoI18nMisses(page)

    // 回归护栏：模板里再塞中文硬编码时，英文界面会混入汉字。
    // 语言选项里的「简体中文」是另一种语言的自我称谓，不在检查范围内。
    const visibleCopy = textOf(page.find('.login-story')) +
      textOf(page.find('.login-form-area')) +
      textOf(page.find('.login-footer'))
    expect(visibleCopy).not.toMatch(/[\u4E00-\u9FFF]/)
  })
})
