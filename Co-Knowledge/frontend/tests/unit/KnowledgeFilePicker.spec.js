// @vitest-environment jsdom
// ↑ 组件测试：断言的是真实 DOM 结构与 change 事件转发。
import { mountWithPlugins } from './helpers/mount'

import KnowledgeFilePicker from '@/features/knowledge-base/components/KnowledgeFilePicker.vue'

// 测的是 `KnowledgeFilePicker.vue` 的「点一下就能选文件」。
//
// 回归背景：隐藏 `<input hidden>` + `<button @click="input.click()">` 会出现
// 「点拖拽区不弹文件选择框」。必须用 label 包住一块**铺满拖拽区**的透明原生
// input，让点击直接命中 input，不依赖模板 ref 与脚本 click()。
// 这层结构一旦被改回 button + script click，下面的用例立刻红。

function fileOf (name, content = 'x') {
  return new File([content], name, { type: 'text/plain' })
}

describe('KnowledgeFilePicker', () => {
  it('拖拽区是 label 包住原生 file input，且 input 没有被隐藏', async () => {
    // Act
    const wrapper = await mountWithPlugins(KnowledgeFilePicker)

    // Assert
    const zone = wrapper.find('.kb-dropzone')
    expect(zone.element.tagName).toBe('LABEL')
    const input = wrapper.find('.kb-dropzone input[type="file"]')
    expect(input.exists()).toBe(true)
    expect(zone.element.contains(input.element)).toBe(true)
    // `hidden` / `display:none` 的 input 在部分浏览器里不弹选择框
    expect(input.attributes('hidden')).toBeUndefined()
    expect(input.attributes('multiple')).toBeDefined()
    expect(input.attributes('accept')).toContain('.pdf')
  })

  it('在原生 input 上选文件后进入待导入列表', async () => {
    // Arrange
    const wrapper = await mountWithPlugins(KnowledgeFilePicker)
    const input = wrapper.find('.kb-upload-input')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [fileOf('a.txt')]
    })

    // Act
    await input.trigger('change')

    // Assert
    expect(wrapper.findAll('.kb-file-list li')).toHaveLength(1)
    expect(wrapper.text()).toContain('a.txt')
  })

  it('拖拽文件到拖拽区同样进入列表', async () => {
    // Arrange
    const wrapper = await mountWithPlugins(KnowledgeFilePicker)

    // Act
    await wrapper.find('.kb-dropzone').trigger('drop', {
      dataTransfer: { files: [fileOf('b.md')] }
    })

    // Assert
    expect(wrapper.findAll('.kb-file-list li')).toHaveLength(1)
    expect(wrapper.text()).toContain('b.md')
  })

  it('不支持的文件格式给出错误提示，不进入列表', async () => {
    // Arrange
    const wrapper = await mountWithPlugins(KnowledgeFilePicker)
    const input = wrapper.find('.kb-upload-input')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [fileOf('virus.exe')]
    })

    // Act
    await input.trigger('change')

    // Assert
    expect(wrapper.findAll('.kb-file-list li')).toHaveLength(0)
    expect(wrapper.find('.kb-upload-errors').exists()).toBe(true)
  })
})
