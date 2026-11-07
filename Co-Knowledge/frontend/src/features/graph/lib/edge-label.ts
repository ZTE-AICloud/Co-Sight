/**
 * 画布上关系标签的取值。
 *
 * 通用抽图算子（-6）产出的 `General_Schema` 只有一个泛化关系类型 `Relation`，
 * 真正的关系语义在边的 `properties.relationship_keywords` 里。直接渲染
 * `edge_type` 的话，画布上每条边都显示 `Relation`。
 *
 * 判据：`edge_type` 缺失或等于通用占位符时退回关键词；模板/专业算子给出的业务
 * 类型（如 `投资`）保持优先，避免把 schema 类型换成同义关键词。
 */

/** 通用算子产出的占位关系类型 */
export const GENERIC_EDGE_TYPE = 'Relation'

/** 画布内联标签上限：超长关键词列表会压到别的边 */
export const EDGE_LABEL_MAX_LENGTH = 24

interface EdgeLike {
  edge_type?: unknown
  class?: unknown
  properties?: Record<string, unknown> | null
}

/**
 * 完整关系标签：业务类型或**全部**关键词（`、` 连接）。
 *
 * @param edge 后端返回的边（`edge_type` 或 `class` + `properties`）
 * @param maxLength 截断上限；传 `Infinity` 表示不截断（悬浮气泡用）
 */
export function edgeLabelText (edge?: EdgeLike | null, maxLength: number = EDGE_LABEL_MAX_LENGTH): string {
  const type = edgeTypeOf(edge)
  if (type && !isGenericType(type)) {
    return type
  }
  const keywords = keywordParts(edge?.properties?.relationship_keywords)
  return keywords.length ? clip(keywords.join('、'), maxLength) : type
}

/**
 * 画布常显标签：业务类型或**第一个**关键词。
 *
 * 长节点名（如 18 字的公司全称）会把连线中点的位置占掉，多关键词标签必然压字；
 * 常显只取第一个关键词，完整关键词留给悬浮气泡与详情列表。
 */
export function edgeInlineLabel (edge?: EdgeLike | null): string {
  const type = edgeTypeOf(edge)
  if (type && !isGenericType(type)) {
    return type
  }
  const keywords = keywordParts(edge?.properties?.relationship_keywords)
  return keywords.length ? clip(keywords[0], EDGE_LABEL_MAX_LENGTH) : type
}

function edgeTypeOf (edge?: EdgeLike | null): string {
  return String(edge?.edge_type ?? edge?.class ?? '').trim()
}

function isGenericType (type: string): boolean {
  return type.toLowerCase() === GENERIC_EDGE_TYPE.toLowerCase()
}

/** 关键词既可能是数组，也可能是逗号分隔的字符串 */
function keywordParts (value: unknown): string[] {
  let parts: string[] = []
  if (Array.isArray(value)) {
    parts = value.map(item => String(item))
  } else if (typeof value === 'string') {
    parts = value.split(/[,，、;；]/)
  }
  return parts.map(part => part.trim()).filter(Boolean)
}

function clip (text: string, maxLength: number): string {
  if (text.length <= maxLength) {
    return text
  }
  return `${text.slice(0, maxLength - 1)}…`
}
