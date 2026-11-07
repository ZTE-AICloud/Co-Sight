import { LAYOUT_FIT_DEFAULTS, resolveLayoutFit } from '@/features/graph/lib/layout-fit'

// 测的是图谱画布「按当前页面尺寸重排」的几何决策（GraphCanvasVis.compactLayoutToFit）。
// 钉住的行为：普通收拢只在溢出时缩小；进出全屏的撑开模式把过小的布局放大到目标、
// 但不会把已经合适的布局缩回去；单方向最多放大 3 倍；中心点取包围盒中心。
// 纯数据函数，不需要挂载组件。

const baseBounds = { minX: 0, minY: 0, maxX: 100, maxY: 100 }
const baseCanvas = { width: 1000, height: 1000 }

function fit (overrides = {}) {
  return resolveLayoutFit({
    bounds: baseBounds,
    canvas: baseCanvas,
    nodeCount: 4,
    ...overrides
  })
}

describe('resolveLayoutFit', () => {
  it('普通收拢模式下包围盒没有溢出画布时不需要重排', () => {
    // Arrange：100×100 的图放在 1000×1000 的画布上
    // Act
    const result = fit()

    // Assert
    expect(result).toBeNull()
  })

  it('包围盒溢出画布时按目标尺寸收拢，锚点为包围盒中心', () => {
    // Arrange：2000×2000 的图放在 1000×1000 的画布上，4 个节点
    const bounds = { minX: 0, minY: 0, maxX: 2000, maxY: 2000 }

    // Act
    const result = fit({ bounds })

    // Assert：目标宽 2×180=360，目标高 2×120=240
    expect(result).not.toBeNull()
    expect(result.scaleX).toBeCloseTo(0.18)
    expect(result.scaleY).toBeCloseTo(0.12)
    expect(result.centerX).toBeCloseTo(1000)
    expect(result.centerY).toBeCloseTo(1000)
    expect(result.changed).toBe(true)
  })

  it('撑开模式把过小的布局放大到目标尺寸，单方向最多放 3 倍', () => {
    // Act：同一张小图，全屏重排
    const result = fit({ expand: true })

    // Assert：目标宽 360 / 100 = 3.6，被 MAX_LAYOUT_STRETCH 截到 3；目标高 240 / 100 = 2.4
    expect(result).not.toBeNull()
    expect(result.scaleX).toBe(LAYOUT_FIT_DEFAULTS.maxStretch)
    expect(result.scaleY).toBeCloseTo(2.4)
    expect(result.centerX).toBeCloseTo(50)
    expect(result.centerY).toBeCloseTo(50)
    expect(result.changed).toBe(true)
  })

  it('撑开模式不会把已经大于目标的布局缩回去', () => {
    // Arrange：500×500 的图放在 1000×1000 的画布上（未溢出，但大于 360×240 的目标）
    const bounds = { minX: 0, minY: 0, maxX: 500, maxY: 500 }

    // Act
    const result = fit({ bounds, expand: true })

    // Assert：两轴都保持 1 倍，调用方只重新居中
    expect(result).not.toBeNull()
    expect(result.scaleX).toBe(1)
    expect(result.scaleY).toBe(1)
    expect(result.changed).toBe(false)
  })

  it('撑开模式下布局仍然溢出画布时按收拢处理', () => {
    // Arrange：窄而高的图（宽 400、高 2000）放在 1000×1000 画布上，50 个节点
    const bounds = { minX: 0, minY: 0, maxX: 400, maxY: 2000 }

    // Act
    const result = fit({ bounds, nodeCount: 50, expand: true })

    // Assert：横向 800/400=2，纵向 755.2/2000≈0.3776（目标是画布高的 80%，再减去底部预留）
    expect(result).not.toBeNull()
    expect(result.scaleX).toBeCloseTo(2)
    expect(result.scaleY).toBeCloseTo(755.2 / 2000)
    expect(result.changed).toBe(true)
  })

  it('目标尺寸随 √节点数增长，并被画布可用尺寸的上限兜底', () => {
    // Arrange：100 个节点 → √100×180 = 1800，超过画布宽的 80%（800）
    const bounds = { minX: 0, minY: 0, maxX: 2000, maxY: 2000 }

    // Act
    const result = fit({ bounds, nodeCount: 100 })

    // Assert：两轴目标都被画布 80% 兜底（纵向还要减底部预留）
    expect(result.scaleX).toBeCloseTo(800 / 2000)
    expect(result.scaleY).toBeCloseTo(((1000 - LAYOUT_FIT_DEFAULTS.bottomSafe) * 0.8) / 2000)
  })

  it('底部预留高度只影响纵向可用尺寸', () => {
    // Arrange：100 个节点时纵向目标 = 可用高 × 0.8（未触发 √n 上限）
    const bounds = { minX: 0, minY: 0, maxX: 2000, maxY: 2000 }

    // Act
    const withSafe = fit({ bounds, nodeCount: 100 })
    const noSafe = fit({ bounds, nodeCount: 100, bottomSafe: 0 })

    // Assert
    expect(withSafe.scaleY).toBeLessThan(noSafe.scaleY)
    expect(withSafe.scaleX).toBe(noSafe.scaleX)
  })

  it('中心点取包围盒中心（支持负坐标）', () => {
    // Arrange
    const bounds = { minX: -100, minY: 50, maxX: 900, maxY: 450 }

    // Act
    const result = fit({ bounds, expand: true })

    // Assert
    expect(result.centerX).toBeCloseTo(400)
    expect(result.centerY).toBeCloseTo(250)
  })

  it('输入无效或节点不足 2 个时返回 null', () => {
    expect(fit({ bounds: { minX: NaN, minY: 0, maxX: 100, maxY: 100 } })).toBeNull()
    expect(fit({ canvas: { width: 0, height: 100 } })).toBeNull()
    expect(fit({ canvas: { width: 100, height: 0 } })).toBeNull()
    expect(fit({ nodeCount: 1 })).toBeNull()
  })
})
