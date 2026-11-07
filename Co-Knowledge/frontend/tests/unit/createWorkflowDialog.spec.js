// @vitest-environment jsdom
// 「新建知识检索」弹窗的知识来源类型回归守卫（0.1.10）：
//   - 来源类型提到第一层：文档知识库 / 图谱知识库（数据库能力未接入，暂不展示）；
//   - 模板跟着类型匹配：文档 3 种，图谱只有「图谱检索」；
//   - 来源下拉只列出当前类型可用的库；切换类型会清空已选并提示。
// 组件用 `@/app/i18n/i18n.js` 的 `$t`（导入期读 localStorage），
// 所以在 import 之前把语言钉成中文，否则断言会拿到 jsdom 的 en-US。
vi.hoisted(() => {
  window.localStorage.setItem('language-option', JSON.stringify('zh-CN'))
})

import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { flush, expectNoI18nMisses, mountWithPlugins } from './helpers/mount'
import CreateWorkflowDialog from '@/features/workflow/components/CreateWorkflowDialog.vue'
import zhStudioDialogs from '@/app/i18n/zh/studioDialogs'

const GLOBAL = {
  components: { ElForm, ElFormItem }
}

const messages = zhStudioDialogs.createWorkflow

const KB_OPTIONS = [
  { id: 'doc-1', name: '产品手册库', statusLabel: '未发布', isGraph: false, isStruct: false },
  { id: 'graph-1', name: '测试2', statusLabel: '未发布', isGraph: true, isStruct: false },
  { id: 'struct-1', name: '结构化库', statusLabel: '未发布', isGraph: false, isStruct: true }
]

async function mountDialog (props = {}) {
  const wrapper = await mountWithPlugins(CreateWorkflowDialog, {
    route: '/flow',
    props: { modelValue: false, ...props },
    global: GLOBAL
  })
  await wrapper.setProps({ modelValue: true })
  await flush()
  return wrapper
}

function groupByLabel (wrapper, label) {
  return wrapper.find(`[role="radiogroup"][aria-label="${label}"]`)
}

function radiosOf (wrapper, label) {
  return groupByLabel(wrapper, label).findAll('[role="radio"]')
}

describe('CreateWorkflowDialog：知识来源类型', () => {
  it('第一层是来源类型：文档知识库与图谱知识库，数据库能力未接入不展示', async () => {
    // Arrange + Act
    const wrapper = await mountDialog({ knowledgeOptions: KB_OPTIONS })
    const choices = radiosOf(wrapper, messages.sourceTypeLabel)

    // Assert
    expect(choices).toHaveLength(2)
    expect(choices[0].text()).toContain(messages.typeKnowledge)
    expect(choices[1].text()).toContain(messages.typeGraph)
    expect(groupByLabel(wrapper, messages.sourceTypeLabel).text()).not.toContain(messages.typeDatabase)
    expectNoI18nMisses(wrapper)
  })

  it('文档知识库匹配三种模板，且下拉里没有图谱库', async () => {
    // Arrange + Act
    const wrapper = await mountDialog({ knowledgeOptions: KB_OPTIONS })
    const templates = radiosOf(wrapper, messages.template).map(radio => radio.text())
    const sourceSelect = wrapper.find('[data-ep-stub="el-select"]')

    // Assert
    expect(templates.join('|')).toContain(messages.templateBlended)
    expect(templates.join('|')).toContain(messages.templateSequential)
    expect(templates.join('|')).toContain(messages.templateConditional)
    expect(templates.join('|')).not.toContain(messages.templateGraph)
    expect(sourceSelect.text()).toContain('产品手册库')
    expect(sourceSelect.text()).not.toContain('测试2')
    // 结构化库走数据库能力，文档下拉也不应出现
    expect(sourceSelect.text()).not.toContain('结构化库')
  })

  it('切到图谱知识库：模板只剩「图谱检索」，下拉只剩图谱库', async () => {
    // Arrange
    const wrapper = await mountDialog({ knowledgeOptions: KB_OPTIONS })

    // Act
    await radiosOf(wrapper, messages.sourceTypeLabel)[1].trigger('click')
    await flush()

    // Assert
    const templates = radiosOf(wrapper, messages.template).map(radio => radio.text())
    expect(templates).toHaveLength(1)
    expect(templates[0]).toContain(messages.templateGraph)
    expect(wrapper.vm.form.template).toBe('Blended')
    const sourceSelect = wrapper.find('[data-ep-stub="el-select"]')
    expect(sourceSelect.text()).toContain('测试2')
    expect(sourceSelect.text()).not.toContain('产品手册库')
  })

  it('切换类型会清空已选来源，并提示已重新匹配模板', async () => {
    // Arrange
    const wrapper = await mountDialog({ knowledgeOptions: KB_OPTIONS })
    wrapper.vm.form.sourceIds = ['doc-1']
    await flush()

    // Act
    await radiosOf(wrapper, messages.sourceTypeLabel)[1].trigger('click')
    await flush()

    // Assert
    expect(wrapper.vm.form.sourceIds).toEqual([])
    expect(wrapper.text()).toContain('已切换为图谱知识库')
    expect(wrapper.text()).toContain(messages.templateGraph)
  })

  it('图谱检索的流程预览给出「知识图谱检索」而不是混合检索', async () => {
    // Arrange
    const wrapper = await mountDialog({ knowledgeOptions: KB_OPTIONS })

    // Act
    await radiosOf(wrapper, messages.sourceTypeLabel)[1].trigger('click')
    await flush()

    // Assert
    const preview = wrapper.find('.workflow-template-preview')
    expect(preview.text()).toContain(messages.stepGraph)
    expect(preview.text()).toContain(messages.stepRerank)
    expect(preview.text()).toContain(messages.stepAnswer)
  })
})
