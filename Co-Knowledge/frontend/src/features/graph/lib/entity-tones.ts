/**
 * 实体类型 → 设计系统语义色（--rs-tone-*）的分配规则。
 *
 * 每个实体类型按固定语义色板映射（场景 purple / 资源 blue / 指标 green /
 * 规则 orange / 操作 cyan）。类型是用户在模板里定义的，没有 tone 字段，
 * 所以按「模板实体类型顺序」依次轮转这五个语义色；画布、图例、基本信息页的
 * 类型标签都走这一份规则，保证三处颜色永远一致。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

export const ENTITY_TONE_SEQUENCE = ['purple', 'blue', 'green', 'orange', 'cyan'] as const

export type EntityTone = (typeof ENTITY_TONE_SEQUENCE)[number]

/** tone → CSS 变量名（canvas 不解析变量，调用方据此读实际色值） */
export const ENTITY_TONE_TOKENS: Record<EntityTone, string> = {
  purple: '--rs-tone-purple',
  blue: '--rs-tone-blue',
  green: '--rs-tone-green',
  orange: '--rs-tone-orange',
  cyan: '--rs-tone-cyan'
}

/** CSS 变量缺失时的兜底值（浅色主题） */
export const ENTITY_TONE_FALLBACKS: Record<EntityTone, string> = {
  purple: '#8045ff',
  blue: '#1677ff',
  green: '#09aa57',
  orange: '#ff8619',
  cyan: '#35a7b7'
}

function sameType (a: string, b: string): boolean {
  return a === b || a.toLowerCase() === b.toLowerCase()
}

/**
 * 分配实体类型颜色。
 *
 * - `schemaOrder`：模板里的实体类型顺序（权威顺序）
 * - `dataTypes`：当前图谱数据里实际出现的类型
 *
 * 先按模板顺序给「模板与数据都有的类型」上色（大小写不敏感匹配），
 * 再按字典序给数据里多出来的类型补色。色板为 --rs-tone-* 五色。
 */
export function assignEntityTones (
  schemaOrder: string[] = [],
  dataTypes: string[] = []
): Record<string, EntityTone> {
  const ordered = Array.isArray(schemaOrder) ? schemaOrder.filter(Boolean) : []
  const fromData = Array.from(new Set((dataTypes || []).filter(Boolean)))
    .sort((a, b) => String(a).localeCompare(String(b), undefined, { sensitivity: 'base' }))
  const map: Record<string, EntityTone> = {}

  ordered.forEach((schemaType, index) => {
    const matched = fromData.find((type) => sameType(String(type), String(schemaType)))
    if (matched) {
      map[matched] = ENTITY_TONE_SEQUENCE[index % ENTITY_TONE_SEQUENCE.length]
    }
  })

  let colorIndex = ordered.length
  fromData.forEach((type) => {
    if (!(type in map)) {
      map[type] = ENTITY_TONE_SEQUENCE[colorIndex % ENTITY_TONE_SEQUENCE.length]
      colorIndex += 1
    }
  })

  return map
}
