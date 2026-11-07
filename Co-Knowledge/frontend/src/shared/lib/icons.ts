/**
 * Icon shim.
 *
 * Re-exports the open-source Element Plus icon set, plus local aliases for the
 * custom icons the UI uses that have no direct equivalent (`HelpTip`,
 * `Question`, `EmptyData`, `SquareMinus`, `SquarePlus`).
 */
import { defineComponent, h, type VNode } from 'vue'

export * from '@element-plus/icons-vue'

// HelpTip / Question: the closest open-source equivalent is the filled
// question-mark circle.
export { QuestionFilled as HelpTip, QuestionFilled as Question } from '@element-plus/icons-vue'

function makeIcon (name: string, render: () => VNode[]) {
  return defineComponent({
    name,
    setup () {
      return () => h(
        'svg',
        {
          viewBox: '0 0 1024 1024',
          xmlns: 'http://www.w3.org/2000/svg',
          width: '1em',
          height: '1em',
          'aria-hidden': 'true'
        },
        render()
      )
    }
  })
}

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  'stroke-width': 56,
  'stroke-linecap': 'round' as const,
  'stroke-linejoin': 'round' as const
}

// Empty data placeholder icon: an empty rounded box with a dashed inner line.
export const EmptyData = makeIcon('EmptyData', () => [
  h('rect', { x: 192, y: 320, width: 640, height: 448, rx: 48, ...stroke }),
  h('path', { d: 'M352 544h320', ...stroke, 'stroke-width': 40, 'stroke-dasharray': '10 18' })
])

// Square with a minus (used as a tree expand/collapse icon).
export const SquareMinus = makeIcon('SquareMinus', () => [
  h('rect', { x: 192, y: 192, width: 640, height: 640, rx: 64, ...stroke }),
  h('path', { d: 'M320 512h384', ...stroke })
])

// Square with a plus (used as a tree expand/collapse icon).
export const SquarePlus = makeIcon('SquarePlus', () => [
  h('rect', { x: 192, y: 192, width: 640, height: 640, rx: 64, ...stroke }),
  h('path', { d: 'M320 512h384M512 320v384', ...stroke })
])
