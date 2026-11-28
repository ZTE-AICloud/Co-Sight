let sequence = 0

/**
 * 生成本地记录 ID。
 *
 * 不用 `crypto.randomUUID()` 裸调用：它只在安全上下文可用，纯 HTTP 部署会直接抛错。
 * 演示页的 ID 只用于本地存储去重，不需要密码学强度。
 */
export function createId (prefix = 't2s') {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  sequence += 1
  const random = Math.random().toString(36).slice(2, 10)
  return `${prefix}-${Date.now().toString(36)}-${sequence}-${random}`
}
