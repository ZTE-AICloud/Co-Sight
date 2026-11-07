import { resolveFullscreenEscape } from '@/features/graph/lib/graph-fullscreen'

// 测的是图谱沉浸画布（0.1.11 原型）的 Esc 优先级：
//   叠加层（抽屉 / 弹窗 / 下拉）> 「查询与操作」浮层 > 退出全屏。
// 纯数据函数，不需要挂载组件；组件只负责把 DOM 上「有没有可见叠加层」喂进来。

describe('resolveFullscreenEscape', () => {
  it('非全屏时忽略 Esc（不影响页面其它快捷键）', () => {
    // Arrange
    const state = { fullscreen: false, toolsOpen: true, overlayOpen: false }

    // Act
    const action = resolveFullscreenEscape(state)

    // Assert
    expect(action).toBe('ignore')
  })

  it('叠加层优先：抽屉 / 弹窗打开时忽略 Esc，交给它们自己关闭', () => {
    // Arrange
    const state = { fullscreen: true, toolsOpen: true, overlayOpen: true }

    // Act / Assert
    expect(resolveFullscreenEscape(state)).toBe('ignore')
  })

  it('浮层展开时只收起浮层，不退出全屏', () => {
    // Arrange
    const state = { fullscreen: true, toolsOpen: true, overlayOpen: false }

    // Act / Assert
    expect(resolveFullscreenEscape(state)).toBe('close-tools')
  })

  it('没有叠加层与浮层时退出全屏', () => {
    // Arrange
    const state = { fullscreen: true, toolsOpen: false, overlayOpen: false }

    // Act / Assert
    expect(resolveFullscreenEscape(state)).toBe('exit')
  })
})
