// @vitest-environment jsdom
// 新模型弹窗（0.1.3 起实际使用的入口）的思考配置回归守卫：
// `none` 是「不配置」，真正关闭走 `auto`（运行时匹配关闭/最低档预置）。
// 组件用的是 `@/app/i18n/i18n.js` 的 `$t`（导入期读 localStorage），
// 所以在 import 之前把语言钉成中文，否则断言会拿到 jsdom 的 en-US。
vi.hoisted(() => {
  window.localStorage.setItem('language-option', JSON.stringify('zh-CN'))
})

import { h, Fragment } from 'vue'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { flush, mountWithPlugins } from './helpers/mount'
import ModelEditorDialog from '@/features/model/components/ModelEditorDialog.vue'
import zhModelManagement from '@/app/i18n/zh/modelManagement'
import zhStudioDialogs from '@/app/i18n/zh/studioDialogs'

const PRESETS = [
  {
    presetId: 'deepseek-vllm',
    label: 'DeepSeek（vLLM/SGLang）',
    labelEn: 'DeepSeek (vLLM/SGLang)',
    note: '本部署实测',
    noteEn: 'Verified here',
    payload: { chat_template_kwargs: { thinking: false } },
    fullOff: true,
    confidence: 'verified'
  },
  {
    presetId: 'qwen-vllm',
    label: 'Qwen3（vLLM/SGLang）',
    labelEn: 'Qwen3 (vLLM/SGLang)',
    note: '厂商文档写法',
    noteEn: 'Vendor documentation',
    payload: { chat_template_kwargs: { enable_thinking: false } },
    fullOff: true,
    confidence: 'standard-doc'
  }
]

vi.mock('@/shared/api/client', () => ({
  default: {
    get: (url, config) => {
      if (url === '/api/co-knowledge/v1/models/thinking-presets') {
        const params = config?.params || {}
        const name = String(params.apiModel || params.modelName || '').toLowerCase()
        return Promise.resolve({
          presets: PRESETS,
          matchedPresetId: name.includes('deepseek') ? 'deepseek-vllm' : '',
          allowedPayloadKeys: ['chat_template_kwargs', 'thinking', 'reasoning_effort', 'enable_thinking', 'google']
        })
      }
      return Promise.resolve({})
    },
    post: () => Promise.resolve({}),
    put: () => Promise.resolve({}),
    delete: () => Promise.resolve({})
  }
}))

/** v-for 的 slot 是一个 Fragment；把里面的 el-option 摊平才能读到 value/label。 */
function flattenOptions (vnodes) {
  return vnodes.flatMap(vnode => (
    vnode.type === Fragment && Array.isArray(vnode.children)
      ? flattenOptions(vnode.children)
      : [vnode]
  ))
}

/** 用原生 select 代替 el-select，才能直接切换思考模式并读到 option 文案。 */
const ElSelectStub = {
  name: 'ElSelect',
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup (props, { slots, emit }) {
    return () => h('select', {
      class: 'stub-select',
      value: props.modelValue,
      onChange: event => emit('update:modelValue', event.target.value)
    }, flattenOptions(slots.default?.() || []).map(vnode => h('option', {
      value: vnode.props?.value,
      selected: vnode.props?.value === props.modelValue
    }, vnode.props?.label)))
  }
}

const inert = name => ({
  name,
  props: { modelValue: { type: [Boolean, Number, String], default: undefined } },
  emits: ['update:modelValue'],
  setup: () => () => h('span')
})

const GLOBAL = {
  components: {
    ElForm,
    ElFormItem,
    ElSelect: ElSelectStub,
    ElSwitch: inert('ElSwitch'),
    ElInputNumber: inert('ElInputNumber'),
    ElCheckbox: inert('ElCheckbox')
  }
}

async function mountDialog (props = {}) {
  const wrapper = await mountWithPlugins(ModelEditorDialog, {
    route: '/models',
    props: { modelValue: false, submitHandler: vi.fn(), ...props },
    global: GLOBAL
  })
  await wrapper.setProps({ modelValue: true })
  await flush()
  return wrapper
}

async function fillRequired (wrapper, name = 'deepseek-chat') {
  await wrapper.find(`input[aria-label="${zhStudioDialogs.modelEditor.name}"]`).setValue(name)
  await wrapper.find(`input[aria-label="${zhStudioDialogs.modelEditor.endpoint}"]`)
    .setValue('http://10.0.0.1:4000/v1')
}

async function submit (wrapper) {
  await wrapper.find('form').trigger('submit')
  await flush()
}

describe('ModelEditorDialog：思考配置', () => {
  it('「关闭思考」= auto（真正匹配关闭预置）；「不发送」= none', async () => {
    const wrapper = await mountDialog()

    const labels = wrapper.findAll('option').map(option => option.text())

    expect(labels).toContain(zhStudioDialogs.modelEditor.thinkingAuto)
    expect(labels).toContain(zhStudioDialogs.modelEditor.thinkingOff)
    expect(zhStudioDialogs.modelEditor.thinkingAuto).toContain('关闭思考')
    expect(zhStudioDialogs.modelEditor.thinkingOff).toContain('不发送')
  })

  it('默认 auto：按模型名匹配预置并提示；保存提交 thinkingMode=auto', async () => {
    const submitHandler = vi.fn()
    const wrapper = await mountDialog({ submitHandler })

    await fillRequired(wrapper)
    await wrapper.find(`input[aria-label="${zhStudioDialogs.modelEditor.name}"]`).trigger('blur')
    await flush()

    expect(wrapper.text()).toContain(
      zhModelManagement.thinkingPreviewMatched.replace('{label}', 'DeepSeek（vLLM/SGLang）'))

    await submit(wrapper)

    expect(submitHandler).toHaveBeenCalledTimes(1)
    const values = submitHandler.mock.calls[0][0]
    expect(values.thinkingMode).toBe('auto')
    expect(values.thinkingPreset).toBe('')
    expect(values.thinkingPayload).toBe(null)
  })

  it('选「不发送」保存 thinkingMode=none，不发送任何思考片段', async () => {
    const submitHandler = vi.fn()
    const wrapper = await mountDialog({ submitHandler })

    await fillRequired(wrapper)
    await wrapper.find('select.stub-select').setValue('none')
    await submit(wrapper)

    expect(submitHandler).toHaveBeenCalledTimes(1)
    const values = submitHandler.mock.calls[0][0]
    expect(values.thinkingMode).toBe('none')
    expect(values.thinkingPreset).toBe('')
    expect(values.thinkingPayload).toBe(null)
  })

  it('auto 未匹配时明确提示「不会发送」，不再假装已关闭', async () => {
    const wrapper = await mountDialog()

    await fillRequired(wrapper, 'private-model-1')
    await wrapper.find(`input[aria-label="${zhStudioDialogs.modelEditor.name}"]`).trigger('blur')
    await flush()

    expect(wrapper.text()).toContain(zhModelManagement.thinkingPreviewNoMatch)
  })
})
