/**
 * 全局健康门禁：栈没准备好时**先失败**，不要让每条用例各自等 30 秒。
 *
 * 覆盖三件事：
 * 1. web 入口可达（`/` 返回 200）
 * 2. RKB 唯一健康端点 `<prefix>/health`（纯文本 `ok`）
 * 3. mock 模式下 fake-model-gateway 的 `/__mock__/health`
 *
 * 失败信息直接给出排查命令，不打印一屏 stack trace。
 */
import { request } from '@playwright/test'
import { env } from './env'

const HEALTH_TIMEOUT_MS = 90_000
const POLL_INTERVAL_MS = 1_000

async function waitForHealth (
  label: string,
  probe: () => Promise<boolean>
): Promise<void> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS
  let lastError = ''
  while (Date.now() < deadline) {
    try {
      if (await probe()) return
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
    await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS))
  }
  throw new Error(
    `[e2e] ${label} 在 ${HEALTH_TIMEOUT_MS / 1000}s 内未就绪。\n` +
    `  入口: ${env.baseURL}\n` +
    `  最近错误: ${lastError || '无'}\n` +
    '  排查: docker compose -p "$E2E_PROJECT" -f deploy/docker-compose.yml ' +
    '-f deploy/docker-compose.e2e.yml logs --tail=200'
  )
}

export default async function globalSetup (): Promise<void> {
  const context = await request.newContext({ baseURL: env.baseURL })
  try {
    await waitForHealth('web 入口', async () => {
      const response = await context.get('/', { timeout: 5_000 })
      return response.ok()
    })

    await waitForHealth('RKB /health', async () => {
      const response = await context.get('/api/co-knowledge/v1/health', { timeout: 5_000 })
      if (!response.ok()) return false
      return (await response.text()).trim() === 'ok'
    })

    // AUTH_MODE=local：先登录，后续 seed 请求才带得上会话 Cookie。
    if (env.authMode === 'local') {
      const response = await context.post('/api/co-knowledge/v1/auth/login', {
        data: { username: env.adminUsername, password: env.adminPassword },
        headers: { Origin: env.baseURL }
      })
      if (!response.ok()) {
        throw new Error(
          `[e2e] admin 登录失败: ${response.status()} ${await response.text()}\n` +
          '  检查 RKB_ADMIN_* 与 E2E_AUTH_MODE 是否一致。'
        )
      }
    }

    if (env.modelMode === 'mock') {
      await waitForHealth('fake-model-gateway', async () => {
        const response = await context.get(`${env.mockBaseURL}/__mock__/health`, {
          timeout: 5_000
        })
        return response.ok()
      })

      // 第一次访问 /models 会触发 model_api 的 seed_if_empty；/system/embedding-models 的数据源
      // 就是注册表，所以必须先 seed，否则建库页的 embedding 下拉是空的。
      await waitForHealth('model registry seed', async () => {
        await context.get('/api/co-knowledge/v1/models', { timeout: 5_000 })
        const response = await context.get('/api/co-knowledge/v1/system/embedding-models', { timeout: 5_000 })
        if (!response.ok()) return false
        const body = await response.json() as string[]
        return Array.isArray(body) && body.length > 0
      })
    }
  } finally {
    await context.dispose()
  }

  console.log(`[e2e] 环境就绪: ${env.baseURL} (mock=${env.modelMode}, runId=${env.runId})`)
}
