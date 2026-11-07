import { separateOverlappingLabels } from '@/features/graph/lib/label-layout'

// 测的是 `src/features/graph/lib/label-layout.ts`（GraphCanvasVis.vue 收起布局后的标签避让）。
// 钉住的行为：标签/节点圆互压时只沿 x 轴对推、留出 padding；空标签、单点、大图、
// 超过画布宽度时不做任何改动；输入坐标不被修改。
// 文本宽度用 `字符数 × 10` 注入，避免依赖真实字体。

const labels = {
  a: 'AAAA',
  b: 'BBBB',
  c: 'CCCC'
}

function baseOptions (overrides = {}) {
  return {
    labelOf: (id) => labels[id] ?? '',
    measureWidth: (label) => label.length * 10,
    labelOffsetY: 44,
    haloRadius: 5,
    ...overrides
  }
}

function byId (updates) {
  return Object.fromEntries(updates.map((item) => [item.id, item]))
}

describe('separateOverlappingLabels', () => {
  it('少于两个节点时返回 null', () => {
    expect(separateOverlappingLabels([], baseOptions())).toBeNull()
    expect(separateOverlappingLabels([{ id: 'a', x: 0, y: 0 }], baseOptions())).toBeNull()
  })

  it('标签互不重叠时返回 null', () => {
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 100, y: 0 }
    ]

    expect(separateOverlappingLabels(points, baseOptions())).toBeNull()
  })

  it('同排两个标签重叠时沿 x 轴对推，最终间隙等于 padding', () => {
    // Arrange：两个 40px 宽的标签中心相距 20px，水平重叠 20px
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 20, y: 0 }
    ]

    // Act
    const result = separateOverlappingLabels(points, baseOptions())

    // Assert：共需推开 20+6，各让一半
    expect(result).not.toBeNull()
    const moved = byId(result.updates)
    expect(moved.a.x).toBeCloseTo(-13)
    expect(moved.b.x).toBeCloseTo(33)
    expect(moved.a.y).toBe(0)
    expect(moved.b.y).toBe(0)
    // a 的标签右边 (7) 与 b 的标签左边 (13) 之间正好 6px
    expect(moved.b.x - 20 - (moved.a.x + 20)).toBeCloseTo(6)
  })

  it('间隙小于 padding 时也补齐到 padding', () => {
    // Arrange：标签左边距 8px，实际间隙只有 8px
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 28, y: 0 }
    ]

    // Act
    const result = separateOverlappingLabels(points, baseOptions())

    // Assert
    const moved = byId(result.updates)
    expect(moved.b.x - 20 - (moved.a.x + 20)).toBeCloseTo(6)
  })

  it('节点圆压到另一节点的标签时推开', () => {
    // Arrange：a 的圆（半径 31）压住 b 的标签左端
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 40, y: -20 }
    ]
    const options = baseOptions({
      haloRadius: 31,
      labelOf: (id) => (id === 'a' ? 'AA' : 'BBBBBBBB')
    })

    // Act
    const result = separateOverlappingLabels(points, options)

    // Assert
    const moved = byId(result.updates)
    expect(moved.a.x).toBeCloseTo(-18.5)
    expect(moved.b.x).toBeCloseTo(58.5)
    expect(moved.b.y).toBe(-20)
  })

  it('标签不重叠但两个节点圆重叠时，按圆的最小间距推开', () => {
    // Arrange：两个短标签（10px）相距 20px，标签无重叠，但半径 31 的圆重叠
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 20, y: 0 }
    ]
    const options = baseOptions({
      haloRadius: 31,
      labelOf: (id) => id.toUpperCase(),
      measureWidth: () => 10
    })

    // Act
    const result = separateOverlappingLabels(points, options)

    // Assert：中心距被推到直径 62
    const moved = byId(result.updates)
    expect(moved.b.x - moved.a.x).toBeCloseTo(62)
  })

  it('没有标签的节点不参与避让，也不出现在 updates 里', () => {
    // Arrange：a 无标签，b/c 同排重叠
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 0, y: 50 },
      { id: 'c', x: 20, y: 50 }
    ]

    // Act
    const result = separateOverlappingLabels(points, baseOptions({
      labelOf: (id) => (id === 'a' ? '' : labels[id])
    }))

    // Assert
    const moved = byId(result.updates)
    expect(moved.a).toBeUndefined()
    expect(moved.b.x).toBeCloseTo(-13)
    expect(moved.c.x).toBeCloseTo(33)
  })

  it('节点数超过 maxNodes 时整体跳过', () => {
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 20, y: 0 },
      { id: 'c', x: 40, y: 0 }
    ]

    expect(separateOverlappingLabels(points, baseOptions({ maxNodes: 2 }))).toBeNull()
  })

  it('避让后超过 maxWidth 时整体放弃', () => {
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 20, y: 0 }
    ]

    expect(separateOverlappingLabels(points, baseOptions({ maxWidth: 40 }))).toBeNull()
  })

  it('忽略坐标非法的节点', () => {
    const points = [
      { id: 'a', x: Number.NaN, y: 0 },
      { id: 'b', x: 0, y: 0 },
      { id: 'c', x: 20, y: 0 }
    ]

    const result = separateOverlappingLabels(points, baseOptions())

    expect(result).not.toBeNull()
    expect(result.updates.map((item) => item.id).sort()).toEqual(['b', 'c'])
  })

  it('不修改传入的坐标数组', () => {
    const points = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 20, y: 0 }
    ]

    separateOverlappingLabels(points, baseOptions())

    expect(points).toEqual([
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 20, y: 0 }
    ])
  })
})
