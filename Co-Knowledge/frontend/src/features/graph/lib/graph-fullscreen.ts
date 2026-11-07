/**
 * 图谱沉浸画布的 Esc 优先级。
 *
 * 抽屉 / 弹窗先自己处理 Esc；已经打开「查询与操作」浮层时先收浮层；
 * 都没有时才退出全屏。这段判定抽成纯函数，避免组件里再写一份难测的 if 链。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

/** Resolve what an Escape keypress should do while the graph canvas is fullscreen. */
export type FullscreenEscapeAction = 'ignore' | 'close-tools' | 'exit'

export interface FullscreenEscapeState {
  /** 是否处于沉浸画布 */
  fullscreen: boolean
  /** 「查询与操作」浮层是否展开 */
  toolsOpen: boolean
  /** 是否有可见的抽屉 / 弹窗 / 下拉浮层优先消费 Esc */
  overlayOpen: boolean
}

/**
 * @returns 'ignore' 什么都不做（非全屏或叠加层优先）；
 *          'close-tools' 只收起操作浮层；
 *          'exit' 退出沉浸画布。
 */
export function resolveFullscreenEscape (state: FullscreenEscapeState): FullscreenEscapeAction {
  if (!state.fullscreen || state.overlayOpen) {
    return 'ignore'
  }
  return state.toolsOpen ? 'close-tools' : 'exit'
}
