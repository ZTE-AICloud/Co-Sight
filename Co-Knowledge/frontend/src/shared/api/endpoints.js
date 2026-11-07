/**
 * 后端前缀的**单点定义**（对应后端的 `backend/src/shared/prefixes.py`）。
 *
 * 前缀只在文件里写一次，其它模块一律从这里导入。散落的字面量一旦漏改，
 * 浏览器会把它落到 SPA 回退拿到 `index.html`，前端只报「网络错误」，很难排查。
 *
 * `VUE_APP_KBASE_BASE` / `VUE_APP_WORKFLOW_BASE` / `VUE_APP_QUERY_BASE`
 * 现在是同一个值 `/api/co-knowledge/v1`（所有后端路由共用一条前缀）；
 * 三个键名保留是因为它们是部署态配置（`.env` 可覆盖）。
 */

const DEFAULT_RKB_PREFIX = '/api/co-knowledge/v1'

export const KBASE_BASE = process.env.VUE_APP_KBASE_BASE || DEFAULT_RKB_PREFIX

// 旧的 VUE_APP_ORCHESTRATOR_BASE 仍兼容，便于既有部署平滑升级。
export const QUERY_BASE = process.env.VUE_APP_QUERY_BASE
  || process.env.VUE_APP_ORCHESTRATOR_BASE
  || DEFAULT_RKB_PREFIX

/**
 * Agent 接入面的三条路径（「远程接入」页）。
 *
 * 三类前缀：
 * - `AGENT_ADMIN_BASE`：UI 管理接口
 * - `AGENT_BASE`：外部 REST，Agent Key
 * - `AGENT_MCP_PATH`：MCP Streamable HTTP
 *
 * ⚠️ 只从 `KBASE_BASE` 派生，不写第二份前缀字面量。
 */
export const AGENT_ADMIN_BASE = `${KBASE_BASE}/agent-keys`
export const AGENT_BASE = `${KBASE_BASE}/agent`
export const AGENT_MCP_PATH = `${KBASE_BASE}/mcp`

/**
 * 本地账号登录。
 * 只从 ``KBASE_BASE`` 派生，不写第二份前缀字面量。
 */
export const AUTH_BASE = `${KBASE_BASE}/auth`
