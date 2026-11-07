/**
 * 图谱画布「按当前页面尺寸重排」的几何决策（GraphCanvasVis.vue）。
 *
 * 节点坐标缓存的是与画布无关的基准布局；每次画布尺寸变化（进出全屏）都要重新换算成
 * 当前画布上的坐标。收拢与撑开共用同一套目标尺寸规则：
 * - 包围盒超过可用画布 95% → 收拢到目标尺寸
 * - 撑开模式（进出全屏）：包围盒小于目标尺寸 → 放大到目标，但不反向收拢已经合适的布局
 *
 * 零 Vue / DOM 依赖（分层约定见 docs/ARCHITECTURE.md），可在 Node 里直接单测。
 */

export interface LayoutBounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export interface LayoutCanvas {
  width: number
  height: number
}

export interface LayoutFitOptions {
  /** 节点坐标包围盒 */
  bounds: LayoutBounds
  /** 画布容器的 CSS 像素尺寸 */
  canvas: LayoutCanvas
  /** 参与布局的节点数（目标尺寸按 √n 增长） */
  nodeCount: number
  /** 是否允许把过小的布局撑开（进出全屏时用 true） */
  expand?: boolean
  /** 画布底部为悬浮工具栏预留的高度 */
  bottomSafe?: number
  /** 包围盒超过可用尺寸该比例时必须收拢 */
  overflowRatio?: number
  /** 收拢 / 撑开后的目标尺寸占可用尺寸比例 */
  targetRatio?: number
  /** 小图点簇的横向目标间距（× √n） */
  spacingX?: number
  /** 小图点簇的纵向目标间距（× √n） */
  spacingY?: number
  /** 单个方向最多放大倍数，避免极端窄长的布局被拉变形 */
  maxStretch?: number
}

export interface LayoutFitResult {
  scaleX: number
  scaleY: number
  /** 缩放锚点：包围盒中心 */
  centerX: number
  centerY: number
  /** 是否真的改变了节点坐标（缩放 ≈1 时调用方可以跳过重叠 / 标签微调） */
  changed: boolean
}

/** 布局目标参数的默认值（与 0.1.0 起画布收拢的取值一致）。 */
export const LAYOUT_FIT_DEFAULTS = {
  bottomSafe: 56,
  // 触发线：包围盒超过画布 95% 才收拢；收拢目标 80%（给节点下方文字留余量）。
  // 两个值必须分开：若「只要 >80% 就收到 80%」，缓存坐标每次重载都会再缩一点。
  overflowRatio: 0.95,
  targetRatio: 0.8,
  // 小图保持紧凑点簇：整体尺寸按 √节点数 × 目标间距增长，
  // 而不是一有溢出就把横向铺满画布（13 个点会被拉成横贯全屏的稀疏带）。
  spacingX: 180,
  spacingY: 120,
  maxStretch: 3
} as const

/** 缩放与 1 的差值小于该值时视为「没变化」，避免反复进出全屏被标签避让的抖动累积。 */
const SCALE_EPSILON = 0.02

function isFiniteBounds (bounds: LayoutBounds): boolean {
  return Number.isFinite(bounds.minX) &&
    Number.isFinite(bounds.minY) &&
    Number.isFinite(bounds.maxX) &&
    Number.isFinite(bounds.maxY)
}

/**
 * 计算把节点坐标换算到当前画布所需的缩放与锚点。
 *
 * @returns null 表示不需要重排（普通收拢模式下没有溢出，或输入无效）。
 *          撑开模式只要输入有效就返回结果（即使 scale 是 1，调用方也可能需要重新居中）。
 */
export function resolveLayoutFit (options: LayoutFitOptions): LayoutFitResult | null {
  const { bounds, canvas, nodeCount, expand = false } = options
  if (!isFiniteBounds(bounds) || nodeCount < 2) {
    return null
  }
  if (!(canvas.width > 0) || !(canvas.height > 0)) {
    return null
  }
  const bottomSafe = options.bottomSafe ?? LAYOUT_FIT_DEFAULTS.bottomSafe
  const overflowRatio = options.overflowRatio ?? LAYOUT_FIT_DEFAULTS.overflowRatio
  const targetRatio = options.targetRatio ?? LAYOUT_FIT_DEFAULTS.targetRatio
  const spacingX = options.spacingX ?? LAYOUT_FIT_DEFAULTS.spacingX
  const spacingY = options.spacingY ?? LAYOUT_FIT_DEFAULTS.spacingY
  const maxStretch = options.maxStretch ?? LAYOUT_FIT_DEFAULTS.maxStretch

  const bboxW = bounds.maxX - bounds.minX
  const bboxH = bounds.maxY - bounds.minY
  const usableW = canvas.width
  const usableH = Math.max(1, canvas.height - bottomSafe)
  const overflows = bboxW > usableW * overflowRatio || bboxH > usableH * overflowRatio
  if (!overflows && !expand) {
    return null
  }

  // 横纵分别缩放：目标尺寸随 √n 增长——小图保持紧凑点簇，
  // 节点多时目标自然超过画布，退化为铺满画布。
  const nodeSpan = Math.sqrt(nodeCount)
  const targetW = Math.min(usableW * targetRatio, nodeSpan * spacingX)
  const targetH = Math.min(usableH * targetRatio, nodeSpan * spacingY)
  let scaleX = Math.min(bboxW > 0 ? targetW / bboxW : 1, maxStretch)
  let scaleY = Math.min(bboxH > 0 ? targetH / bboxH : 1, maxStretch)
  if (!Number.isFinite(scaleX) || !Number.isFinite(scaleY)) {
    return null
  }
  // 撑开模式只负责「变大」：没溢出画布时不要因为目标尺寸更小而把布局缩回去，
  // 否则小图进全屏反而更小。溢出时仍按收拢处理。
  if (expand && !overflows) {
    scaleX = Math.max(1, scaleX)
    scaleY = Math.max(1, scaleY)
  }

  return {
    scaleX,
    scaleY,
    centerX: (bounds.minX + bounds.maxX) / 2,
    centerY: (bounds.minY + bounds.maxY) / 2,
    changed: Math.abs(scaleX - 1) > SCALE_EPSILON || Math.abs(scaleY - 1) > SCALE_EPSILON
  }
}
