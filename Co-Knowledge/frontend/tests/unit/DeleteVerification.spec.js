// @vitest-environment jsdom
// 删除确认码：4 位本地码，防误操作（不是安全认证）。
// 全局 DeleteConfirmDialog 与目录删除弹窗共用这一份实现，这里钉住输入/错误/刷新语义。
import { mountWithPlugins } from './helpers/mount'

import DeleteVerification from '@/shared/ui/DeleteVerification.vue'
import i18n from '@/app/i18n/i18n.js'

let originalLocale
beforeEach(() => {
  originalLocale = i18n.global.locale.value
  i18n.global.locale.value = 'zh'
})
afterEach(() => {
  i18n.global.locale.value = originalLocale
})

async function mountVerification () {
  return mountWithPlugins(DeleteVerification)
}

describe('DeleteVerification', () => {
  it('展示 4 位验证码，输入正确后发出 verified=true 并提示通过', async () => {
    // Arrange
    const wrapper = await mountVerification()
    const code = wrapper.find('.delete-confirm-challenge code').text()
    expect(code).toMatch(/^\d{4}$/)

    // Act
    await wrapper.find('.delete-confirm-code-row input').setValue(code)
    await wrapper.flush()

    // Assert
    expect(wrapper.emitted('update:verified').at(-1)).toEqual([true])
    expect(wrapper.text()).toContain('验证通过')
  })

  it('输入错误码时提示不匹配，并发出 verified=false', async () => {
    // Arrange
    const wrapper = await mountVerification()
    const code = wrapper.find('.delete-confirm-challenge code').text()
    const wrong = code === '1000' ? '1001' : '1000'

    // Act
    await wrapper.find('.delete-confirm-code-row input').setValue(wrong)
    await wrapper.flush()

    // Assert
    expect(wrapper.emitted('update:verified').at(-1)).toEqual([false])
    expect(wrapper.text()).toContain('验证码不匹配')
  })

  it('刷新按钮清空输入并换一个新码', async () => {
    // Arrange
    const wrapper = await mountVerification()
    const before = wrapper.find('.delete-confirm-challenge code').text()
    await wrapper.find('.delete-confirm-code-row input').setValue(before)

    // Act
    await wrapper.find('.delete-confirm-challenge button').trigger('click')
    await wrapper.flush()

    // Assert
    const after = wrapper.find('.delete-confirm-challenge code').text()
    expect(after).not.toBe(before)
    expect(wrapper.find('.delete-confirm-code-row input').element.value).toBe('')
    expect(wrapper.emitted('update:verified').at(-1)).toEqual([false])
  })
})
