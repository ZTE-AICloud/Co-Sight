/**
 * 线性图标集。
 *
 * 统一规格：24×24 viewBox、无填充、1.8 描边、圆角端点。颜色全部走 currentColor，
 * 由外层 `.ux-tinted-icon` / `.ux-title-icon` 的 tone 变量决定。
 *
 * Element Plus 图标是填充式的，套上 stroke 观感不对；这里用最小实现补齐
 * 「文档之外」的那几个图形（分层 / 星芒 / 切分 / 地球 / 活动 / 立方 / 工作流）。
 * 文档、分享、搜索、聊天、钥匙等直接使用 @element-plus/icons-vue。
 */
import { defineComponent, h, type VNode } from 'vue'

function lineIcon (name: string, paths: string[]) {
  return defineComponent({
    name,
    setup: (): (() => VNode) => () => h(
      'svg',
      {
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        // 用内联 style 而不是 stroke-width 属性。
        // 属性会被外层 CSS（如 `.nav-item svg { stroke-width:.3 }`）覆盖，
        // 0.3px 的稿线在 20px 尺寸下看起来就是灰色。
        style: { strokeWidth: 1.8 },
        'stroke-linecap': 'round',
        'stroke-linejoin': 'round',
        'aria-hidden': 'true'
      },
      paths.map(d => h('path', { d }))
    )
  })
}

export const CubeIcon = lineIcon('CubeIcon', ['M12 2 3 7v10l9 5 9-5V7L12 2Z', 'm3 7 9 5 9-5', 'M12 12v10'])
export const WorkflowIcon = lineIcon('WorkflowIcon', [
  'M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z',
  'M17 22a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z',
  'm11 10 4 4',
  'M9 5v2',
  'M8 6h2',
  'M17 17v2',
  'M16 18h2'
])
export const PuzzleIcon = lineIcon('PuzzleIcon', [
  'M9 3H5a2 2 0 0 0-2 2v4h2a2 2 0 0 1 0 4H3v6a2 2 0 0 0 2 2h5v-2a2 2 0 0 1 4 0v2h5a2 2 0 0 0 2-2v-5h-2a2 2 0 0 1 0-4h2V5a2 2 0 0 0-2-2h-5V2a2.5 2.5 0 0 0-5 0v1Z'
])
export const LayersIcon = lineIcon('LayersIcon', ['m12 3 10 5-10 5L2 8l10-5Z', 'm2 12 10 5 10-5', 'm2 16 10 5 10-5'])
export const SparkleIcon = lineIcon('SparkleIcon', [
  'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z',
  'M20 2v4',
  'M18 4h4'
])
export const SplitIcon = lineIcon('SplitIcon', [
  'M6 5h12M6 19h12',
  'M4 8H3v8h1M20 8h1v8h-1',
  'M8 9h8M8 15h8',
  'M7 3h10a2 2 0 0 1 2 2v3H5V5a2 2 0 0 1 2-2ZM5 16h14v3a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-3Z'
])
export const GlobeIcon = lineIcon('GlobeIcon', [
  'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  'M3 12h18',
  'M12 3c-5 5-5 13 0 18 5-5 5-13 0-18Z'
])
export const ActivityIcon = lineIcon('ActivityIcon', ['M2 12h5l3-9 4 18 3-9h5'])
