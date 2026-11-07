import { describe, expect, it } from 'vitest'

import {
  isBatchPublishTarget,
  PUBLISH_TYPE
} from '@/features/workflow/lib/publishActions'

// 已发布的工作流改完草稿后，列表菜单不能只剩「取消发布」——
// 没有重新发布入口的话，对话测试会永远跑旧快照。这里钉住发布态 → 动作的判定。

describe('工作流发布态 → 批量发布目标', () => {
  it.each([
    ['未发布（0）', PUBLISH_TYPE.UNPUBLISHED, true],
    ['已发布未修改（1）', PUBLISH_TYPE.PUBLISHED, false],
    ['发布后修改（2）', PUBLISH_TYPE.MODIFIED_AFTER_PUBLISH, true],
    ['后端返回字符串 "2"', '2', true],
    ['缺字段（老数据）', undefined, false]
  ])('%s → %s', (_label, publishType, expected) => {
    // Arrange / Act
    const result = isBatchPublishTarget({ publishType })

    // Assert
    expect(result).toBe(expected)
  })

  it('空行不抛错，按「不发布」处理', () => {
    expect(isBatchPublishTarget(null)).toBe(false)
    expect(isBatchPublishTarget({})).toBe(false)
  })
})
