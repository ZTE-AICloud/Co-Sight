// @vitest-environment jsdom
// ↑ errors.ts 依赖 `@/app/i18n/i18n.js`（读 localStorage / navigator）
import { vi } from 'vitest'

// 只验证「选中哪个词条 + 参数」，不依赖全局语言
vi.mock('@/app/i18n/i18n.js', () => ({
  $t: (key, params) => (params?.name ? `${key}|${params.name}` : key)
}))

import { streamErrorMessage } from '@/features/chat/lib/errors'

function problemResult (problem) {
  return {
    ok: false,
    status: 404,
    errorEnvelope: problem,
    errorEvent: null
  }
}

describe('streamErrorMessage', () => {
  it('未发布时用选中名称替换服务端返回的内部 ID', () => {
    // Arrange：服务端 detail 里是 RAG_Workflow_c8c6，和下拉名称对不上
    const result = problemResult({
      code: 'published_workflow_not_found',
      detail: '工作流 RAG_Workflow_c8c6 没有已发布的版本，请先在画布上保存并发布。'
    })

    // Act
    const text = streamErrorMessage(result, 'fallback', { workflowName: '图谱知识库的检索--专业的' })

    // Assert
    expect(text).toBe('modules.chatTest.workflowNotPublishedNamed|图谱知识库的检索--专业的')
  })

  it('拿不到名称时回落到通用术语，仍然不暴露内部 ID', () => {
    // Arrange
    const result = problemResult({ code: 'published_workflow_not_found', detail: 'whatever' })

    // Act
    const text = streamErrorMessage(result, 'fallback')

    // Assert
    expect(text).toBe('modules.chatTest.workflowNotPublished')
  })

  it('其他业务错误仍优先展示服务端 detail', () => {
    // Arrange
    const result = problemResult({ code: 'workflow_has_no_operator', detail: '知识检索没有算子' })

    // Act / Assert
    expect(streamErrorMessage(result, 'fallback')).toBe('知识检索没有算子')
  })

  it('没有 problem 时回落到请求失败 + HTTP 状态', () => {
    // Arrange：nginx 502/504 常见形状——没有 problem 正文
    const result = { ok: false, status: 502, errorEnvelope: null, errorEvent: null }

    // Act / Assert
    expect(streamErrorMessage(result, '请求失败'))
      .toBe('请求失败modules.commonUi.chat.httpStatusSuffix')
  })
})
