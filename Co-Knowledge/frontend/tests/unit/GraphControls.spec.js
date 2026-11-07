// @vitest-environment jsdom
// ↑ 组件测试：要挂载 GraphControls.vue，触发真实 DOM 事件（click）与组件事件（blur）
import fs from 'node:fs'
import path from 'node:path'
import { h } from 'vue'

import { ElInputNumber } from 'element-plus/es/components/input-number/index'

import { flush, mountWithPlugins, textOf } from './helpers/mount'

import GraphControls from '@/features/graph/components/GraphControls.vue'

// 测的是 `src/features/graph/components/GraphControls.vue`（条件编辑器：查询面板）。
//
// 这份 spec 只钉**三处看着像 bug、但属于有意保持的语义**的行为 ——
// 目的是把它们冻住，防止将来有人"顺手修"：
//
//   1) 行数上限守卫 `conditions.length >= propOptionsCount * 2`：属性表为空时 1 >= 0 恒真，
//      "加条件"按钮点了只弹一条指错方向的 warning —— 已知缺陷，本仓保持；
//   2) `handleLimitBlur` 无效值兜底发 50，与组件自身默认 100 不一致
//      ——50 对应的是调用方页面（KnowledgeGraphDetail.vue:213）的初始值，不是随手写的数；
//   3) `validateConditionRow` 只声明 1 个形参，但有 4 处调用传 3 个实参
//      ——多余实参被 JS 静默忽略。
//
// 每条"钉住"的用例都配了阳性对照/边界用例（能加行的那一侧），否则"点了没反应"也可能是
// 按钮整个坏了，测试会假绿。

// ── ElMessage：组件唯一的"用户可见反馈"出口，拦下来直接断言 ────────────────────
// mock 掉整个 `element-plus` 裸导入：GraphControls 只用它一个导出（ElMessage），
// 就地换成一个 spy，比让真 ElMessage 往 document.body 里塞浮层干净。
// （helpers/mount.js 注册 EP 组件走的是 `element-plus/es/components/*` 子路径，不受影响。）
const { warningSpy } = vi.hoisted(() => ({ warningSpy: vi.fn() }))
vi.mock('element-plus', () => ({
  ElMessage: { warning: warningSpy, success: vi.fn(), error: vi.fn(), info: vi.fn() }
}))

// ── el-select 替身 ─────────────────────────────────────────────────────────────
// helpers 里 el-select 是占位件（不能交互），真 el-select 在 jsdom 里要开 teleport 弹层、
// 点选项，代价大且脆。这里覆盖成一个只保留"组件用到的那部分契约"（v-model / change）的替身，
// 由测试用 $emit 驱动 —— 被测的是 GraphControls 的守卫逻辑，不是下拉控件本身。
// class / placeholder 等属性照常透传到替身根节点，所以定位按 DOM 选择器走。
const ElSelectStub = {
  name: 'ElSelect',
  props: {
    modelValue: { default: undefined },
    placeholder: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
    clearable: { type: Boolean, default: false },
    size: { type: String, default: '' }
  },
  emits: ['update:modelValue', 'change'],
  setup () {
    return () => h('div')
  }
}

async function mountControls (props = {}) {
  const wrapper = await mountWithPlugins(GraphControls, {
    router: null, // 组件不读路由，省一跳
    props,
    global: { components: { ElSelect: ElSelectStub, ElInputNumber } }
  })
  // 0.1.0：复杂条件默认收在「高级查询」里；这些用例测的就是条件编辑器本身。
  const advanced = wrapper.findAll('button').find(btn => textOf(btn).includes('高级查询'))
  expect(advanced, '工具条里找不到「高级查询」按钮').toBeTruthy()
  await advanced.trigger('click')
  await flush()
  return wrapper
}

/** 定位某选择器命中的 el-select 替身实例（替身根节点就是带 class 的那层）。 */
function selectAt (wrapper, selector) {
  const element = wrapper.find(selector).element
  return wrapper.findAllComponents(ElSelectStub).find(c => c.element === element) || null
}

/**
 * 用某个 el-select 选一个值：先 update:modelValue（v-model 写回）再 change（业务回调），
 * 与 Element Plus 真实下拉的发射顺序一致。
 */
async function chooseSelect (wrapper, selector, value) {
  const select = selectAt(wrapper, selector)
  expect(select, `找不到 ${selector} 命中的 el-select`).not.toBeNull()
  select.vm.$emit('update:modelValue', value)
  select.vm.$emit('change', value)
  await flush()
}

/** 条件行数（默认查询类型下只有"当前组"一组）。 */
function conditionRows (wrapper) {
  return wrapper.findAll('.condition-row')
}

/** 第 index 行左侧的"+"按钮（.col-actions 里按模板顺序：先加、后删）。 */
function addButton (wrapper, index = 0) {
  return conditionRows(wrapper)[index].findAll('.col-actions button')[0]
}

// i18n 真值，抄自 `src/i18n/zh/kb.js:683`（本地挂载的是真词条 zh）
const ROW_LIMIT_MESSAGE = '属性条件个数不能超过可选属性总数的两倍'
// 组件的提示出口已统一走 `@/lib/message`（默认注入 showClose: true），
// 所以落到 ElMessage.warning 的实参是规范化后的配置对象，而不是裸字符串。
const ROW_LIMIT_PAYLOAD = { showClose: true, message: ROW_LIMIT_MESSAGE, type: 'warning' }

const STRING_PROP = { name: 'name', type: 'STRING' }

describe('GraphControls 条件编辑器', () => {
  beforeEach(() => {
    warningSpy.mockClear()
  })

  describe('行数上限守卫：属性表为空时加不了第二个条件（上游既有缺陷，钉住）', () => {
    // 触发条件：类型出现在下拉里（entityTypes），但属性表缺失或为空 ——
    // 两份数据都源自同一份 schemaInfo，schemaMapper.js:85 就是 `entity.properties || []`，
    // 所以"类型在、属性为空"是合法且真的会发生的状态。
    it.each([
      ['属性表缺这个类型', {}],
      ['属性表里是空数组', { EmptyType: [] }]
    ])('%s：类型选好后点"+"，不加行、只弹行数上限 warning（1 >= 0 恒真）', async (_label, entityTypeProperties) => {
      // Arrange
      const wrapper = await mountControls({ entityTypes: ['EmptyType'], entityTypeProperties })
      await chooseSelect(wrapper, '.entity-select', 'EmptyType')

      // Assert：按钮没被禁用 —— 挡人的是守卫，不是 disabled（这点是缺陷的核心）
      const button = addButton(wrapper)
      expect(button.attributes('disabled')).toBeUndefined()
      expect(conditionRows(wrapper)).toHaveLength(1)

      // Act
      await button.trigger('click')

      // Assert
      expect(warningSpy).toHaveBeenCalledTimes(1)
      expect(warningSpy).toHaveBeenCalledWith(ROW_LIMIT_PAYLOAD)
      expect(conditionRows(wrapper)).toHaveLength(1)
    })

    it('子图模式的起始实体组同样：属性为空 → 加不了行、弹同一条 warning（4 处守卫逐字相同）', async () => {
      // Arrange：切到子图路径查询，起始实体组的 el-select 是第一个 .entity-select
      const wrapper = await mountControls({ entityTypes: ['EmptyType'], entityTypeProperties: { EmptyType: [] } })
      await chooseSelect(wrapper, '.query-type-select', 'subgraph')
      await chooseSelect(wrapper, '.entity-select', 'EmptyType')

      // Act
      await addButton(wrapper).trigger('click')

      // Assert：起始实体组仍只有 1 行（子图模式另有 2 个途径组，也各 1 行）
      expect(warningSpy).toHaveBeenCalledWith(ROW_LIMIT_PAYLOAD)
      expect(wrapper.findAll('.entity-group')[0].findAll('.condition-row')).toHaveLength(1)
      expect(conditionRows(wrapper)).toHaveLength(3)
    })

    it('阳性对照：属性表非空时点"+"能加行（否则上面的"不加行"可能只是按钮坏了）', async () => {
      // Arrange
      const wrapper = await mountControls({
        entityTypes: ['Person'],
        entityTypeProperties: { Person: [STRING_PROP] }
      })
      await chooseSelect(wrapper, '.entity-select', 'Person')

      // Act
      await addButton(wrapper).trigger('click')

      // Assert
      expect(conditionRows(wrapper)).toHaveLength(2)
      expect(warningSpy).not.toHaveBeenCalled()
    })

    it('边界：1 个属性 → 上限 2 行。第 2 行能加，第 3 行被拒（"两倍"语义本身就是上限）', async () => {
      // Arrange
      const wrapper = await mountControls({
        entityTypes: ['Person'],
        entityTypeProperties: { Person: [STRING_PROP] }
      })
      await chooseSelect(wrapper, '.entity-select', 'Person')

      // Act：第一次加成功
      await addButton(wrapper).trigger('click')
      expect(conditionRows(wrapper)).toHaveLength(2)

      // Act：第二次撞上限（2 >= 1 * 2）
      await addButton(wrapper, 1).trigger('click')

      // Assert
      expect(warningSpy).toHaveBeenCalledTimes(1)
      expect(conditionRows(wrapper)).toHaveLength(2)
    })
  })

  describe('limit 输入的 blur 兜底（50）与钳制（1..1000）—— 有意保持，钉住', () => {
    /** 触发 limit 输入框的 blur（走组件声明的 blur 事件，不碰 EP 内部）。 */
    async function blurLimit (wrapper) {
      const numberInput = wrapper.findComponent(ElInputNumber)
      expect(numberInput.exists()).toBe(true)
      numberInput.vm.$emit('blur', new FocusEvent('blur'))
      await flush()
    }

    it('兜底值仍是 50（不是组件默认的 100）：父组件显式传 null 时 blur 发 50', async () => {
      // Arrange：显式传 null —— prop 默认值只对 undefined 生效，null 会原样进来
      const wrapper = await mountControls({ limitValue: null })

      // Act
      await blurLimit(wrapper)

      // Assert
      expect(wrapper.emitted('limit-change')).toEqual([[50]])
    })

    it('NaN 同样走 50 兜底（判据是 Number.isNaN，不是"falsy"）', async () => {
      // Arrange
      const wrapper = await mountControls({ limitValue: NaN })

      // Act
      await blurLimit(wrapper)

      // Assert
      expect(wrapper.emitted('limit-change')).toEqual([[50]])
    })

    it('越界值按 1..1000 钳制：0 → 1、5000 → 1000', async () => {
      // Arrange / Act / Assert
      const below = await mountControls({ limitValue: 0 })
      await blurLimit(below)
      expect(below.emitted('limit-change')).toEqual([[1]])

      const above = await mountControls({ limitValue: 5000 })
      await blurLimit(above)
      expect(above.emitted('limit-change')).toEqual([[1000]])
    })

    it('合法值（100）blur 不发事件（钳制结果与当前值相同就静默）', async () => {
      // Arrange
      const wrapper = await mountControls({ limitValue: 100 })

      // Act
      await blurLimit(wrapper)

      // Assert
      expect(wrapper.emitted('limit-change')).toBeUndefined()
    })
  })

  describe('validateConditionRow 的"签名漂移"：1 参签名 + 4 处 3 实参调用（有意保持，勿改）', () => {
    // 行为面：多余实参被忽略 ⇒ 校验结果只由 row 决定，与传入的 (typeName, mode) 无关。
    it('同一行内容经"三参调用"与"一参调用"得到同一 error（多余实参不影响结果）', async () => {
      // Arrange
      const wrapper = await mountControls({
        entityTypes: ['Person'],
        entityTypeProperties: { Person: [{ name: 'age', type: 'INTEGER' }] }
      })
      await chooseSelect(wrapper, '.entity-select', 'Person')
      // 3 参调用点（handlePropChange）→ 自动补第一个允许的运算符 eq
      await chooseSelect(wrapper, '.col-prop .condition-select', 'age')

      // Act：运算符选 gt 但值为空 → 1 参调用点（handleOperatorChange）先报"不能为空"
      await chooseSelect(wrapper, '.col-operator .condition-select', 'gt')
      const viaOneArg = textOf(wrapper.find('.col-value .error-msg'))

      // Act：重选同一属性，再走一次 3 参调用点
      await chooseSelect(wrapper, '.col-prop .condition-select', 'age')
      const viaThreeArgs = textOf(wrapper.find('.col-value .error-msg'))

      // Assert
      expect(viaOneArg.startsWith('该运算符下值不能为空')).toBe(true)
      expect(viaThreeArgs).toBe(viaOneArg)
    })

    it('换类型名、换查询模式（entity vs relation）结果不变 —— 实参里的 type/mode 没被用上', async () => {
      // Arrange：两个完全不同的 (type, mode) 上下文，行内容相同
      const errorFor = async ({ entityTypes, edgeTypes, entityTypeProperties, edgeTypeProperties, queryType, type }) => {
        const wrapper = await mountControls({ entityTypes, edgeTypes, entityTypeProperties, edgeTypeProperties })
        if (queryType === 'relation') {
          await chooseSelect(wrapper, '.query-type-select', 'relation')
        }
        await chooseSelect(wrapper, '.entity-select', type)
        await chooseSelect(wrapper, '.col-prop .condition-select', 'p')
        await chooseSelect(wrapper, '.col-operator .condition-select', 'gt')
        return textOf(wrapper.find('.col-value .error-msg'))
      }

      // Act
      const entityError = await errorFor({
        entityTypes: ['Person'],
        entityTypeProperties: { Person: [{ name: 'p', type: 'INTEGER' }] },
        queryType: 'entity',
        type: 'Person'
      })
      const relationError = await errorFor({
        edgeTypes: ['Knows'],
        edgeTypeProperties: { Knows: [{ name: 'p', type: 'LONG' }] },
        queryType: 'relation',
        type: 'Knows'
      })

      // Assert
      expect(entityError).not.toBe('')
      expect(relationError).toBe(entityError)
    })

    // 源码面：行为面测不出"签名/实参被删"（删了行为不变），只钉得住"结果一致"。
    // 因此这里额外把**源码形状**钉死，防止有人"顺手"把签名补成 3 参或把实参删干净。
    // ⚠️ jsdom 环境里 `import.meta.url` 是 http://localhost/...（不是 file:），
    // 只能用 cwd 拼；vitest 的 root 就是 frontend/（`npm run test:unit` 在 frontend/ 下跑）。
    const SOURCE = fs.readFileSync(
      path.resolve(process.cwd(), 'src/features/graph/components/GraphControls.vue'),
      'utf8'
    )

    /** 取某个顶层 function 的函数体（从 `function name (` 到下一个顶层 `function `）。 */
    function functionBody (name) {
      const start = SOURCE.indexOf(`function ${name} (`)
      expect(start, `源码里找不到 function ${name}`).toBeGreaterThan(-1)
      const rest = SOURCE.slice(start + 1)
      const end = rest.indexOf('\nfunction ')
      return end === -1 ? rest : rest.slice(0, end)
    }

    it('签名仍是 (row) —— 不要补成 3 参（补了就等于替上游"修"了漂移）', () => {
      expect(SOURCE).toMatch(/function validateConditionRow \(row\) \{/)
      expect(SOURCE).not.toMatch(/function validateConditionRow \(row,/)
    })

    it('4 处"属性变更"调用点仍各传 3 个实参：(row, group.type, mode)', () => {
      expect(functionBody('handlePropChange')).toContain('validateConditionRow(row, group.type, queryType.value)')
      expect(functionBody('handleSubgraphStartPropChange')).toContain("validateConditionRow(row, group.type, 'entity')")
      expect(functionBody('handleSubgraphEntityPropChange')).toContain("validateConditionRow(row, group.type, 'entity')")
      expect(functionBody('handleSubgraphEdgePropChange')).toContain("validateConditionRow(row, group.type, 'relation')")
    })

    it('值/运算符变更的 2 处仍是 1 参调用（"两种调用形状并存"本身就是要冻住的事实）', () => {
      expect(functionBody('handleValueInput')).toContain('validateConditionRow(row)')
      expect(functionBody('handleOperatorChange')).toContain('validateConditionRow(row)')
    })

    it('解释这条漂移的【签名与调用不一致】注记还在（删注释 = 把"有意保持"还原成"像 bug"）', () => {
      // 源码注记标题以「【签名与调用不一致」开头（提示这是有意保持的签名），这里只钉前缀
      expect(SOURCE).toContain('【签名与调用不一致')
    })
  })
})

// ── 查询请求体：工具条「全部实体类型」快速筛选 ────────────────────────────────
// 工具条上的类型下拉必须同步到 handleExecuteQuery 读取的值，否则选中
// Person/Product 后点查询，请求体里的 entity_type 恒为 []。
describe('查询请求体：工具条实体类型快速筛选参与 filters', () => {
  async function emittedPayload (selectedEntityTypes, groupType = '') {
    const wrapper = await mountControls({
      entityTypes: ['Person', 'Product'],
      selectedEntityTypes
    })
    if (groupType) {
      await chooseSelect(wrapper, '.entity-select', groupType)
    }
    // 抽屉 footer 里的「应用查询」在测试替身里不渲染，直接点工具条上的「查询」——
    // 两个按钮调的是同一个 handleExecuteQuery。
    const apply = wrapper.findAll('button').find(btn => textOf(btn).trim() === '查询')
    expect(apply, '工具条里找不到「查询」按钮').toBeTruthy()
    await apply.trigger('click')
    await flush()
    const emissions = wrapper.emitted('execute-query') || []
    expect(emissions.length, '没有发出 execute-query').toBeGreaterThan(0)
    return emissions[emissions.length - 1][0]
  }

  it('在工具条选中 Product 后查询：filters 明确带上 entity_type=[Product]', async () => {
    // Arrange / Act
    const payload = await emittedPayload(['Product'])

    // Assert
    expect(payload.queryType).toBe('entity')
    expect(payload.filters).toContainEqual({ entity_type: ['Product'], properties: {} })
  })

  it('高级条件里已经有的类型不重复下发（同一类型只出现一次）', async () => {
    // Arrange / Act：高级条件选 Person，工具条回显同为 Person
    const payload = await emittedPayload(['Person'], 'Person')

    // Assert
    const personFilters = payload.filters.filter(filter => (filter.entity_type || []).includes('Person'))
    expect(personFilters).toHaveLength(1)
    expect(payload.filters).toHaveLength(1)
  })

  it('未选择任何类型时不下发多余的实体类型过滤（阳性对照）', async () => {
    // Arrange / Act
    const payload = await emittedPayload([])

    // Assert：只有默认空组，没有任何非空 entity_type
    expect(payload.filters.every(filter => (filter.entity_type || []).length === 0)).toBe(true)
  })
})
