import {
  createConditionRow,
  createGroup,
  resetGroupConditions,
  isOnlyCondition,
  normalizePropertyOption
} from '@/features/graph/lib/control-forms'

// 测的是 `knowledgeGraphTab/lib/control-forms.ts`（从 GraphControls.vue 抽出的 5 个纯函数）。
// 这些默认值直接决定条件编辑器（查询面板）的第一屏：新组/新行长什么样、重置后还剩什么、
// 属性下拉拿到什么。全部断言钉的是**行为**（默认值、引用关系、守卫分支），不是实现细节。
//
// ⚠️ 下面对「引用」的断言是刻意的：这些对象会被 v-model 就地改（group.type / row.value），
// 一旦哪天把默认值做成模块级共享对象或让 reset 复用旧行，改一行就会串到另一行 —— 这两条就是那个报警器。

/** 条件行的形状（id 每次现生成，只断言类型） */
const conditionRowShape = {
  id: expect.any(String),
  enabled: true,
  prop: '',
  operator: '',
  value: '',
  error: ''
}

describe('createConditionRow', () => {
  it('默认值：enabled=true，prop/operator/value/error 都是空串（模板 v-model 绑的就是这些字段）', () => {
    // Act
    const row = createConditionRow()

    // Assert
    expect(row).toEqual(conditionRowShape)
  })

  it('id 形如 cond-<时间戳>-<随机串>，且 500 次生成互不重复', () => {
    // Arrange
    const seen = new Set()

    // Act
    for (let i = 0; i < 500; i += 1) {
      seen.add(createConditionRow().id)
    }

    // Assert：id 撞车会让 v-for 的 :key 复用错行
    expect(seen.size).toBe(500)
    expect([...seen].every(id => /^cond-\d+-[0-9a-f]+$/.test(id))).toBe(true)
  })

  it('每次调用返回新对象：改一行的字段不波及其它行（不许把默认值做成共享常量）', () => {
    // Arrange
    const first = createConditionRow()
    const second = createConditionRow()

    // Act
    first.prop = 'name'
    first.error = 'boom'

    // Assert
    expect(first).not.toBe(second)
    expect(second.prop).toBe('')
    expect(second.error).toBe('')
  })
})

describe('createGroup', () => {
  it('默认值：type 空、logicOperator=and、恰含 1 条空条件行', () => {
    // Act
    const group = createGroup()

    // Assert
    expect(group).toEqual({
      id: expect.any(String),
      type: '',
      logicOperator: 'and',
      conditions: [conditionRowShape]
    })
  })

  it('id 前缀恒为 entity-（关系组/边组也一样）—— 有意保持，id 只作模板 :key', () => {
    // Act
    const group = createGroup()

    // Assert
    expect(group.id).toMatch(/^entity-\d+-[0-9a-f]+$/)
  })

  it('两个组不共享 conditions 数组与条件行（嵌套对象也是新建的）', () => {
    // Arrange
    const a = createGroup()
    const b = createGroup()

    // Act：改 A 的类型、A 里那一行的值
    a.type = 'Person'
    a.conditions[0].value = 'tom'

    // Assert
    expect(a.conditions).not.toBe(b.conditions)
    expect(a.conditions[0]).not.toBe(b.conditions[0])
    expect(b.type).toBe('')
    expect(b.conditions[0].value).toBe('')
  })
})

describe('resetGroupConditions', () => {
  it('传入 null / undefined 时静默返回、不抛错（调用点可能拿到越界下标取出的组）', () => {
    // Act / Assert
    expect(() => resetGroupConditions(null)).not.toThrow()
    expect(() => resetGroupConditions(undefined)).not.toThrow()
  })

  it('原地重置：logicOperator 回 and、conditions 只剩一条新行；返回 undefined（调用点不接返回值）', () => {
    // Arrange
    const group = createGroup()
    group.logicOperator = 'or'
    group.conditions = [createConditionRow(), createConditionRow(), createConditionRow()]

    // Act
    const ret = resetGroupConditions(group)

    // Assert
    expect(ret).toBeUndefined()
    expect(group.logicOperator).toBe('and')
    expect(group.conditions).toEqual([conditionRowShape])
  })

  it('重置后的行是**新对象**（id 也变），旧行被解绑：改旧行不影响组', () => {
    // Arrange
    const group = createGroup()
    const oldRow = group.conditions[0]

    // Act
    resetGroupConditions(group)
    const newRow = group.conditions[0]
    oldRow.prop = 'OLD'
    oldRow.value = 'stale'

    // Assert
    expect(newRow).not.toBe(oldRow)
    expect(newRow.id).not.toBe(oldRow.id)
    expect(group.conditions[0].prop).toBe('')
    expect(group.conditions[0].value).toBe('')
  })

  it('保留组的 id 与 type（只清条件，不改身份）——切换类型时 v-model 刚写进去的 type 不能被抹掉', () => {
    // Arrange
    const group = createGroup()
    const originalId = group.id
    group.type = 'Movie'

    // Act
    resetGroupConditions(group)

    // Assert
    expect(group.id).toBe(originalId)
    expect(group.type).toBe('Movie')
  })
})

describe('isOnlyCondition', () => {
  it('1 行→true、2 行→false、0 行→true（判据是 <=1，不是 ===1；模板用它禁用删除按钮）', () => {
    // Arrange
    const group = createGroup()

    // Act / Assert：1 行
    expect(isOnlyCondition(group)).toBe(true)

    // Act / Assert：2 行
    group.conditions.push(createConditionRow())
    expect(isOnlyCondition(group)).toBe(false)

    // Act / Assert：0 行（防御性边界，仍按"只剩一行"处理）
    group.conditions = []
    expect(isOnlyCondition(group)).toBe(true)
  })
})

describe('normalizePropertyOption', () => {
  it('字符串输入：label 与 value 都用它，type 为空串', () => {
    // Act
    const option = normalizePropertyOption('name')

    // Assert
    expect(option).toEqual({ label: 'name', value: 'name', type: '' })
  })

  it('null / undefined：返回全空对象，不抛错', () => {
    // Act / Assert
    expect(normalizePropertyOption(null)).toEqual({ label: '', value: '', type: '' })
    expect(normalizePropertyOption(undefined)).toEqual({ label: '', value: '', type: '' })
  })

  it('非对象也非字符串（42 / true）：返回全空对象，不抛错', () => {
    // Act / Assert
    expect(normalizePropertyOption(42)).toEqual({ label: '', value: '', type: '' })
    expect(normalizePropertyOption(true)).toEqual({ label: '', value: '', type: '' })
  })

  it('后端对象（name + type）：value 用属性名，label 缺省回落属性名，type 原样带出', () => {
    // Act
    const option = normalizePropertyOption({ name: 'age', type: 'INTEGER' })

    // Assert
    expect(option).toEqual({ label: 'age', value: 'age', type: 'INTEGER' })
  })

  it('label 与属性名不同时：label 用 label，value 仍用属性名（下拉显示中文、下发给后端的是字段名）', () => {
    // Act
    const option = normalizePropertyOption({ name: 'birth', label: '出生日期', type: 'DATE' })

    // Assert
    expect(option).toEqual({ label: '出生日期', value: 'birth', type: 'DATE' })
  })

  it('只有 label、没有属性名时：value 回落 label', () => {
    // Act
    const option = normalizePropertyOption({ label: '权重' })

    // Assert
    expect(option).toEqual({ label: '权重', value: '权重', type: '' })
  })

  it('缺字段 / 空对象 / 数组等畸形值：统一降级成空 value（下游 .filter(option => option.value) 的判别位）', () => {
    // Act
    const malformed = [{}, [], { unrelated: 1 }].map(normalizePropertyOption)

    // Assert
    expect(malformed).toEqual([
      { label: '', value: '', type: '' },
      { label: '', value: '', type: '' },
      { label: '', value: '', type: '' }
    ])
  })

  it('truthy 非字符串字段**原样带出**、不做 String 强转 —— 有意保持，别"顺手修"', () => {
    // 钉住登记项「normalizePropertyOption 不做 String 强制转换」的另一半：
    // 非字符串输入（42 / true）早在 `typeof prop !== 'object'` 分支降级成空对象，
    // 但**对象里的字段值**是数字/布尔时不受那条保护，会原样进 value / type。
    // 对象里的字段值是数字/布尔时不受 `typeof prop !== 'object'` 保护，会原样带出；
    // type 被 PROPERTY_TYPES 白名单约束成字符串，外部手写 schema 才可能带进来。
    expect(normalizePropertyOption({ name: 42, type: 42 }))
      .toEqual({ label: 42, value: 42, type: 42 })
    expect(normalizePropertyOption({ name: true, type: true }))
      .toEqual({ label: true, value: true, type: true })
  })

  it('falsy 的非字符串字段（0 / 空串）走 `||` 链回落成空串 —— 这类"坏数据"反而被下游滤掉', () => {
    // 钉住同一条 `||` 链的另一半：0 与 '' 是 falsy，逐个回落、最终得 ''，
    // 于是 value 为空 → 下游 .filter(option => option.value) 丢弃整条。
    expect(normalizePropertyOption({ name: 0, type: 0 }))
      .toEqual({ label: '', value: '', type: '' })
    expect(normalizePropertyOption({ name: '', type: '' }))
      .toEqual({ label: '', value: '', type: '' })
  })

  it('过滤语义（模拟下游用法）：一列属性项里只有能产出 value 的才留下 —— 缺字段的整条被丢掉', () => {
    // Arrange：前两条是坏数据，第三条是正常后端对象
    const raw = [null, {}, { name: 'title', type: 'STRING' }]

    // Act
    const kept = raw.map(normalizePropertyOption).filter(option => option.value)

    // Assert
    expect(kept).toHaveLength(1)
    expect(kept[0]).toEqual({ label: 'title', value: 'title', type: 'STRING' })
  })

  it('每次调用产出新对象：改返回值不会污染下一次调用（渲染期反复 map 也不串）', () => {
    // Arrange
    const raw = { name: 'name', type: 'STRING' }

    // Act
    const first = normalizePropertyOption(raw)
    first.value = 'mutated'
    const second = normalizePropertyOption(raw)

    // Assert
    expect(first).not.toBe(second)
    expect(second.value).toBe('name')
  })
})
