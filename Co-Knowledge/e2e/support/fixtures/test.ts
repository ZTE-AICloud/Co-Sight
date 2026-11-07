/**
 * 自定义 test fixture。
 *
 * - `api`：API 造数/清理客户端
 * - `consoleErrors`（auto）：收集 console.error / pageerror；用例结束时有未放行的
 *   错误就失败。需要故意制造错误（断网、5xx）的用例先调用 `consoleErrors.allow(...)`。
 * - `runId`：本次运行唯一标识，测试资源名统一带它。
 */
import { test as base, expect } from '@playwright/test'
import { ApiClient } from '../api/api-client'
import { env, resourceName } from '../env'

export interface ConsoleErrorCollector {
  readonly messages: string[]
  /** 放行某类预期内的 console error（正则匹配整条文本）。 */
  allow: (pattern: RegExp) => void
}

interface Fixtures {
  api: ApiClient
  consoleErrors: ConsoleErrorCollector
  runId: string
}

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request, env.baseURL))
  },

  runId: async ({}, use) => {
    await use(env.runId)
  },

  consoleErrors: [async ({ page }, use) => {
    const messages: string[] = []
    const allowed: RegExp[] = []

    page.on('console', message => {
      if (message.type() === 'error') messages.push(message.text())
    })
    page.on('pageerror', error => {
      messages.push(`pageerror: ${error.message}`)
    })

    const collector: ConsoleErrorCollector = {
      messages,
      allow: pattern => allowed.push(pattern)
    }

    await use(collector)

    const unexpected = messages.filter(
      message => !allowed.some(pattern => pattern.test(message))
    )
    if (unexpected.length > 0) {
      throw new Error(
        `页面出现 ${unexpected.length} 条未放行的 console error：\n` +
        unexpected.map(message => `  - ${message}`).join('\n')
      )
    }
  }, { auto: true }]
})

export { expect, resourceName }
