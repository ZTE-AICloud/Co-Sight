/**
 * 查询流水线的阶段骨架：id 与后端 `STAGE_DEFS` 一一对应。
 *
 * 运行中先用它渲染未点亮的步骤，SSE 的 `stage` 帧按 id 更新状态与耗时；
 * 完成后「运行详情 → 流水线耗时」展示的仍是同一份 `stages` 数据（后端权威）。
 */
export const QUERY_STAGES = [
  { id: 'tables', name: '表检索' },
  { id: 'columns', name: '字段检索' },
  { id: 'values', name: '值匹配' },
  { id: 'relations', name: '关系补全' },
  { id: 'llm', name: 'SQL 生成' },
  { id: 'validation', name: '安全校验' },
  { id: 'explain', name: '执行计划' },
  { id: 'execute', name: '只读查询' }
]

const STAGE_STATUSES = ['running', 'success', 'skipped']

/**
 * SSE `stage` 帧 → 新的进度表（不可变合并）。
 *
 * 未知 id / 状态的帧直接丢弃：阶段清单以本文件为准，不因服务端多推一帧就
 * 在界面上多出一个步骤。
 */
export function stageEventState (state, event) {
  const id = String(event?.id || '')
  if (!QUERY_STAGES.some(stage => stage.id === id)) {
    return state
  }
  if (!STAGE_STATUSES.includes(event?.status)) {
    return state
  }
  return {
    ...state,
    [id]: {
      status: event.status,
      ms: Number.isFinite(event.ms) ? event.ms : null
    }
  }
}

/** problem+json / 网络错误 → 一条可读文案（优先服务端本地化的 detail）。 */
export function problemText (problem, fallback) {
  if (!problem) {
    return fallback
  }
  if (typeof problem === 'string') {
    return problem
  }
  if (typeof problem.detail === 'string' && problem.detail) {
    return problem.detail
  }
  if (typeof problem.message === 'string' && problem.message) {
    return problem.message
  }
  if (typeof problem.title === 'string' && problem.title) {
    return problem.title
  }
  return fallback
}
