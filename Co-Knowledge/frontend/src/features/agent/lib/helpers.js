/**
 * 「远程接入」页的纯函数。
 *
 * 单独抽出来是为了能在 vitest 里直接断言（渲染组件断言代码片段既慢又脆）。
 * 这里不 import Vue / Element Plus / axios。
 */

/** scope → i18n 键。键名必须同时存在于 zh/en 两份 remoteAccess 文案里。 */
export const SCOPE_LABEL_KEYS = {
  'kb:list': 'modules.remoteAccess.scopeKbList',
  'kb:search': 'modules.remoteAccess.scopeKbSearch',
  'kb:answer': 'modules.remoteAccess.scopeKbAnswer',
  'workflow:read': 'modules.remoteAccess.scopeWorkflowRead',
  'workflow:run': 'modules.remoteAccess.scopeWorkflowRun'
}

/** 后端 scope 的固定展示顺序。 */
export const SCOPE_ORDER = ['kb:list', 'kb:search', 'kb:answer',
  'workflow:read', 'workflow:run']

/** `YYYY-MM-DD` 的长度（编辑差异比较时只取日期部分）。 */
const DATE_ONLY_LENGTH = 10

export function scopeLabelKey (scope) {
  return SCOPE_LABEL_KEYS[scope] || 'modules.remoteAccess.scopeUnknown'
}

/** 去重并按固定顺序排列；未知 scope 丢弃（后端也会拒绝）。 */
export function normalizeScopes (value) {
  const list = Array.isArray(value) ? value : []
  return SCOPE_ORDER.filter(scope => list.includes(scope))
}

/**
 * 把相对路径变成可复制的绝对地址。
 *
 * `base` 允许已是绝对 URL（`VUE_APP_KBASE_BASE` 可以被部署成绝对地址），此时原样返回。
 *
 * @param {string} path
 * @param {string} [origin] 默认 `window.location.origin`
 * @returns {string}
 */
export function absoluteUrl (path, origin) {
  if (!path) {
    return ''
  }
  if (/^https?:\/\//i.test(path)) {
    return path
  }
  let base = origin
  if (base === undefined) {
    base = typeof window !== 'undefined' ? window.location.origin : ''
  }
  if (!base) {
    return path
  }
  const separator = path.startsWith('/') ? '' : '/'
  return `${base}${separator}${path}`
}

const KEY_PLACEHOLDER = '<YOUR_API_KEY>'

export function buildClaudeCommand (mcpUrl, keyPlaceholder = KEY_PLACEHOLDER) {
  return [
    `claude mcp add --transport http co-knowledge ${mcpUrl} \\`,
    `  --header "Authorization: Bearer ${keyPlaceholder}"`
  ].join('\n')
}

export function buildMcpJson (mcpUrl, keyPlaceholder = KEY_PLACEHOLDER) {
  return JSON.stringify({
    mcpServers: {
      'co-knowledge': {
        type: 'http',
        url: mcpUrl,
        headers: { Authorization: `Bearer ${keyPlaceholder}` }
      }
    }
  }, null, 2)
}

export function buildMcpCurl (mcpUrl) {
  return [
    `curl -sS ${mcpUrl} \\`,
    '  -H "Authorization: Bearer $RAG_STUDIO_KEY" \\',
    '  -H "Content-Type: application/json" \\',
    '  -H "Accept: application/json, text/event-stream" \\',
    '  -d \'{"jsonrpc":"2.0","id":1,"method":"initialize","params":' +
      '{"protocolVersion":"2025-06-18","capabilities":{},' +
      '"clientInfo":{"name":"curl","version":"0"}}}\''
  ].join('\n')
}

export function buildStdioCommand (mcpUrl, keyPlaceholder = KEY_PLACEHOLDER) {
  return `npx -y mcp-remote ${mcpUrl} \\\n  --header "Authorization: Bearer ${keyPlaceholder}"`
}

export function buildListCurl (restBase) {
  return [
    `curl -sS ${restBase}/knowledge-bases \\`,
    '  -H "Authorization: Bearer $RAG_STUDIO_KEY"'
  ].join('\n')
}

export function buildSearchCurl (restBase) {
  return [
    `curl -sS ${restBase}/search \\`,
    '  -H "Authorization: Bearer $RAG_STUDIO_KEY" \\',
    '  -H "Content-Type: application/json" \\',
    '  -d \'{"query":"your question","top_k":5}\''
  ].join('\n')
}

export function buildAnswerCurl (restBase) {
  return [
    `curl -sS ${restBase}/answer \\`,
    '  -H "Authorization: Bearer $RAG_STUDIO_KEY" \\',
    '  -H "Content-Type: application/json" \\',
    '  -d \'{"question":"your question","top_k":8}\''
  ].join('\n')
}

/**
 * ISO / 日期字符串 → `YYYY-MM-DD HH:mm`（本地时区）。
 * 空值返回 `''`；解析不了时原样返回，避免把后端值吞成 `Invalid Date`。
 */
export function formatDateTime (value) {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }
  const pad = number => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/**
 * 调用量计数 → 千分位字符串（`12,430`）。
 *
 * 空值 / 非数字回落 `—`（与「接口未提供」的占位一致）；计数只做展示，
 * 不做单位换算，保持与后端返回的原始数字一致。
 */
export function formatCount (value) {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '—'
  }
  return Math.round(number).toLocaleString('en-US')
}

/**
 * 过期日：按 **UTC** 取日期。
 *
 * 后端把 ``YYYY-MM-DD`` 存成当天 ``23:59:59 UTC``，序列化时带时区偏移；
 * 用本地 ``getDate()`` 在东八区会显示成第二天，和用户选的日期不一致。
 * 列表只展示日期，时间固定由「23:59:59 UTC」提示。
 */
export function formatDateUTC (value) {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }
  const pad = number => String(number).padStart(2, '0')
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
}

/** 过期判断；空值 = 永不过期。 */
export function isExpired (expiresAt, now = Date.now()) {
  if (!expiresAt) {
    return false
  }
  const time = new Date(expiresAt).getTime()
  if (Number.isNaN(time)) {
    return false
  }
  return time <= now
}

function sameList (left, right) {
  const a = [...(left || [])].sort()
  const b = [...(right || [])].sort()
  return a.length === b.length && a.every((item, index) => item === b[index])
}

/**
 * 编辑弹窗的**差量**载荷。
 *
 * 只发真正变化的字段有两个原因：
 * 1. 后端对 `expiresAt` 有「必须晚于当前时间」的校验 —— 一把已经过期的 Key
 *    如果每次编辑都回传旧日期，会永远保存失败；
 * 2. 避免把一次「只改限流」的操作放大成整行覆盖（多人同时编辑时更容易互相踩）。
 *
 * @param {object} original 列表行的 DTO（camelCase）
 * @param {object} form     表单值（expiresAt 为 `YYYY-MM-DD` 或空串）
 * @returns {object} 可直接 PATCH 的载荷；无变化时为 `{}`
 */
export function buildPatchPayload (original, form) {
  const payload = {}
  const originalName = (original && original.name) || ''
  const formName = form && form.name ? String(form.name).trim() : ''
  if (formName !== originalName) {
    payload.name = formName
  }

  const originalDescription = (original && (original.description ?? original.desc)) || ''
  const formDescription = form && form.description ? String(form.description).trim() : ''
  if (formDescription !== originalDescription) {
    payload.description = formDescription
  }

  const originalScopes = normalizeScopes(original && original.scopes)
  const formScopes = normalizeScopes(form && form.scopes)
  if (!sameList(formScopes, originalScopes)) {
    payload.scopes = formScopes
  }

  if (!sameList(form && form.kbIds, original && original.kbIds)) {
    payload.kbIds = [...(form && form.kbIds ? form.kbIds : [])]
  }

  const originalRate = Number(original && original.rateLimitPerMin)
  const formRate = Number(form && form.rateLimitPerMin)
  if (formRate !== originalRate) {
    payload.rateLimitPerMin = formRate
  }

  const originalExpires = original && original.expiresAt
    ? String(original.expiresAt).slice(0, DATE_ONLY_LENGTH)
    : ''
  const formExpires = (form && form.expiresAt) || ''
  if (formExpires !== originalExpires) {
    payload.expiresAt = formExpires || null
  }

  return payload
}
