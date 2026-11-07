/**
 * 图谱画布标签避让的纯几何逻辑（GraphCanvasVis.vue）。
 *
 * 节点名是固定 13px 的 canvas 文本，画在节点中心下方 44px；位置收拢后长名字会互相压住，
 * 也会压到邻近节点圆上。画布横向余量充足，这里只沿 x 轴对推。
 *
 * 零 Vue / DOM 依赖：文本宽度由调用方用 canvas.measureText 注入，可在 Node 里直接单测。
 */

export interface LabelLayoutPoint {
  id: string
  x: number
  y: number
}

/* eslint-disable no-unused-vars -- 函数类型签名里的参数名只用于说明，不参与运行时 */
export interface LabelLayoutOptions {
  /** 节点 id → 显示名；空串表示不画标签，不参与避让 */
  labelOf: (id: string) => string
  /** 13px 标签字体下的文本宽度 */
  measureWidth: (label: string) => number
  /** 标签中心相对节点中心的纵向偏移（正数在下方） */
  labelOffsetY: number
  /** 节点光环半径 */
  haloRadius: number
  /** 标签文本包围盒的上下余量 */
  ascent?: number
  descent?: number
  /** 两个标签之间的最小水平间隙 */
  padding?: number
  /** 最多挤开的轮数 */
  passes?: number
  /** 超过该节点数直接跳过（大图标签本就密集，收益低且 O(n²)） */
  maxNodes?: number
  /** 分隔后的最大宽度；超出时返回 null，避免把节点推到画布外 */
  maxWidth?: number
}
/* eslint-enable no-unused-vars */

export interface LabelSeparationResult {
  /** 发生位移的节点（绝对坐标，y 不变） */
  updates: LabelLayoutPoint[]
}

interface LabelBox extends LabelLayoutPoint {
  left: number
  right: number
  top: number
  bottom: number
  circleLeft: number
  circleRight: number
  circleTop: number
  circleBottom: number
}

const DEFAULT_ASCENT = 10
const DEFAULT_DESCENT = 4
const DEFAULT_PADDING = 6
const DEFAULT_PASSES = 4
const DEFAULT_MAX_NODES = 60

function buildLabelBox (
  point: LabelLayoutPoint,
  options: Required<Pick<LabelLayoutOptions, 'labelOf' | 'measureWidth' | 'labelOffsetY' | 'haloRadius'>> & {
    ascent: number
    descent: number
  }
): LabelBox | null {
  const label = options.labelOf(point.id)
  if (!label || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
    return null
  }
  const half = options.measureWidth(label) / 2
  return {
    id: point.id,
    x: point.x,
    y: point.y,
    left: point.x - half,
    right: point.x + half,
    top: point.y + options.labelOffsetY - options.ascent,
    bottom: point.y + options.labelOffsetY + options.descent,
    circleLeft: point.x - options.haloRadius,
    circleRight: point.x + options.haloRadius,
    circleTop: point.y - options.haloRadius,
    circleBottom: point.y + options.haloRadius
  }
}

/** 节点圆与另一节点标签的水平缺口，>0 表示需要推开该距离 */
function circleLabelGap (circle: LabelBox, label: LabelBox, padding: number): number {
  if (circle.circleBottom <= label.top || label.bottom <= circle.circleTop) {
    return 0
  }
  if (label.x >= circle.x) {
    return circle.circleRight + padding - label.left
  }
  return label.right - (circle.circleLeft - padding)
}

/** 两个节点圆（半径 haloRadius）的水平缺口，>0 表示需要推开该距离 */
function circleCircleGap (a: LabelBox, b: LabelBox, haloRadius: number): number {
  const dy = Math.abs(a.y - b.y)
  const minDistance = haloRadius * 2
  if (dy >= minDistance) {
    return 0
  }
  const requiredX = Math.sqrt(minDistance * minDistance - dy * dy)
  return requiredX - Math.abs(b.x - a.x)
}

/**
 * 按真实标签宽度消除「标签压标签」「节点圆压标签」，只沿 x 轴对推。
 * 节点中心距的兜底（resolveOverlapsForAllNodes）由调用方在应用结果后再跑一次。
 */
export function separateOverlappingLabels (
  points: readonly LabelLayoutPoint[],
  options: LabelLayoutOptions
): LabelSeparationResult | null {
  const maxNodes = options.maxNodes ?? DEFAULT_MAX_NODES
  if (points.length < 2 || points.length > maxNodes) {
    return null
  }
  const boxOptions = {
    labelOf: options.labelOf,
    measureWidth: options.measureWidth,
    labelOffsetY: options.labelOffsetY,
    haloRadius: options.haloRadius,
    ascent: options.ascent ?? DEFAULT_ASCENT,
    descent: options.descent ?? DEFAULT_DESCENT
  }
  const padding = options.padding ?? DEFAULT_PADDING
  const passes = options.passes ?? DEFAULT_PASSES
  const items = points
    .map(point => buildLabelBox(point, boxOptions))
    .filter((item): item is LabelBox => item !== null)
  if (items.length < 2) {
    return null
  }
  const moved = new Map<string, LabelLayoutPoint>()
  const shift = (item: LabelBox, dx: number): void => {
    item.x += dx
    item.left += dx
    item.right += dx
    item.circleLeft += dx
    item.circleRight += dx
    moved.set(item.id, { id: item.id, x: item.x, y: item.y })
  }
  const pushApart = (a: LabelBox, b: LabelBox, distance: number): void => {
    const half = distance / 2
    shift(a, a.x <= b.x ? -half : half)
    shift(b, a.x <= b.x ? half : -half)
  }
  for (let pass = 0; pass < passes; pass++) {
    let changed = false
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i]
        const b = items[j]
        let need = 0
        if (a.bottom > b.top && b.bottom > a.top) {
          const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left)
          if (overlapX > -padding) {
            need = overlapX + padding
          }
        }
        need = Math.max(
          need,
          circleLabelGap(a, b, padding),
          circleLabelGap(b, a, padding),
          circleCircleGap(a, b, options.haloRadius)
        )
        if (need <= 0) {
          continue
        }
        pushApart(a, b, need)
        changed = true
      }
    }
    if (!changed) {
      break
    }
  }
  if (!moved.size) {
    return null
  }
  // 标签/光环是图形最宽的部分；超过画布宽度时整体放弃，宁可保留少量压字也不裁节点
  if (options.maxWidth !== undefined) {
    const left = Math.min(...items.map(item => Math.min(item.left, item.circleLeft)))
    const right = Math.max(...items.map(item => Math.max(item.right, item.circleRight)))
    if (right - left > options.maxWidth) {
      return null
    }
  }
  return { updates: Array.from(moved.values()) }
}
