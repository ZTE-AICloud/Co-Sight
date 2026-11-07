// @vitest-environment jsdom
/**
 * 图谱「快速新建」的纯函数单测：
 * - 名称规则必须和整页 `CreateKnowledgeGraph.validateName` 一致；
 * - 草稿只消费一次，返回键不能把上一批文件带回整页。
 */
import {
  isValidGraphQuickName,
  setGraphQuickDraft,
  takeGraphQuickDraft
} from '@/features/graph/lib/graph-quick-create'

describe('图谱快速新建', () => {
  test('名称规则与整页一致：2-30 字、允许中英文/数字/点/横线/空格', () => {
    expect(isValidGraphQuickName('图谱_01-a.b')).toBe(true)
    expect(isValidGraphQuickName('ab')).toBe(true)
    expect(isValidGraphQuickName('a')).toBe(false)
    expect(isValidGraphQuickName('a'.repeat(31))).toBe(false)
    expect(isValidGraphQuickName('a/b')).toBe(false)
    expect(isValidGraphQuickName('   ')).toBe(false)
  })

  test('草稿读取一次后清空，避免返回建图页重复带入文件', () => {
    // Arrange
    const draft = {
      name: 'quick-graph',
      description: 'draft',
      model: 'Qwen3-Embedding-0.6B',
      files: [{ name: 'a.md', size: 10 }]
    }

    // Act
    setGraphQuickDraft(draft)
    const first = takeGraphQuickDraft()
    const second = takeGraphQuickDraft()

    // Assert
    expect(first).toBe(draft)
    expect(second).toBeNull()
  })

  test('可以显式清空草稿', () => {
    // Arrange
    setGraphQuickDraft({ name: 'x', description: '', model: 'm', files: [] })

    // Act
    setGraphQuickDraft(null)

    // Assert
    expect(takeGraphQuickDraft()).toBeNull()
  })
})
