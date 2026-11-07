/**
 * 基础设施故障演练（RES-01/02）。
 *
 * 这些用例会 **stop/restart 容器**，默认不跑：`E2E_INFRA=1` 时才执行，且必须串行
 * （Playwright 的 workers 对本文件应为 1）。容器名可用环境变量覆盖。
 */
import { execFileSync } from 'node:child_process'
import { test, expect, resourceName } from '../../support/fixtures/test'
import { env } from '../../support/env'
import { KbListPage } from '../../support/pages/kb-list.page'
import { cleanupSeed, seedKbWithMarkdown } from '../../support/fixtures/seed'

const RKB = process.env.E2E_RKB_CONTAINER || 'rag-studio-e2e-phase1-rag-knowledge-base-1'
const OPENSEARCH = process.env.E2E_OPENSEARCH_CONTAINER
  || 'rag-studio-e2e-phase1-opensearch-1'

const skip = process.env.E2E_INFRA !== '1'

function docker (...args: string[]): string {
  return execFileSync('docker', args, { encoding: 'utf8', timeout: 120_000 }).trim()
}

function containerHealth (name: string): string {
  try {
    return docker('inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}', name)
  } catch {
    return 'missing'
  }
}

async function waitForHealth (name: string, timeoutMs = 180_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let last = ''
  while (Date.now() < deadline) {
    last = containerHealth(name)
    if (last === 'healthy' || last === 'running') return
    await new Promise(resolve => setTimeout(resolve, 2_000))
  }
  throw new Error(`容器 ${name} 未在 ${timeoutMs / 1000}s 内恢复：${last}`)
}

async function waitForRkb (timeoutMs = 180_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let last = ''
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${env.baseURL}/api/co-knowledge/v1/health`)
      last = String(response.status)
      if (response.ok) return
    } catch (error) {
      last = String(error)
    }
    await new Promise(resolve => setTimeout(resolve, 2_000))
  }
  throw new Error(`RKB 未在 ${timeoutMs / 1000}s 内恢复：${last}`)
}

test.describe.serial('基础设施韧性', () => {
  test.skip(skip, '设置 E2E_INFRA=1 且允许 docker 控制容器时运行')

  test('@p0 RES-01 后端重启后恢复且数据不丢', async ({ page, api }) => {
    test.setTimeout(300_000)
    const seeded = await seedKbWithMarkdown(api, 'RES-01-KB')
    try {
      docker('restart', RKB)
      await waitForRkb()

      const list = new KbListPage(page)
      await list.goto()
      await list.expectRow(seeded.kbName)

      const rows = await api.listKbs()
      expect(rows.some(row => row.id === seeded.kbId)).toBe(true)
      expect((await api.listAllFiles(seeded.kbId)).length).toBeGreaterThan(0)
    } finally {
      await cleanupSeed(api, seeded)
    }
  })

  test('@p1 RES-02 OpenSearch 不可用时列表可用、检索报错明确', async ({ page, api }) => {
    test.setTimeout(300_000)
    const seeded = await seedKbWithMarkdown(api, 'RES-02-KB')
    try {
      docker('stop', OPENSEARCH)
      try {
        const list = new KbListPage(page)
        await list.goto()
        await list.expectRow(seeded.kbName)

        // type=1 是关键词检索（OpenSearch）；type=0 是向量检索（pgvector），搜索后端挂了仍可用
        await expect(api.retrieve({
          question: seeded.marker,
          kbId: seeded.kbId,
          type: 1,
          topK: 5
        })).rejects.toThrow(/ES|Elastic|elastic|检索|search|connect/i)
      } finally {
        docker('start', OPENSEARCH)
        await waitForHealth(OPENSEARCH)
      }
    } finally {
      await cleanupSeed(api, seeded)
    }
  })

})
