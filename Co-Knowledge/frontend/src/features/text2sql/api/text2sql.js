import axios from '@/shared/api/client'
import { KBASE_BASE } from '@/shared/api/endpoints'
import { streamPost } from '@/shared/api/stream'

const TEXT2SQL_BASE = `${KBASE_BASE}/text2sql`

export function listDatasources () {
  return axios.get(`${TEXT2SQL_BASE}/datasources`)
}

export function getDatasource (datasourceId) {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}`)
}

export function createDatasource (payload) {
  return axios.post(`${TEXT2SQL_BASE}/datasources`, payload)
}

export function updateDatasource (datasourceId, payload) {
  return axios.patch(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}`, payload)
}

export function deleteDatasource (datasourceId) {
  return axios.delete(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}`)
}

export function testConnectionPayload (payload) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/connection-test`, payload)
}

export function testConnection (datasourceId) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/connection-test`)
}

export function scanDatasource (datasourceId) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/scan`)
}

// AI 辅助：只生成建议，不落库；采纳时仍走 updateTable / updateColumn / updateValue。
export function requestAssist (datasourceId, payload) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/assist`, payload)
}

// 流式版：stage 帧上报进度（目录/样本/生成批次），result 帧是完整建议体。
export function assistStream (datasourceId, payload, handlers) {
  return streamPost(
    `${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/assist/stream`,
    payload,
    handlers)
}

export function listTables (datasourceId) {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/tables`)
}

export function updateTable (datasourceId, tableId, payload) {
  return axios.patch(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/tables/${encodeURIComponent(tableId)}`, payload)
}

export function updateColumn (datasourceId, columnId, payload) {
  return axios.patch(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/columns/${encodeURIComponent(columnId)}`, payload)
}

export function listRelations (datasourceId) {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/relations`)
}

export function listValues (datasourceId, columnId = '') {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/values`, {
    params: columnId ? { columnId } : {}
  })
}

export function listMetrics (datasourceId) {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/metrics`)
}

export function listVersions (datasourceId) {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/versions`)
}

export function createVersion (datasourceId, payload = {}) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/versions`, payload)
}

export function getVersion (datasourceId, versionId) {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/versions/${encodeURIComponent(versionId)}`)
}

export function buildVersion (datasourceId, versionId) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/versions/${encodeURIComponent(versionId)}/build`)
}

// 回收旧版本：保留最近 keep 个 READY，其余归档并清掉知识（后端保证不动
// 活动版本、被查询历史/收藏/反馈引用的版本）。
export function cleanupVersions (datasourceId, keep = 3) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/versions/cleanup`, { keep })
}

export function publishVersion (datasourceId, versionId, expectedRevision) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/publication`, {
    versionId,
    expectedRevision
  })
}

export function listPublications (datasourceId) {
  return axios.get(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/publications`)
}

export function runQuery (datasourceId, payload) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/query`, payload)
}

/**
 * 查询的流式版本：`stage` 帧上报阶段，`result` 帧携带与同步接口同形的响应体。
 *
 * 不走 axios 的原因见 `shared/api/stream`（XHR 拿不到增量）。失败有两种形状：
 * 进流前是真实 HTTP 状态 + problem+json（`result.ok === false`），进流后是终态
 * `event: error`（`result.errorEvent`）。
 */
export function runQueryStream (datasourceId, payload, handlers) {
  return streamPost(
    `${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/query/stream`,
    payload,
    handlers)
}

export function listRuns (params = {}) {
  return axios.get(`${TEXT2SQL_BASE}/runs`, { params })
}

export function getRun (runId) {
  return axios.get(`${TEXT2SQL_BASE}/runs/${encodeURIComponent(runId)}`)
}

export function deleteRun (runId) {
  return axios.delete(`${TEXT2SQL_BASE}/runs/${encodeURIComponent(runId)}`)
}

export function clearRuns (datasourceId = '') {
  return axios.delete(`${TEXT2SQL_BASE}/runs`, {
    params: datasourceId ? { datasourceId } : {}
  })
}

export function createFeedback (runId, payload) {
  return axios.post(`${TEXT2SQL_BASE}/runs/${encodeURIComponent(runId)}/feedback`, payload)
}

export function listFeedback (datasourceId) {
  return axios.get(`${TEXT2SQL_BASE}/feedback`, { params: { datasourceId } })
}

export function listFavorites () {
  return axios.get(`${TEXT2SQL_BASE}/favorites`)
}

export function createFavorite (payload) {
  return axios.post(`${TEXT2SQL_BASE}/favorites`, payload)
}

export function updateFavorite (favoriteId, payload) {
  return axios.patch(`${TEXT2SQL_BASE}/favorites/${encodeURIComponent(favoriteId)}`, payload)
}

export function deleteFavorite (favoriteId) {
  return axios.delete(`${TEXT2SQL_BASE}/favorites/${encodeURIComponent(favoriteId)}`)
}

export function getWorkspace () {
  return axios.get(`${TEXT2SQL_BASE}/workspace`)
}

export function saveWorkspace (payload) {
  return axios.put(`${TEXT2SQL_BASE}/workspace`, payload)
}

export function createValue (datasourceId, payload) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/values`, payload)
}

export function updateValue (datasourceId, valueId, payload) {
  return axios.patch(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/values/${encodeURIComponent(valueId)}`, payload)
}

export function deleteValue (datasourceId, valueId) {
  return axios.delete(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/values/${encodeURIComponent(valueId)}`)
}

export function createMetric (datasourceId, payload) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/metrics`, payload)
}

export function updateMetric (datasourceId, metricId, payload) {
  return axios.patch(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/metrics/${encodeURIComponent(metricId)}`, payload)
}

export function deleteMetric (datasourceId, metricId) {
  return axios.delete(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/metrics/${encodeURIComponent(metricId)}`)
}

// 审核通过 / 停用：APPROVED 与 DISABLED 两种终态。
export function setMetricStatus (datasourceId, metricId, status) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/metrics/${encodeURIComponent(metricId)}/status`, { status })
}

export function createRelation (datasourceId, payload) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/relations`, payload)
}

export function updateRelation (datasourceId, relationId, payload) {
  return axios.patch(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/relations/${encodeURIComponent(relationId)}`, payload)
}

export function deleteRelation (datasourceId, relationId) {
  return axios.delete(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/relations/${encodeURIComponent(relationId)}`)
}

export function verifyRelation (datasourceId, relationId, verified) {
  return axios.post(`${TEXT2SQL_BASE}/datasources/${encodeURIComponent(datasourceId)}/relations/${encodeURIComponent(relationId)}/verification`, { verified })
}
