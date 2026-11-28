// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { mountWithPlugins, expectNoI18nMisses } from './helpers/mount'
import TaskDetailDrawer from '@/features/tasks/components/TaskDetailDrawer.vue'

const TASK = {
  id: 't1',
  taskType: 'FILE_IMPORT',
  lane: 'file_import',
  status: 'COMPLETED',
  priority: 0,
  progress: 100,
  attempt: 1,
  maxAttempts: 4,
  kbaseId: 'kb1',
  kbaseName: 'Demo KB',
  fileName: 'report.md',
  payload: {},
  extra: {
    fileName: 'report.md',
    fileSize: 2048,
    chunkCount: 2,
    vectorCount: 3,
    indexDocCount: 3,
    stageTimingsMs: { parse: 12, split: 20, embed: 300 }
  },
  attempts: []
}

describe('TaskDetailDrawer', () => {
  it('产出页签渲染结构化结果摘要并保留原始 JSON', async () => {
    const wrapper = await mountWithPlugins(TaskDetailDrawer, {
      props: { modelValue: true, task: TASK }
    })
    await wrapper.vm.$nextTick()

    const text = wrapper.text()
    expect(text).toContain('结果摘要')
    expect(text).toContain('切片')
    expect(text).toContain('解析 12ms · 切分 20ms · 向量化 300ms')
    expect(text).toContain('原始 JSON')
    expect(text).toContain('"chunkCount": 2')
    expectNoI18nMisses(wrapper)
    wrapper.unmount()
  })
})
