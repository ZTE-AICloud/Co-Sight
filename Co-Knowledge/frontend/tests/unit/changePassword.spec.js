// @vitest-environment jsdom
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
import ChangePasswordForm from '@/features/auth/components/ChangePasswordForm.vue'
import { changePassword } from '@/features/auth/api'
import { resetSessionState } from '@/features/auth/session'

let wrapper = null

async function mountForm () {
  wrapper = await mountWithPlugins(ChangePasswordForm, { router: null })
  return wrapper
}

beforeEach(() => {
  resetSessionState()
  changePassword.mockReset()
  successSpy.mockClear()
})

afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
  document.body.innerHTML = ''
})

describe('ChangePasswordForm', () => {
  it('空值提交：三项都报错且不发请求', async () => {
    const form = await mountForm()

    await form.find('form.cp-form').trigger('submit')
    await flush()

    expect(form.find('#cp-current-error').text())
      .toBe('modules.auth.changePassword.currentPlaceholder')
    expect(form.find('#cp-new-error').text())
      .toBe('modules.auth.changePassword.nextPlaceholder')
    expect(form.find('#cp-confirm-error').text())
      .toBe('modules.auth.changePassword.confirmPlaceholder')
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('两次新密码不一致', async () => {
    const form = await mountForm()
    await form.find('#cp-current').setValue('old-password')
    await form.find('#cp-new').setValue('new-password-123')
    await form.find('#cp-confirm').setValue('different-password')

    await form.find('form.cp-form').trigger('submit')
    await flush()

    expect(form.find('#cp-confirm-error').text())
      .toBe('modules.auth.changePassword.mismatch')
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('新密码过短', async () => {
    const form = await mountForm()
    await form.find('#cp-current').setValue('old-password')
    await form.find('#cp-new').setValue('short')
    await form.find('#cp-confirm').setValue('short')

    await form.find('form.cp-form').trigger('submit')
    await flush()

    expect(form.find('#cp-new-error').text())
      .toBe('modules.auth.changePassword.policy')
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('当前密码错误：错误落在当前密码框', async () => {
    changePassword.mockRejectedValue({
      code: 'invalid_current_password',
      detail: '当前密码不正确'
    })
    const form = await mountForm()
    await form.find('#cp-current').setValue('wrong-password')
    await form.find('#cp-new').setValue('new-password-123')
    await form.find('#cp-confirm').setValue('new-password-123')

    await form.find('form.cp-form').trigger('submit')
    await flush()

    expect(form.find('#cp-current-error').text()).toBe('当前密码不正确')
    expect(form.find('.cp-form-error').exists()).toBe(false)
  })

  it('成功：调用接口、提示并 emit success', async () => {
    changePassword.mockResolvedValue(null)
    const form = await mountForm()
    await form.find('#cp-current').setValue('old-password')
    await form.find('#cp-new').setValue('new-password-123')
    await form.find('#cp-confirm').setValue('new-password-123')

    await form.find('form.cp-form').trigger('submit')
    await flush()

    expect(changePassword).toHaveBeenCalledWith('old-password', 'new-password-123')
    expect(successSpy).toHaveBeenCalled()
    expect(form.emitted('success')).toHaveLength(1)
  })
})
