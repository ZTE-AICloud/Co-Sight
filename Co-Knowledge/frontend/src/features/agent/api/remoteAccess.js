import axios from '@/shared/api/client'
import { AGENT_ADMIN_BASE, KBASE_BASE } from '@/shared/api/endpoints'

/**
 * 「远程接入」页的 Key 管理接口（`{KBASE_BASE}/agent-keys`）。
 *
 * 三条与后端约定好的形状（改动前先对 `backend/src/agent_api/admin_rest.py`）：
 * 1. 列表返回 `{ items, total, page, pageSize }` —— 列表接口的分页体约定
 *    读的就是这两个字段名；多返回 `currentPage/pageSize` 只是为了排障。
 * 2. **完整 Key 只在创建响应里出现一次**（`bo.plaintextKey`），列表永远只有前缀。
 * 3. 错误是真实状态码 + RFC 9457 problem，由 `api/base.js` 统一弹提示。
 */

export function getAgentKeyStatusApi (config = {}) {
  return axios.get(`${AGENT_ADMIN_BASE}/status`, config)
}

export function queryAgentKeysApi (params, config = {}) {
  return axios.get(AGENT_ADMIN_BASE, { params, ...config })
}

/**
 * 调用量指标：`{ totalCalls, requests7d, windowStart, windowEnd }`。
 *
 * 后端在每次 Key 鉴权通过时按自然日累加；`requests7d` 含今天在内的 7 天。
 */
export function getAgentKeyStatsApi (config = {}) {
  return axios.get(`${AGENT_ADMIN_BASE}/stats`, config)
}

export function createAgentKeyApi (data, config = {}) {
  return axios.post(AGENT_ADMIN_BASE, data, config)
}

export function updateAgentKeyApi (keyPrefix, data, config = {}) {
  return axios.patch(`${AGENT_ADMIN_BASE}/${encodeURIComponent(keyPrefix)}`, data, config)
}

export function deleteAgentKeyApi (keyPrefix, config = {}) {
  return axios.delete(`${AGENT_ADMIN_BASE}/${encodeURIComponent(keyPrefix)}`, config)
}

/**
 * 文档知识库下拉（Key 的 `kbIds` 白名单）。
 *
 * 复用列表页同一条 `GET /knowledge-bases`：`categories=1` = 文档知识库。
 */
export function searchDocumentKbasesApi (params = {}, config = {}) {
  const { currentPage = 1, pageSize = 50, keyword = '' } = params || {}
  return axios.get(`${KBASE_BASE}/knowledge-bases`, {
    ...config,
    params: {
      categories: '1',
      page: currentPage,
      size: pageSize,
      keyword
    }
  })
}
