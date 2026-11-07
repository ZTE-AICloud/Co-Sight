// 检索器里存了 3 个知识库（其中同一个 tableName 重复 3 次）时，
// 点标签的 × 只删掉一份、同名标签原地不动，看起来像「没法删」。
// 这里钉住去重规则：加载与保存都过 `uniqueKbNames`，重复值不再进 UI。
import { describe, it, expect } from 'vitest'
import { uniqueKbNames } from '@/features/workflow/lib/kbSelection'

describe('uniqueKbNames（知识库名收敛）', () => {
  it('去掉重复的 tableName，保留首次出现顺序', () => {
    // Arrange：线上 89f4 流程里实际存下的数组（A 重复 3 次）
    const stored = [
      'kb_index_d9d566e3c0dbb2bb',
      'kb_index_d9d566e3c0dbb2bb',
      'kb_index_9501e5ffe2ad1141',
      'kb_index_d9d566e3c0dbb2bb',
      'kb_index_05c284e96b6d4d8ebcc94e5037eae02b'
    ]

    // Act
    const result = uniqueKbNames(stored)

    // Assert
    expect(result).toEqual([
      'kb_index_d9d566e3c0dbb2bb',
      'kb_index_9501e5ffe2ad1141',
      'kb_index_05c284e96b6d4d8ebcc94e5037eae02b'
    ])
  })

  it('字符串按单元素处理，空串算没选', () => {
    expect(uniqueKbNames('kb_index_7')).toEqual(['kb_index_7'])
    expect(uniqueKbNames('')).toEqual([])
  })

  it('非数组返回空数组（调用方按没选处理）', () => {
    expect(uniqueKbNames(undefined)).toEqual([])
    expect(uniqueKbNames(null)).toEqual([])
    expect(uniqueKbNames({ a: 1 })).toEqual([])
  })

  it('丢掉 null / undefined / 空串，但保留数字形态的老 pkId 原样', () => {
    expect(uniqueKbNames(['kb_index_7', null, '', undefined, 'kb_index_7', 42])).toEqual(['kb_index_7', 42])
  })

  it('幂等：再收敛一次结果不变', () => {
    const once = uniqueKbNames(['b', 'a', 'b'])
    expect(uniqueKbNames(once)).toEqual(once)
  })
})
