// @vitest-environment jsdom
// ↑ 本文件同时挂载组件（ModelFormDialog / ModelTable 的回归守卫）—— 组件测试需要 DOM。
//   纯契约用例在这里不受影响（`@/api/base` 本来就是桩，见下）。
import { h } from 'vue'
import { readFileSync } from 'node:fs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index'
import { ElSwitch } from 'element-plus/es/components/switch/index'
import { createModelApi, deleteModelApi, getThinkingPresetsApi, queryModelsApi, testModelApi, testModelConfigApi, updateModelApi } from '@/features/model/api/model'
import { KIND_LABEL_KEY, MODEL_KINDS, needsDimension, PATH_PLACEHOLDER } from '@/features/model/type'
import { flush, findByText, mountWithPlugins, normalizeText } from './helpers/mount'
import ModelFormDialog from '@/features/model/ModelFormDialog.vue'
import ModelTable from '@/features/model/ModelTable.vue'
import ModelTestResultTable from '@/features/model/ModelTestResultTable.vue'
import zhModelManagement from '@/app/i18n/zh/modelManagement'

// `@/api/base` 在导入期读 window / localStorage（见 api.stream.spec.js 的说明），
// node 环境里 import 不进来。这里换成记录调用的桩 —— 顺带把**请求形状**钉住。
const calls = []
//: 思考预置目录是表单内部辅助请求；单独记录，避免污染保存/测试的动词断言。
const catalogCalls = []
//: `/test` 结尾的 POST 返回一份形状完整的探测结果（`ModelTestResult`，见 type.ts），
//: 供「结果行」的渲染断言用；其余请求返回 {}（接口契约用例只用请求侧形状）。
const TEST_RESULT = {
  ok: true, probed: true, models: ['model-a'], dimension: null,
  dimensionMatches: null, latencyMs: 64, message: ''
}
const THINKING_PRESETS = [
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
      // 思考预置目录：按传入的 modelName 给一个匹配结果。
      // 记到 catalogCalls，不污染 calls —— 保存/测试用例只关心提交动词。
      if (url === '/api/co-knowledge/v1/models/thinking-presets') {
        catalogCalls.push({ method: 'get', url, config })
        const params = config?.params || {}
        const name = String(params.apiModel || params.modelName || '').toLowerCase()
        const matchedPresetId = name.includes('deepseek')
          ? 'deepseek-vllm'
          : (name.includes('qwen') ? 'qwen-vllm' : '')
        return Promise.resolve({
          presets: THINKING_PRESETS,
          matchedPresetId,
          matchedBy: matchedPresetId ? 'model_name' : '',
          confidence: matchedPresetId ? 'standard-doc' : '',
          warning: matchedPresetId || !name ? '' : 'no_preset_match',
          allowedPayloadKeys: ['chat_template_kwargs', 'thinking', 'reasoning_effort', 'enable_thinking', 'google'],
          maxPayloadBytes: 8192,
          modes: ['none', 'auto', 'preset', 'custom']
        })
      }
      calls.push({ method: 'get', url, config })
      // llm 页签的列表给一行真数据：ModelTable「行内连接测试 → 结果表」用例要真点行按钮。
      // 其余查询（含 rerank 空态用例）仍返回空对象 → 空表。
      if (url === '/api/co-knowledge/v1/models' && config?.params?.kind === 'llm') {
        return Promise.resolve({
          items: [{
            modelId: 'mdl-llm-0001', modelKind: 'llm', modelName: 'qwen-max',
            displayName: '', apiModel: '', baseUrl: 'http://10.0.0.9:4000/v1',
            apiKeyMasked: 'sk-****9f', hasApiKey: true, chatPath: '', embeddingsPath: '',
            modelsPath: '', rerankPath: '', dimension: null, maxTokens: null, temperature: null,
            timeout: null, isReasoning: false, thinkingDisabled: false,
            thinkingMode: 'auto', thinkingPreset: '', thinkingPayload: null,
            thinkingMatchedPresetId: 'qwen-vllm',
            thinkingMatchedPresetLabel: 'Qwen3（vLLM/SGLang）',
            thinkingMatchedPresetLabelEn: 'Qwen3 (vLLM/SGLang)',
            thinkingPresetLabel: '', thinkingPresetLabelEn: '', thinkingWarning: '',
            isDefault: false, enabled: true, source: 'user',
            remark: '', createTime: '', modifyTime: '', creator: ''
          }],
          total: 1
        })
      }
      return Promise.resolve({})
    },
    post: (url, data, config) => {
      calls.push({ method: 'post', url, data, config })
      return Promise.resolve(url.endsWith('/test') ? TEST_RESULT : {})
    },
    put: (url, data, config) => { calls.push({ method: 'put', url, data, config }); return Promise.resolve({}) },
    delete: (url, config) => { calls.push({ method: 'delete', url, config }); return Promise.resolve({}) }
  }
}))

// 测的是模型管理页的**对外契约**，不是渲染细节：
//
// 1. `api/model.js` 打的路由必须与后端 `compat/model_api/router.py` 注册的一模一样 ——
//    少一个斜杠、用错动词都只在真点页面时才暴露（后端那条兜底路由会把未知路径
//    变成 `0005 + msg:null`，看起来像「后端报错了」，而不是「前端打错地址」）。
// 2. `type.ts` 的「哪一类有哪些字段」判定表：三类模型共用一个页面，漏一类不会报错，
//    只会让那一类的表单少一个必填项 / 多一个用不上的字段。

describe('api/model.js', () => {
  beforeEach(() => { calls.length = 0; catalogCalls.length = 0 })

  it('列表：GET /models，类型与搜索词走 query', async () => {
    await queryModelsApi({ kind: 'embedding', keyword: 'qwen', currentPage: 2, pageSize: 10 })
    const [call] = calls
    expect(call.method).toBe('get')
    expect(call.url).toBe('/api/co-knowledge/v1/models')
    expect(call.config.params).toEqual({ kind: 'embedding', keyword: 'qwen', currentPage: 2, pageSize: 10 })
  })

  it('新建 / 更新 / 删除 / 两种连接测试都打在对的动词与路径上', async () => {
    await createModelApi({ modelName: 'm' })
    await updateModelApi('id-1', { modelName: 'm' })
    await deleteModelApi('id-1')
    await testModelApi('id-1', {})
    await testModelConfigApi({ modelName: 'm' })
    await getThinkingPresetsApi({ modelName: 'deepseek-chat' })

    expect(calls.map(call => [call.method, call.url])).toEqual([
      ['post', '/api/co-knowledge/v1/models'],
      ['put', '/api/co-knowledge/v1/models/id-1'],
      ['delete', '/api/co-knowledge/v1/models/id-1'],
      ['post', '/api/co-knowledge/v1/models/id-1/test'],
      ['post', '/api/co-knowledge/v1/models/test']
    ])
    expect(catalogCalls.map(call => [call.method, call.url])).toEqual([
      ['get', '/api/co-knowledge/v1/models/thinking-presets']
    ])
    expect(catalogCalls[0].config.params).toEqual({ modelName: 'deepseek-chat' })
  })

  it('连接测试允许调用方关掉自动错误弹窗', async () => {
    await testModelConfigApi({}, { skipErrorHandler: true })
    expect(calls[0].config).toEqual({ skipErrorHandler: true })
  })
})

describe('type.ts 的三类模型字段判定', () => {
  it('三类都有页签文案键（漏一类 = 页签显示成键名）', () => {
    expect(MODEL_KINDS).toEqual(['llm', 'embedding', 'rerank'])
    for (const kind of MODEL_KINDS) {
      expect(KIND_LABEL_KEY[kind]).toBe(`modules.modelManagement.tab${kind[0].toUpperCase()}${kind.slice(1)}`)
    }
  })

  it('只有 embedding 需要向量维度', () => {
    expect(needsDimension('embedding')).toBe(true)
    expect(needsDimension('llm')).toBe(false)
    expect(needsDimension('rerank')).toBe(false)
  })

  it('路径占位提示与后端 DEFAULT_PATHS 对齐', () => {
    // 后端服务目录的 models.py：llm → chat/models、embedding → embeddings、rerank → rerank
    // models 只有 LLM 有：清单探测的消费者只有生成端点那两处
    expect(PATH_PLACEHOLDER.llm).toEqual({ chatPath: '/chat/completions', modelsPath: '/models' })
    expect(PATH_PLACEHOLDER.embedding).toEqual({ embeddingsPath: '/embeddings' })
    expect(PATH_PLACEHOLDER.rerank).toEqual({ rerankPath: '/rerank' })
  })
})

describe('i18n 词条', () => {
  it('页面用到的键在 zh 与 en 里都在（缺一边会被一致性用例拦下，这里给出更早的定位）', async () => {
    const zh = (await import('@/app/i18n/zh/modelManagement')).default
    const en = (await import('@/app/i18n/en/modelManagement')).default
    expect(Object.keys(zh).sort()).toEqual(Object.keys(en).sort())
    expect(Object.keys(zh).length).toBeGreaterThan(40)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 组件级：编辑态必须认出行（回归守卫）
//
// 症状：任意行点「编辑」→ 弹窗标题
// 显示「新建模型」，保存实际发 **POST（新建）**：名字不变 → 永远报「同类型下已存在同名
// 模型：<自己>」；改名 → 「保存成功」但原行没动、静默多出一条重复行。
//
// 根因：行 → 表单只按 `SUBMITTABLE_FIELDS` 白名单拷字段（**不含 `modelId`**），
// `formData.modelId` 恒空 → `isEdit` 恒 false → 标题 / PUT-vs-POST / 连接测试
// 三条分支全走错。这几条用例把「openDialog(row) 之后必须是编辑态」钉死。
// ⛔ 回退修复（把 modelId 从拷贝名单里拿掉），第一条立刻红。
// ─────────────────────────────────────────────────────────────────────────────

/**
 * el-dialog：helpers 的占位件只渲默认插槽，而「确定 / 测试」按钮在 footer 插槽里 ——
 * 本组用例要真点它们，所以给一个同时渲默认 + footer 的局部透传件（标题也描出来，供断言）。
 */
const DialogPassthrough = {
  name: 'ElDialog',
  props: ['modelValue', 'title', 'width', 'appendToBody', 'closeOnPressEscape', 'closeOnClickModal', 'beforeClose'],
  setup (props, { slots }) {
    return () => h('div', { class: 'test-dialog' }, [
      h('div', { class: 'test-dialog__title' }, props.title),
      slots.default ? slots.default() : null,
      slots.footer ? slots.footer() : null
    ])
  }
}

/**
 * 挂 ModelFormDialog / ModelTable 要补的（helpers 的最小集之外）：
 * - 真 ElForm / ElFormItem：submit 走的是 `formRef.validate(cb)`，没表单组件这条链断了；
 * - 透传 dialog（见上）；
 * - 真 ElTable / ElTableColumn：连接测试结果以表格呈现，真渲染才能断言得到行；
 *   列表空态文案也靠真表格渲染出来；
 * - `$message` 桩：保存成功后的提示走 globalProperties；
 * - `loading` 指令桩：`v-loading` 由全量 EP 注册，这里给个空指令免得刷警告。
 */
const DIALOG_MOUNT_GLOBAL = {
  components: { ElDialog: DialogPassthrough, ElForm, ElFormItem, ElTable, ElTableColumn },
  directives: { loading: {} },
  config: { globalProperties: { $message: { success: () => {}, error: () => {} } } }
}


/** 一行 llm 模型（形状 = 列表接口的返回行，modelId 是 PUT 的目标） */
const EDIT_ROW = {
  modelId: 'mdl-llm-0001',
  modelKind: 'llm',
  modelName: 'qwen-max',
  displayName: 'Qwen Max',
  apiModel: '',
  baseUrl: 'http://10.0.0.9:4000/v1',
  apiKeyMasked: 'sk-****9f',
  hasApiKey: true,
  chatPath: '',
  embeddingsPath: '',
  modelsPath: '',
  rerankPath: '',
  dimension: null,
  maxTokens: null,
  temperature: null,
  timeout: null,
  isReasoning: false,
  thinkingDisabled: false,
  thinkingMode: 'preset',
  thinkingPreset: 'qwen-vllm',
  thinkingPayload: { chat_template_kwargs: { enable_thinking: false } },
  thinkingMatchedPresetId: '',
  thinkingMatchedPresetLabel: '',
  thinkingMatchedPresetLabelEn: '',
  thinkingPresetLabel: 'Qwen3（vLLM/SGLang）',
  thinkingPresetLabelEn: 'Qwen3 (vLLM/SGLang)',
  thinkingWarning: '',
  isDefault: false,
  enabled: true,
  source: 'user',
  remark: '',
  createTime: '2026-10-01 10:00:00',
  modifyTime: '2026-10-01 10:00:00',
  creator: 'admin'
}

async function mountDialog () {
  return mountWithPlugins(ModelFormDialog, { route: '/models', global: DIALOG_MOUNT_GLOBAL })
}

/** 点 footer 上某个按钮（文案取真词条），再等校验/请求的 promise 落地 */
async function clickFooterButton (wrapper, text) {
  const button = findByText(wrapper, text, 'button')
  expect(button, `footer 上找不到「${text}」按钮`).not.toBeNull()
  await button.trigger('click')
  await flush()
}

describe('ModelFormDialog：编辑态必须认出行（openDialog(row) → PUT）', () => {
  beforeEach(() => { calls.length = 0 })

  it('编辑保存：标题 =「编辑」，打 PUT /models/<modelId>（修前这里是 POST“新建”→ 必红）', async () => {
    // Arrange
    const wrapper = await mountDialog()

    // Act：走 ModelTable 真实编辑路径 —— openDialog(row) 后直接保存
    wrapper.vm.openDialog(EDIT_ROW)
    await flush()

    // 标题先钉：编辑态若显示「新建模型」就是坏的这一处
    expect(wrapper.find('.test-dialog__title').text()).toBe('编辑')
    await clickFooterButton(wrapper, '确定')

    // Assert：PUT + 主键在路径里；修前会看到 post /api/co-knowledge/v1/models（“新建”分支）
    expect(calls.map(call => [call.method, call.url])).toEqual([
      ['put', `/api/co-knowledge/v1/models/${EDIT_ROW.modelId}`]
    ])
    // 每模型思考配置必须原样带回（编辑 preset 行不能静默变 auto/none）
    expect(calls[0].data.thinkingMode).toBe('preset')
    expect(calls[0].data.thinkingPreset).toBe('qwen-vllm')
    expect(calls[0].data.thinkingPayload).toBe(null)
  })

  it('LLM 表单显示「思考配置」；embedding / rerank 表单不显示', async () => {
    const llmDialog = await mountWithPlugins(ModelFormDialog, {
      route: '/models', props: { kind: 'llm' }, global: DIALOG_MOUNT_GLOBAL
    })
    llmDialog.vm.openDialog()
    await flush()
    expect(llmDialog.text()).toContain(zhModelManagement.formThinkingMode)

    for (const kind of ['embedding', 'rerank']) {
      const dialog = await mountWithPlugins(ModelFormDialog, {
        route: '/models', props: { kind }, global: DIALOG_MOUNT_GLOBAL
      })
      dialog.vm.openDialog()
      await flush()
      expect(dialog.text()).not.toContain(zhModelManagement.formThinkingMode)
    }
  })

  it('编辑态「连接测试」打 /models/<id>/test（用库里那把 key），不是新建向导的 /models/test', async () => {
    // Arrange
    const wrapper = await mountDialog()
    wrapper.vm.openDialog(EDIT_ROW)
    await flush()

    // Act
    await clickFooterButton(wrapper, '连接测试')

    // Assert
    expect(calls.map(call => [call.method, call.url])).toEqual([
      ['post', `/api/co-knowledge/v1/models/${EDIT_ROW.modelId}/test`]
    ])
  })

  it('新建保存：标题 =「新增模型」，仍打 POST /models（防回归）', async () => {
    // Arrange
    const wrapper = await mountDialog()
    wrapper.vm.openDialog()
    await flush()
    expect(wrapper.find('.test-dialog__title').text()).toBe('新增模型')

    // 新建时表单是空的：按用户操作把必填项填上（选择器用真词条拼，别抄字面量）
    await wrapper.find(`input[placeholder="${zhModelManagement.formNamePlaceholder}"]`).setValue('qwen-plus')
    await wrapper.find(`input[placeholder="${zhModelManagement.formBaseUrlPlaceholder}"]`).setValue('http://10.0.0.9:4000/v1')

    // Act
    await clickFooterButton(wrapper, '确定')

    // Assert
    expect(calls.map(call => [call.method, call.url])).toEqual([
      ['post', '/api/co-knowledge/v1/models']
    ])
    // 新 LLM 默认自动匹配；payload 由后端在运行时解析
    expect(calls[0].data.thinkingMode).toBe('auto')
    expect(calls[0].data.thinkingPreset).toBe('')
    expect(calls[0].data.thinkingPayload).toBe(null)
  })

  it('自动模式按模型名显示匹配结果', async () => {
    const wrapper = await mountDialog()
    wrapper.vm.openDialog()
    await flush()

    const input = wrapper.find(`input[placeholder="${zhModelManagement.formNamePlaceholder}"]`)
    await input.setValue('deepseek-chat')
    await input.trigger('blur')
    await flush()
    await flush()

    expect(wrapper.text()).toContain('已匹配 DeepSeek（vLLM/SGLang）')
  })

  it('自动模式未匹配时给出提示但仍可保存', async () => {
    const wrapper = await mountDialog()
    wrapper.vm.openDialog()
    await flush()

    await wrapper.find(`input[placeholder="${zhModelManagement.formNamePlaceholder}"]`)
      .setValue('unknown-private-model')
    await wrapper.find(`input[placeholder="${zhModelManagement.formNamePlaceholder}"]`)
      .trigger('blur')
    await flush()
    await flush()

    expect(wrapper.text()).toContain(zhModelManagement.thinkingPreviewNoMatch)
    await wrapper.find(`input[placeholder="${zhModelManagement.formBaseUrlPlaceholder}"]`)
      .setValue('http://10.0.0.9:4000/v1')
    await clickFooterButton(wrapper, '确定')

    expect(calls[0].data.thinkingMode).toBe('auto')
  })

  it('自定义 JSON 原样提交解析后的对象', async () => {
    const customRow = {
      ...EDIT_ROW,
      thinkingMode: 'custom',
      thinkingPreset: '',
      thinkingPayload: { thinking: { type: 'disabled' } },
      thinkingPresetLabel: '',
      thinkingPresetLabelEn: ''
    }
    const wrapper = await mountDialog()
    wrapper.vm.openDialog(customRow)
    await flush()

    const textarea = wrapper.find('.model-form__thinking-json textarea')
    expect(textarea.element.value).toContain('"type": "disabled"')
    await clickFooterButton(wrapper, '确定')

    expect(calls[0].data.thinkingMode).toBe('custom')
    expect(calls[0].data.thinkingPayload).toEqual({ thinking: { type: 'disabled' } })
  })

  it('自定义 JSON 非法时阻止保存并提示', async () => {
    const customRow = {
      ...EDIT_ROW,
      thinkingMode: 'custom',
      thinkingPreset: '',
      thinkingPayload: { thinking: { type: 'disabled' } },
      thinkingPresetLabel: '',
      thinkingPresetLabelEn: ''
    }
    const wrapper = await mountDialog()
    wrapper.vm.openDialog(customRow)
    await flush()

    await wrapper.find('.model-form__thinking-json textarea').setValue('{not-json')
    await clickFooterButton(wrapper, '确定')
    await flush()

    // 校验未通过 → 不发请求（Element Plus 负责把错误文案渲染在表单项下）
    expect(calls).toHaveLength(0)
    expect(wrapper.find('.model-form__thinking-json textarea').element.value).toBe('{not-json')
  })
})

describe('ModelTable 空态：用页面自带文案，不是 EP 默认「暂无数据」', () => {
  it('列表为空时，原生 table 真渲染出 `empty` 词条', async () => {
    // Arrange：模型表是原生 table.list-table，空态是 tbody 里的 empty-row
    const wrapper = await mountWithPlugins(ModelTable, {
      route: '/models',
      props: { kind: 'rerank' },
      global: DIALOG_MOUNT_GLOBAL
    })
    await flush()

    // Assert
    expect(wrapper.find('.empty-row').text()).toBe(zhModelManagement.empty)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 状态列只有一列：开关 + 文案。
//
// 曾经并排放「状态（已启用 / 保存即生效）」和「启用（开关）」两列 —— 两列取的都是
// `enabled`，同一句话在一行里说了两遍；而「保存即生效」对每一行都没有信息量。
// 下面两条钉住：① 表头只剩一个「状态」列；② 关开关会写回 `enabled` 并翻成「已停用」。
// ─────────────────────────────────────────────────────────────────────────────
describe('ModelTable：状态列 = 开关 + 文案（不再单设「启用」列）', () => {
  const TABLE_MOUNT_GLOBAL = {
    ...DIALOG_MOUNT_GLOBAL,
    components: { ...DIALOG_MOUNT_GLOBAL.components, ElSwitch }
  }

  async function mountTable () {
    const wrapper = await mountWithPlugins(ModelTable, {
      route: '/models',
      props: { kind: 'llm' },
      global: TABLE_MOUNT_GLOBAL
    })
    wrapper.vm.refreshTableData()
    await flush()
    return wrapper
  }

  it('表头：勾选 / 名称 / 端点 / 密钥 / 状态 / 操作，没有「启用」列', async () => {
    // Arrange & Act
    const wrapper = await mountTable()
    const headers = wrapper.findAll('.models-table thead th').map(th => normalizeText(th.text()))

    // Assert
    expect(headers).toHaveLength(6)
    expect(headers[4]).toBe(zhModelManagement.columnHealth)
    expect(headers).not.toContain('启用')
    expect(wrapper.text()).not.toContain('保存即生效')
  })

  it('关掉开关：PUT enabled=false + isDefault=false，同一格文案翻成「已停用」', async () => {
    // Arrange
    calls.length = 0
    const wrapper = await mountTable()
    expect(normalizeText(wrapper.find('.models-table tbody .table-status').text()))
      .toBe(zhModelManagement.healthOk)

    // Act
    await wrapper.find('.models-table tbody .el-switch').trigger('click')
    await flush()

    // Assert
    const put = calls.find(call => call.method === 'put')
    expect(put, '关开关没有发 PUT').toBeTruthy()
    expect(put.url).toBe('/api/co-knowledge/v1/models/mdl-llm-0001')
    expect(put.data).toEqual({ enabled: false, isDefault: false })
    expect(normalizeText(wrapper.find('.models-table tbody .table-status').text()))
      .toBe(zhModelManagement.healthOff)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 英文侧两处易错点的守卫：
//   1. 编辑对话框 API 密钥占位符渲染成 `[object Object]` —— `keyPlaceholder` computed
//      返回 `storedKeyMask` **ref 本身**（漏 `.value`），模板把它字符串化。
//   2. 结果行/删除确认的冒号若硬编码全角「：」，en 下会渲染成 `Latency：64ms`。
//      冒号必须并入词条值（zh「：」/ en ": "），zh 渲染不能改变。
// ─────────────────────────────────────────────────────────────────────────────

describe('ModelFormDialog：API 密钥占位符（不是 [object Object]）', () => {
  beforeEach(() => { calls.length = 0 })

  it('编辑含已存密钥的行：placeholder = 脱敏值，输入框本体留空（留空 = 保留库里那把）', async () => {
    // Arrange
    const wrapper = await mountDialog()

    // Act
    wrapper.vm.openDialog(EDIT_ROW)
    await flush()

    // Assert
    const keyInput = wrapper.find('input[type="password"]')
    expect(keyInput.exists()).toBe(true)
    expect(keyInput.attributes('placeholder')).toBe(EDIT_ROW.apiKeyMasked)
    expect(keyInput.attributes('placeholder')).not.toContain('[object Object]')
    // 脱敏值只做**提示**：不回填输入框（回填会被当明文提交上去）
    expect(keyInput.element.value).toBe('')
  })

  it('新建态 / 行上没有已存密钥：没有占位提示', async () => {
    // Arrange
    const wrapper = await mountDialog()

    // Act + Assert：新建
    wrapper.vm.openDialog()
    await flush()
    expect(wrapper.find('input[type="password"]').attributes('placeholder') || '').toBe('')

    // Act + Assert：编辑一条未配置密钥的行
    wrapper.vm.openDialog({ ...EDIT_ROW, hasApiKey: false, apiKeyMasked: '' })
    await flush()
    expect(wrapper.find('input[type="password"]').attributes('placeholder') || '').toBe('')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 连接测试结果用**表格**展示。
//   渲染的唯一实现 = ModelTestResultTable（列表行弹窗与新建·编辑向导共用）；
//   行序固定：连接状态 → 端点声明的模型 → [实测向量维度] → 耗时。
//   旧用例钉的「冒号随语言」（en 曾渲染出全角「：」）在表格下换成：表头与行标签
//   词条本身不带冒号，且 en 弹窗整体仍不得出现全角冒号。
// ─────────────────────────────────────────────────────────────────────────────

/** 结果表的表头 → `['检查项', '结果']` */
function tableHeaders (wrapper) {
  return wrapper.findAll('.el-table__header th .cell').map(cell => normalizeText(cell.text()))
}

/** 结果表的行 → `[[标签, 值], ...]`（逐格取文本再折叠空白） */
function tableRows (wrapper) {
  return wrapper.findAll('.el-table__row')
    .map(tr => tr.findAll('td .cell').map(cell => normalizeText(cell.text())))
}

describe('ModelFormDialog：连接测试结果以表格渲染', () => {
  beforeEach(() => { calls.length = 0 })

  async function openTestResult (locale, testButtonText) {
    const wrapper = await mountWithPlugins(ModelFormDialog, {
      locale,
      route: '/models',
      global: DIALOG_MOUNT_GLOBAL
    })
    wrapper.vm.openDialog(EDIT_ROW)
    await flush()
    await clickFooterButton(wrapper, testButtonText)
    return wrapper
  }

  it('zh：表头「检查项 / 结果」；行 = 连接状态/端点声明的模型/耗时（TEST_RESULT: model-a, 64ms）', async () => {
    // Act
    const wrapper = await openTestResult('zh', '连接测试')

    // Assert
    expect(tableHeaders(wrapper)).toEqual([zhModelManagement.testResultItem, zhModelManagement.testResultValue])
    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testSuccess],
      [zhModelManagement.testResultModels, 'model-a'],
      [zhModelManagement.testResultLatency, '64ms']
    ])
  })

  it('en：同一张表用 en 词条，且全程没有全角「：」（回归面）', async () => {
    // Act
    const wrapper = await openTestResult('en', 'Test connection')

    // Assert
    expect(tableHeaders(wrapper)).toEqual(['Item', 'Result'])
    expect(tableRows(wrapper)).toEqual([
      ['Status', 'Endpoint reachable'],
      ['Models reported by the endpoint', 'model-a'],
      ['Latency', '64ms']
    ])
    expect(normalizeText(wrapper.text())).not.toContain('：')
  })
})

describe('ModelTable：行内「连接测试」的弹窗用同一张结果表', () => {
  beforeEach(() => { calls.length = 0 })

  it('点行按钮 → 结果弹窗渲染表格（连接状态/端点声明的模型/耗时）', async () => {
    // Arrange：llm 页签的 get 桩会返回一行（见文件头 mock）。
    // 原生 table 在 onMounted 取数；这里再手动刷一次，等一拍即可。
    const wrapper = await mountWithPlugins(ModelTable, {
      route: '/models',
      props: { kind: 'llm' },
      global: DIALOG_MOUNT_GLOBAL
    })
    wrapper.vm.refreshTableData()
    await flush()

    // Act：行内操作按钮里的「连接测试」（页内还有向导弹窗的同名按钮，必须限定在表格行里）
    const rowTestButton = wrapper.findAll('.list-table tbody tr .row-actions button')
      .find(btn => normalizeText(btn.text()) === zhModelManagement.test)
    expect(rowTestButton, '行内找不到「连接测试」按钮').toBeTruthy()
    await rowTestButton.trigger('click')
    await flush()

    // Assert：按标题找结果弹窗（页内还有向导/删除确认的 dialog 壳）
    const dialog = wrapper.findAll('.test-dialog')
      .find(d => d.find('.test-dialog__title').text() === zhModelManagement.testResultTitle)
    expect(dialog, '结果弹窗没出现').toBeTruthy()
    expect(tableHeaders(dialog)).toEqual([zhModelManagement.testResultItem, zhModelManagement.testResultValue])
    expect(tableRows(dialog)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testSuccess],
      [zhModelManagement.testResultModels, 'model-a'],
      [zhModelManagement.testResultLatency, '64ms']
    ])
  })

  it('LLM 行自动匹配时，名称列显示预设标签', async () => {
    const wrapper = await mountWithPlugins(ModelTable, {
      route: '/models',
      props: { kind: 'llm' },
      global: DIALOG_MOUNT_GLOBAL
    })
    wrapper.vm.refreshTableData()
    await flush()
    await flush()

    expect(wrapper.text()).toContain('自动 · Qwen3（vLLM/SGLang）')
  })
})

describe('ModelTestResultTable：行矩阵（后端 ModelTestResult 语义 → 行的映射）', () => {
  const BASE = {
    ok: true, probed: true, models: [], dimension: null,
    dimensionMatches: null, latencyMs: 10, message: ''
  }

  async function mountTable (result, registeredDimension = null, kind = '') {
    const wrapper = await mountWithPlugins(ModelTestResultTable, {
      route: '/models',
      props: { result, registeredDimension, kind },
      global: DIALOG_MOUNT_GLOBAL
    })
    // ⚠️ 必须等一拍：el-table 的行在首次渲染就出现，但**单元格**要等列 store 初始化的
    //    下一 tick 才铺出来 —— 少了这拍，`td .cell` 全是 0 个。
    await flush()
    return wrapper
  }

  it('embedding 维度一致：第 2 行 =「实测向量维度 / 1024（与登记的维度一致）」', async () => {
    // Act
    const wrapper = await mountTable(
      { ...BASE, models: null, dimension: 1024, dimensionMatches: true }, 1024, 'embedding')

    // Assert：embedding 不出「端点声明的模型」行（只有 LLM 有清单能力）
    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testSuccess],
      [zhModelManagement.testResultDimension, `1024（${zhModelManagement.testResultDimensionOk}）`],
      [zhModelManagement.testResultLatency, '10ms']
    ])
  })

  it('维度不一致：值里带上登记值（登记 768）', async () => {
    // Act
    const wrapper = await mountTable(
      { ...BASE, models: null, dimension: 1024, dimensionMatches: false }, 768, 'embedding')

    // Assert
    expect(tableRows(wrapper)[1]).toEqual([
      zhModelManagement.testResultDimension,
      `1024（${zhModelManagement.testResultDimensionMismatch.replace('{0}', '768')}）`
    ])
  })

  it('ok=false + probed=null：状态 =「部分可达」（warning tag），清单行落到「无法判定」说明', async () => {
    // Act：只有 LLM 会走到「清单探测失败」这一态
    const wrapper = await mountTable({ ...BASE, ok: false, probed: null, models: null }, null, 'llm')

    // Assert
    expect(wrapper.find('.el-tag').classes()).toContain('el-tag--warning')
    expect(tableRows(wrapper)[1]).toEqual([
      zhModelManagement.testResultModels,
      zhModelManagement.testResultUndetermined
    ])
  })

  it('ok=false + probed=false：状态 =「不可达」（danger tag）', async () => {
    // Act
    const wrapper = await mountTable({ ...BASE, ok: false, probed: false, models: null }, null, 'llm')

    // Assert
    expect(wrapper.find('.el-tag').classes()).toContain('el-tag--danger')
  })

  it('llm（无维度行）：只有 状态/清单/耗时 三行；多模型用「、」连接', async () => {
    // Act
    const wrapper = await mountTable({ ...BASE, models: ['a', 'b'] }, null, 'llm')

    // Assert
    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testSuccess],
      [zhModelManagement.testResultModels, 'a、b'],
      [zhModelManagement.testResultLatency, '10ms']
    ])
  })
})

describe('冒号约定：模板里禁止硬编码全角冒号（词条化）', () => {
  // 结果行改表格后，带冒号的拼接词条只剩删除确认的「模型名称：<名字>」。
  const COLON_KEYS = ['deleteConfirmName']

  it('zh 词条以全角「：」收尾、en 词条以半角「:」收尾且不含全角冒号', async () => {
    const zh = (await import('@/app/i18n/zh/modelManagement')).default
    const en = (await import('@/app/i18n/en/modelManagement')).default
    for (const key of COLON_KEYS) {
      expect(zh[key], `zh.${key} 缺失`).toBeTruthy()
      expect(zh[key].endsWith('：'), `zh.${key} 应以全角冒号收尾`).toBe(true)
      expect(en[key], `en.${key} 缺失`).toBeTruthy()
      expect(en[key].includes('：'), `en.${key} 不能含全角冒号`).toBe(false)
      expect(en[key].trimEnd().endsWith(':'), `en.${key} 应以半角冒号收尾`).toBe(true)
    }
  })

  it('结果表与两个页面的模板/拼接里没有「}}：」/「\'：\'」形态（冒号必须来自词条）', () => {
    // 路径从 process.cwd() 拼（= `npm run test:unit` 的 frontend/）：
    // ⛔ 别用 `new URL('../..', import.meta.url)` —— vitest 会重写 import.meta.url，
    //    解析出来是 `/src/...`（缺仓库前缀），readFileSync 直接 ENOENT。
    for (const file of ['ModelFormDialog.vue', 'ModelTable.vue', 'ModelTestResultTable.vue']) {
      const source = readFileSync(`src/features/model/${file}`, 'utf8')
      expect(source, `${file} 仍把全角冒号贴在 $t 插值后`).not.toMatch(/\}\}：/)
      expect(source, `${file} 仍硬编码全角冒号字面量`).not.toMatch(/['"`]：/)
    }
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// LLM 连接测试走**真实调用**：
//   `/models` 清单里有名字 ≠ 能推理（有的模型能列出来但 chat 返回 404）。
//   状态以 `chatOk` 为准，「真实调用」行把端点给的失败原因摊开。
// ─────────────────────────────────────────────────────────────────────────────
describe('ModelTestResultTable：LLM 真实调用结果', () => {
  async function mountResult (result) {
    const wrapper = await mountWithPlugins(ModelTestResultTable, {
      router: null,
      props: { result },
      global: { components: { ElTable, ElTableColumn } }
    })
    // el-table 的列 store 比数据晚一拍铺单元格（与 ModelTable 行内用例同一个坑）
    await flush()
    await flush()
    return wrapper
  }

  it('chatOk=true：状态「模型调用成功」，真实调用行显示成功', async () => {
    const wrapper = await mountResult({
      ok: true, chatOk: true, chatError: '', probed: true, models: ['model-a'],
      dimension: null, dimensionMatches: null, latencyMs: 12, message: ''
    })

    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testCallSuccess],
      [zhModelManagement.testResultCall, zhModelManagement.testResultCallSucceeded],
      [zhModelManagement.testResultModels, 'model-a'],
      [zhModelManagement.testResultLatency, '12ms']
    ])
  })

  it('chatOk=false：清单里仍有该模型也必须判失败，并展示端点给的失败原因', async () => {
    const failure = 'model call failed: HTTP 404: Received Model Group=qwen3-32b'
    const wrapper = await mountResult({
      ok: false, chatOk: false, chatError: failure, probed: true, models: ['qwen3-32b'],
      dimension: null, dimensionMatches: null, latencyMs: 60, message: failure
    })

    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testCallFailed],
      [zhModelManagement.testResultCall, failure],
      [zhModelManagement.testResultModels, 'qwen3-32b'],
      [zhModelManagement.testResultLatency, '60ms']
    ])
  })

  it('没有 chatOk（embedding）时保持原行序与原语义', async () => {
    const wrapper = await mountResult({
      ok: true, probed: true, models: ['Qwen3-Embedding-0.6B'], dimension: 1024,
      dimensionMatches: true, latencyMs: 40, message: ''
    })

    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testSuccess],
      [zhModelManagement.testResultModels, 'Qwen3-Embedding-0.6B'],
      [zhModelManagement.testResultDimension, `1024（${zhModelManagement.testResultDimensionOk}）`],
      [zhModelManagement.testResultLatency, '40ms']
    ])
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// embedding 连接测试给出「真实调用」结果：
//   路径少一段（`/embeddings` vs `/v1/embeddings`）时后端只回兜底文案
//   「endpoint unreachable or undetermined」，界面显示「端点可达，但无法确认模型清单」，
//   看不出是 HTTP 404。现在状态以 `embeddingsOk` 为准，并摊开 URL + HTTP 状态。
// ─────────────────────────────────────────────────────────────────────────────
describe('ModelTestResultTable：embedding 真实调用结果', () => {
  async function mountEmbedding (result) {
    const wrapper = await mountWithPlugins(ModelTestResultTable, {
      router: null,
      props: { result, kind: 'embedding' },
      global: { components: { ElTable, ElTableColumn } }
    })
    await flush()
    await flush()
    return wrapper
  }

  it('embeddingsOk=false：状态「模型调用失败」，摊开 URL + HTTP 状态，不出清单行', async () => {
    const failure = 'model call failed: HTTP 404 (POST https://llm.example.com/embeddings)'
    const wrapper = await mountEmbedding({
      ok: false, probed: null, models: null,
      embeddingsOk: false, embeddingsError: failure,
      dimension: null, dimensionMatches: null, latencyMs: 76, message: failure
    })

    expect(wrapper.find('.el-tag').classes()).toContain('el-tag--danger')
    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testCallFailed],
      [zhModelManagement.testResultCall, failure],
      [zhModelManagement.testResultLatency, '76ms']
    ])
  })

  it('embeddingsOk=true：状态「模型调用成功」+ 调用成功行 + 实测维度', async () => {
    const wrapper = await mountEmbedding({
      ok: true, probed: null, models: null, embeddingsOk: true, embeddingsError: '',
      dimension: 1024, dimensionMatches: true, latencyMs: 79, message: 'model call succeeded'
    })

    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testCallSuccess],
      [zhModelManagement.testResultCall, zhModelManagement.testResultCallSucceeded],
      [zhModelManagement.testResultDimension, `1024（${zhModelManagement.testResultDimensionOk}）`],
      [zhModelManagement.testResultLatency, '79ms']
    ])
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// rerank 连接测试走**真实调用**：
//   rerank 端点通常没有 `/models`（请求 `/models` 会 404），
//   没有真实调用时，正确的端点会被报成「端点可达，但无法确认模型清单」+ 0ms。
//   现在状态以 `rerankOk` 为准，且 rerank 不出「端点声明的模型」这一行。
// ─────────────────────────────────────────────────────────────────────────────
describe('ModelTestResultTable：rerank 真实调用结果', () => {
  async function mountRerank (result, kind = 'rerank') {
    const wrapper = await mountWithPlugins(ModelTestResultTable, {
      router: null,
      props: { result, kind },
      global: { components: { ElTable, ElTableColumn } }
    })
    await flush()
    await flush()
    return wrapper
  }

  it('rerankOk=true：状态「模型调用成功」，真实调用行成功，且不出清单行', async () => {
    const wrapper = await mountRerank({
      ok: true, rerankOk: true, rerankError: '', probed: null, models: null,
      dimension: null, dimensionMatches: null, latencyMs: 41, message: 'model call succeeded'
    })

    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testCallSuccess],
      [zhModelManagement.testResultCall, zhModelManagement.testResultCallSucceeded],
      [zhModelManagement.testResultLatency, '41ms']
    ])
  })

  it('rerankOk=false：状态「模型调用失败」，真实调用行摊开端点给的失败原因', async () => {
    const failure = 'rerank call failed: HTTP 404: The model `nope` does not exist.'
    const wrapper = await mountRerank({
      ok: false, rerankOk: false, rerankError: failure, probed: null, models: null,
      dimension: null, dimensionMatches: null, latencyMs: 12, message: failure
    })

    expect(tableRows(wrapper)).toEqual([
      [zhModelManagement.testResultStatus, zhModelManagement.testCallFailed],
      [zhModelManagement.testResultCall, failure],
      [zhModelManagement.testResultLatency, '12ms']
    ])
  })
})
