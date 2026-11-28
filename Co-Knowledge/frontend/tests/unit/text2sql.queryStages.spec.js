// 查询步骤条的数据契约：阶段帧只更新已知 id，错误文案按 problem 字段回退。
import { describe, expect, it } from 'vitest'

import { QUERY_STAGES, problemText, stageEventState } from '@/features/text2sql/utils/queryStages'

describe('queryStages', () => {
  it('阶段帧按 id 合并且不改原对象', () => {
    const before = { tables: { status: 'running', ms: null } }
    const after = stageEventState(before, { id: 'tables', status: 'success', ms: 18 })

    expect(after.tables).toEqual({ status: 'success', ms: 18 })
    expect(before.tables).toEqual({ status: 'running', ms: null })
    expect(after).not.toBe(before)
  })

  it('忽略未知阶段与非法状态', () => {
    const state = { llm: { status: 'running', ms: null } }
    expect(stageEventState(state, { id: 'unknown', status: 'success', ms: 1 })).toBe(state)
    expect(stageEventState(state, { id: 'llm', status: 'done' })).toBe(state)
  })

  it('缺少耗时时保留 null（界面显示「进行中」而不是 0 ms）', () => {
    const after = stageEventState({}, { id: 'llm', status: 'success' })
    expect(after.llm).toEqual({ status: 'success', ms: null })
  })

  it('阶段清单与后端 STAGE_DEFS 的 id 顺序一致', () => {
    expect(QUERY_STAGES.map(stage => stage.id)).toEqual([
      'tables', 'columns', 'values', 'relations',
      'llm', 'validation', 'explain', 'execute'
    ])
  })

  it('错误文案优先 detail，其次 message/title', () => {
    expect(problemText({ detail: '未发布' }, 'fallback')).toBe('未发布')
    expect(problemText({ message: '网络中断' }, 'fallback')).toBe('网络中断')
    expect(problemText({ title: 'Bad Request' }, 'fallback')).toBe('Bad Request')
    expect(problemText(null, 'fallback')).toBe('fallback')
    expect(problemText(new Error('boom'), 'fallback')).toBe('boom')
  })
})
