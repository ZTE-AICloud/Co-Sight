import { resolveGraphStats } from '@/features/graph/lib/graph-stats'

// 基本信息页的「实体数量 / 关系数量」必须用后端返回的全量统计（stats），
// 不能再取当前查询结果。这里钉住解析与回落规则。

describe('resolveGraphStats', () => {
  it('读取后端返回的全量实体/关系数', () => {
    expect(resolveGraphStats({ entityCount: 42, edgeCount: 17 })).toEqual({
      entityCount: 42,
      edgeCount: 17
    })
  })

  it('没有 stats 时返回 null，调用方回落到当前查询结果', () => {
    expect(resolveGraphStats(undefined)).toBeNull()
    expect(resolveGraphStats(null)).toBeNull()
    expect(resolveGraphStats({})).toBeNull()
    expect(resolveGraphStats('42')).toBeNull()
  })

  it('只返回一个计数时另一个按 0 处理', () => {
    expect(resolveGraphStats({ entityCount: 9 })).toEqual({
      entityCount: 9,
      edgeCount: 0
    })
    expect(resolveGraphStats({ edgeCount: 4 })).toEqual({
      entityCount: 0,
      edgeCount: 4
    })
  })

  it('非法值归零而不是显示 NaN', () => {
    expect(resolveGraphStats({ entityCount: 'abc', edgeCount: -3 })).toEqual({
      entityCount: 0,
      edgeCount: 0
    })
    expect(resolveGraphStats({ entityCount: '12', edgeCount: 3.9 })).toEqual({
      entityCount: 12,
      edgeCount: 3
    })
  })
})
