// @vitest-environment jsdom
// 目录删除弹窗：一层弹窗内三选一（一并删除 / 仅删除目录 / 中止），且删除动作需要
// 4 位确认码。回归背景：不能退化成「通用删除确认 → 第二个文档处理选择」；
// 单层弹窗也不能漏确认码。
import { mountWithPlugins, expectNoI18nMisses, findByText } from './helpers/mount'

import DeleteFolderDialog from '@/features/knowledge-base/components/DeleteFolderDialog.vue'
import i18n from '@/app/i18n/i18n.js'

// 组件脚本里的 `$t` 来自全局 i18n 实例（模板中同名绑定会遮蔽插件注入的实例），
// jsdom 的 navigator.language 是 en-US；这里显式钉成中文再断言中文文案。
let originalLocale
beforeEach(() => {
  originalLocale = i18n.global.locale.value
  i18n.global.locale.value = 'zh'
})
afterEach(() => {
  i18n.global.locale.value = originalLocale
})

// StudioDialog 里包着 el-dialog（teleport + append-to-body），jsdom 下直接渲染
// 拿不到 actions 插槽；用一个只保留两个插槽的壳替换，断言的是本组件的分支与事件。
const StudioDialogStub = {
  name: 'StudioDialog',
  props: ['modelValue', 'title', 'subtitle', 'icon', 'hint', 'width', 'dialogClass', 'busy'],
  emits: ['update:modelValue', 'opened'],
  template: '<section><h2>{{ title }}</h2><p>{{ subtitle }}</p><slot/><slot name="actions"/></section>'
}

async function mountDialog (props = {}) {
  return mountWithPlugins(DeleteFolderDialog, {
    props: { modelValue: true, folderName: 'Docs', documentCount: 3, ...props },
    global: { stubs: { StudioDialog: StudioDialogStub } }
  })
}

/** 读弹窗里的 4 位确认码并输入，走真实的 DeleteVerification 逻辑。 */
async function verify (wrapper) {
  const challenge = wrapper.find('.delete-confirm-challenge code').text()
  await wrapper.find('.delete-confirm-code-row input').setValue(challenge)
  await wrapper.flush()
}

describe('DeleteFolderDialog', () => {
  it('目录有文档时一层弹窗给出三个显式动作，删除动作默认禁用', async () => {
    // Arrange / Act
    const wrapper = await mountDialog({ documentCount: 3 })

    // Assert：文案与三个按钮都在同一层
    expect(wrapper.text()).toContain('3 篇文档')
    expect(wrapper.text()).toContain('请选择处理方式')
    expect(wrapper.text()).toContain('请选择如何处理目录中的文档')
    const buttons = wrapper.findAll('button').filter(button => button.text())
    expect(buttons.map(button => button.text())).toEqual(['取消', '仅删除目录', '一并删除'])
    expect(buttons[0].attributes('disabled')).toBeUndefined()
    expect(buttons[1].attributes('disabled')).toBeDefined()
    expect(buttons[2].attributes('disabled')).toBeDefined()
    expectNoI18nMisses(wrapper)
  })

  it('输入正确确认码后「一并删除 / 仅删除目录」才可点，并发出对应事件', async () => {
    // Arrange
    const wrapper = await mountDialog({ documentCount: 2 })

    // Act
    await verify(wrapper)
    await findByText(wrapper, '一并删除', 'button').trigger('click')
    await findByText(wrapper, '仅删除目录', 'button').trigger('click')

    // Assert
    expect(wrapper.emitted('delete-with-docs')).toHaveLength(1)
    expect(wrapper.emitted('delete-only')).toHaveLength(1)
  })

  it('确认码不匹配时删除按钮保持禁用', async () => {
    // Arrange
    const wrapper = await mountDialog({ documentCount: 2 })
    const challenge = wrapper.find('.delete-confirm-challenge code').text()
    const wrong = challenge === '1000' ? '1001' : '1000'

    // Act
    await wrapper.find('.delete-confirm-code-row input').setValue(wrong)
    await wrapper.flush()

    // Assert
    expect(findByText(wrapper, '一并删除', 'button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('验证码不匹配')
  })

  it('点「取消」只关闭弹窗，无需确认码，也不发删除动作', async () => {
    // Arrange
    const wrapper = await mountDialog({ documentCount: 2 })

    // Act
    await findByText(wrapper, '取消', 'button').trigger('click')

    // Assert
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(wrapper.emitted('delete-only')).toBeUndefined()
    expect(wrapper.emitted('delete-with-docs')).toBeUndefined()
  })

  it('空目录只给「中止 / 仅删除目录」两个动作，删除同样需要确认码', async () => {
    // Arrange / Act
    const wrapper = await mountDialog({ documentCount: 0 })

    // Assert
    expect(wrapper.text()).toContain('没有文档')
    expect(wrapper.text()).toContain('删除后不可恢复，请确认')
    const buttons = wrapper.findAll('button').filter(button => button.text())
    expect(buttons.map(button => button.text())).toEqual(['取消', '仅删除目录'])
    expect(buttons[1].attributes('disabled')).toBeDefined()
    await verify(wrapper)
    expect(findByText(wrapper, '仅删除目录', 'button').attributes('disabled')).toBeUndefined()
    expectNoI18nMisses(wrapper)
  })

  it('请求在飞时（busy）三个动作都禁用，避免重复提交', async () => {
    // Arrange / Act
    const wrapper = await mountDialog({ documentCount: 2, busy: true })

    // Assert
    for (const button of wrapper.findAll('button').filter(button => button.text())) {
      expect(button.attributes('disabled')).toBeDefined()
    }
  })
})
