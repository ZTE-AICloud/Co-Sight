/**
 * 图谱概览的全量统计（实体 / 关系）。
 *
 * 详情接口 `GET /knowledge-bases/{id}/graph` 返回 `stats`，
 * 它是图存储里的物理行数，**不受当前查询条件（类型、关键词、limit）影响**。
 * 没有这个字段时返回 null，调用方回落到当前查询结果。
 *
 * 零 Vue 依赖，可在 Node 里直接单测。
 */

export interface GraphStats {
  entityCount: number
  edgeCount: number
}

function toCount (value: unknown): number {
  const count = Number(value)
  if (!Number.isFinite(count) || count <= 0) {
    return 0
  }
  return Math.trunc(count)
}

export function resolveGraphStats (raw: unknown): GraphStats | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const value = raw as Record<string, unknown>
  if (value.entityCount === undefined && value.edgeCount === undefined) {
    return null
  }
  return {
    entityCount: toCount(value.entityCount),
    edgeCount: toCount(value.edgeCount)
  }
}
