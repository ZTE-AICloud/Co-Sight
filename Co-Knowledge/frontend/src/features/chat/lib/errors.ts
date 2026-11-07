/**
 * 错误 → 用户可见文案。零 Vue 依赖；两个 composable（工作流列表 / 对话流）共用，
 * 所以单独成文件，不塞进任何一个 composable 里。
 */
import { $t } from '@/app/i18n/i18n.js'

/** RFC 9457 problem（服务端错误体） */
export interface StreamProblem {
  /** RFC 9457 的本地化文案 */
  detail?: unknown
  /** 稳定机器码 */
  code?: unknown
  title?: unknown
  [key: string]: unknown
}

/** `api/stream.js` 返回值（见该文件的 docstring） */
export interface StreamResult {
  /** false = **没进入流式**（服务端在出第一字节前失败，/ 或 nginx 层失败） */
  ok: boolean
  status: number
  contentType?: string
  done?: boolean
  aborted?: boolean
  /** 预流失败：HTTP problem+json */
  errorEnvelope: StreamProblem | null
  /** 流中途失败：SSE `event: error` */
  errorEvent: StreamProblem | null
}

/** 两种失败形状统一收窄成一条用户文案：预流 problem / 流内 error 事件。 */
export function errText (e: unknown, fallback: string): string {
  if (!e) {
    return fallback
  }
  if (typeof e === 'string') {
    return e
  }
  const detail = (e as { detail?: unknown }).detail
  if (typeof detail === 'string' && detail) {
    return detail
  }
  const message = (e as { message?: unknown }).message
  if (typeof message === 'string' && message) {
    return message
  }
  const title = (e as { title?: unknown }).title
  if (typeof title === 'string' && title) {
    return title
  }
  return fallback
}

/**
 * 没进入流式 / 流中途失败时的错误文案：优先用服务端 problem 的 detail，
 * 其次带 HTTP 状态。
 *
 * 带状态码是刚需：nginx 502/504 连 problem 都没有，不把状态码露出来就只剩一句
 * 「请求失败」，没法区分「后端说知识检索没发布」和「网关挂了」。
 *
 * `published_workflow_not_found` 例外：服务端 detail 里带的是**内部 ID**
 * （RAG_Workflow_xxxx），和下拉里显示的名称对不上；这里用当前选中的名称重写，
 * 名称拿不到时也要保证术语是「知识检索」。
 */
export function streamErrorMessage (
  result: StreamResult | null | undefined,
  fallback: string,
  context?: { workflowName?: string }
): string {
  const problem = result && (result.errorEvent || result.errorEnvelope)
  if (problem && problem.code === 'published_workflow_not_found') {
    return context?.workflowName
      ? $t('modules.chatTest.workflowNotPublishedNamed', { name: context.workflowName })
      : $t('modules.chatTest.workflowNotPublished')
  }
  const text = errText(problem, '')
  if (text) {
    return text
  }
  // 括号/破折号占位与语种相关（en 用半角括号并前置空格），整段后缀放 i18n 里
  return `${fallback}${$t('modules.commonUi.chat.httpStatusSuffix', { status: result ? result.status : '—' })}`
}
