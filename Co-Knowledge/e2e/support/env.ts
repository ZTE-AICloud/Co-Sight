/**
 * E2E 环境变量单点读取。
 *
 * 所有默认值都指向 `deploy/docker-compose.e2e.yml` 的约定：
 * - web 发布到 127.0.0.1:18080
 * - fake-model-gateway 的宿主调试端口 127.0.0.1:18081
 *
 * 不要在测试文件里直接读 `process.env`，否则默认值与覆盖逻辑会各写一份。
 */

function trimTrailingSlash (value: string): string {
  return value.replace(/\/+$/, '')
}

function nonEmpty (value: string | undefined, fallback: string): string {
  const trimmed = (value || '').trim()
  return trimmed || fallback
}

export const env = {
  baseURL: trimTrailingSlash(nonEmpty(process.env.E2E_BASE_URL, 'http://127.0.0.1:18080')),
  mockBaseURL: trimTrailingSlash(nonEmpty(process.env.E2E_MOCK_BASE_URL, 'http://127.0.0.1:18081')),
  runId: nonEmpty(process.env.E2E_RUN_ID, `e2e-${Date.now().toString(36)}`),
  modelMode: nonEmpty(process.env.E2E_MODEL_MODE, 'mock'),
  browserChannel: (process.env.E2E_BROWSER_CHANNEL || '').trim(),
  locale: nonEmpty(process.env.E2E_LOCALE, 'zh-CN'),
  timezone: nonEmpty(process.env.E2E_TIMEZONE, 'Asia/Shanghai'),
  // 本地账号 E2E：与栈的 AUTH_MODE 保持一致；none 时这些字段不参与鉴权。
  authMode: nonEmpty(process.env.E2E_AUTH_MODE, 'none'),
  adminUsername: nonEmpty(process.env.E2E_ADMIN_USERNAME, 'e2e-admin'),
  adminPassword: process.env.E2E_ADMIN_PASSWORD || 'E2eAdminPass123!'
} as const

/** 用例资源名统一前缀；同一 run 内再加用例 ID，避免并行 worker 撞名。 */
export function resourceName (caseId: string, suffix = ''): string {
  const tail = suffix ? `-${suffix}` : ''
  const full = `E2E-${env.runId}-${caseId}${tail}`
  // KB 名称上限 30；超长时截断并追加稳定哈希，既满足校验又不丢唯一性。
  if (full.length <= 30) return full
  let hash = 0
  for (let index = 0; index < full.length; index += 1) {
    hash = (Math.imul(hash, 31) + full.charCodeAt(index)) >>> 0
  }
  return `${full.slice(0, 23)}-${hash.toString(36).slice(0, 5)}`
}
