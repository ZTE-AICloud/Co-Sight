/**
 * 图谱画布节点标签的纯格式化逻辑（GraphCanvasVis.vue）。
 *
 * 背景：实体名多为 19~26 字符的 snake_case（如 `ent_battery_backup_001`），
 * 统一截断到 12 字符 + `...` 会让一屏里大部分标签都看不全。
 * 这里在靠近中点的下划线处断成两行，每行 ≤ 16 字符，宽度基本不变、
 * 但最长可完整显示 32 字符。
 *
 * 零 Vue 依赖：不读 props / 组件状态 / i18n，可在 Node 里直接单测。
 */

/** 每行最多字符数 */
export const NODE_LABEL_LINE_MAX = 16

/** 两行合计上限；超过后截断并以 `...` 结尾 */
export const NODE_LABEL_MAX_LEN = NODE_LABEL_LINE_MAX * 2

/**
 * 把实体名格式化成画布标签：短名原样返回，长名在两行内展示。
 * 超过 32 字符时截断到 29 字符 + `...`（仍保持两行）。
 */
export function formatNodeLabel (text?: string | null): string {
  if (!text) {
    return ''
  }
  const s = String(text).trim()
  if (s.length <= NODE_LABEL_LINE_MAX) {
    return s
  }
  const clipped = s.length > NODE_LABEL_MAX_LEN
    ? s.slice(0, NODE_LABEL_MAX_LEN - 3) + '...'
    : s
  return splitLabelLines(clipped)
}

/**
 * 在靠近中点的下划线之后断行，使两行都不超过 NODE_LABEL_LINE_MAX；
 * 没有合适的下划线时在第 NODE_LABEL_LINE_MAX 个字符处硬断。
 */
/**
 * 关系（边）标签与节点标签共用同一套两行规则。
 * 边标签截到 8 字符（`MapsEntity` → `MapsEnti...`）稍微长一点就看不全。
 */
export const formatEdgeLabel = formatNodeLabel

export function splitLabelLines (text: string): string {
  const mid = text.length / 2
  let breakAt = -1
  for (let i = 0; i < text.length - 1; i++) {
    if (text[i] !== '_') {
      continue
    }
    const firstLen = i + 1
    const secondLen = text.length - firstLen
    if (firstLen > NODE_LABEL_LINE_MAX || secondLen > NODE_LABEL_LINE_MAX) {
      continue
    }
    if (breakAt === -1 || Math.abs(firstLen - mid) < Math.abs(breakAt - mid)) {
      breakAt = firstLen
    }
  }
  if (breakAt === -1) {
    breakAt = NODE_LABEL_LINE_MAX
  }
  return `${text.slice(0, breakAt)}\n${text.slice(breakAt)}`
}
