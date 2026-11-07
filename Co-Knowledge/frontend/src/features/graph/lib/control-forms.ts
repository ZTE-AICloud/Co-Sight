/**
 * GraphControls 条件编辑器的纯数据层：条件行 / 条件组的工厂与重置，以及属性项归一化。
 *
 * 零 Vue 依赖：不读 props / 组件状态 / i18n，可在 Node 里直接单测。同理，带 `t()` 文案、
 * 读 `props.xxxTypeProperties` 或直接写响应式变量的函数（`getOperatorOptions`、
 * `getValuePlaceholder`、`validateConditionRow`、`resetAllConditions` 等）**不在这里** ——
 * 它们不是纯函数。
 */

/** 条件行：模板里 `v-for="(row, rowIndex) in group.conditions"` 的一行属性过滤。 */
export interface ConditionRow {
  /** 行 id，仅作模板 :key（`createConditionRow` 里现生成） */
  id: string
  /** 该行是否参与最终下发的 filter */
  enabled: boolean
  /** 属性名（取值是 `normalizePropertyOption` 产出的 value） */
  prop: string
  /** 运算符（取值来自 getOperatorOptions，如 eq / in / between） */
  operator: string
  /** 输入框里的原始文本（矩阵形态的值如 `[1,2]` 也先存成字符串） */
  value: string
  /** 校验错误文案，空串 = 无错；由组件里的 validateConditionRow 就地写入 */
  error: string
}

/** 条件组：一个实体/关系类型 + 它下面的一组条件行。 */
export interface ConditionGroup {
  id: string
  type: string
  /** 组内条件行之间的逻辑连接符：'and' | 'or' */
  logicOperator: string
  conditions: ConditionRow[]
}

/** `normalizePropertyOption` 的归一化结果，直接喂给 `el-option`。 */
export interface NormalizedPropertyOption {
  /** 展示文案（缺 label 时回落属性名） */
  label: string
  /** 选中值（属性名；全缺时为空串，下游靠它过滤掉坏数据） */
  value: string
  /** 属性类型（如 STRING / INTEGER），供 getPropertyType 消费 */
  type: string
}

/**
 * 属性项的原始形状：字符串、后端对象（`property_name` / `property_type`），
 * 或任意畸形值（null、数字、数组……）。
 *
 * 索引签名用 `unknown` 而不是 `any`：归一化只认上面列出的字段，其余字段读都不读，
 * 但也不拒绝（后端 DTO 多带字段是常态）。
 */
export type PropertyOptionInput =
  | string
  | null
  | undefined
  | {
      property_name?: string
      name?: string
      code?: string
      prop?: string
      label?: string
      property_type?: string
      type?: string
      [key: string]: unknown
    }

/**
 * 属性项归一化：把「字符串 / 后端对象 / 畸形值」统一成 `{ label, value, type }`。
 *
 * 契约（组件里的 `getPropertyOptions` 依赖）：
 * - value 为空串的行会被 `.filter(option => option.value)` 丢掉 —— 缺字段/畸形输入
 *   在这里降级成空 value，而不是抛错；
 * - ⚠️ 不做 String 强制转换：字段是 truthy 的非字符串（如数字 42）会原样进 value/type；
 *   falsy 的 0 / '' 反而会走 `||` 链回落成 ''（"坏数据"里只有 truthy 的坏值会漏过去）。
 *
 * schema 的键是 `name` / `type` / `label`。所有 schema 写入路径都把 `type` 约束成
 * 字符串（`graph_schema_service.PROPERTY_TYPES` 白名单 + `validate_property_type`）；
 * 只有外部算子产出/手写 schema.json 才可能把非字符串带进来。
 * 本函数**不做防御**；边界由 tests/unit/graphControls.control-forms.spec.js 钉住。
 */
export function normalizePropertyOption (prop: PropertyOptionInput): NormalizedPropertyOption {
  if (typeof prop === 'string') {
    return { label: prop, value: prop, type: '' }
  }
  if (!prop || typeof prop !== 'object') {
    return { label: '', value: '', type: '' }
  }
  const name = prop.name || ''
  const label = prop.label || name || ''
  const type = prop.type || ''
  return { label, value: name || label, type }
}

/**
 * 组内是否只剩一行条件（`<= 1`，0 行也算）。模板用它禁用「删除条件行」按钮
 * （GraphControls.vue 模板 170 / 174 行）。
 */
export function isOnlyCondition (group: ConditionGroup): boolean {
  return group.conditions.length <= 1
}

/** 新条件行：默认空属性/空运算符、启用、无错误，id 现生成（不共享引用）。 */
export function createConditionRow (): ConditionRow {
  return {
    id: `cond-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    enabled: true,
    prop: '',
    operator: '',
    value: '',
    error: '' // 新增：用于存储错误信息
  }
}

/**
 * 新条件组：默认空类型、'and'、含 1 行空条件。
 *
 * 注：id 前缀恒为 `entity-`（关系/边组也是），只作模板 :key，无功能影响。
 */
export function createGroup (): ConditionGroup {
  return {
    id: `entity-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    type: '',
    logicOperator: 'and',
    conditions: [createConditionRow()]
  }
}

/**
 * 重置一个已存在的条件组：逻辑符回 'and'，条件行**整体换新**（旧行对象被解绑，
 * 不会与新行共享引用）。
 *
 * ⚠️ 原地改传入对象、返回 undefined —— 组件的四个调用点都靠这个语义生效，
 * 不要改成「返回新对象」。
 * 传入 null / undefined（例如按越界下标取到的组）时静默返回，不抛错。
 */
export function resetGroupConditions (group: ConditionGroup | null | undefined): void {
  if (!group) {
    return
  }
  group.logicOperator = 'and'
  group.conditions = [createConditionRow()]
}
