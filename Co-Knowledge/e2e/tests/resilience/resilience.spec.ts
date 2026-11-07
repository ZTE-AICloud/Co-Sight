import { test, expect, resourceName } from '../../support/fixtures/test'
import { env } from '../../support/env'
import { ChatPage } from '../../support/pages/chat.page'
import { ModelPage } from '../../support/pages/model.page'
import {
  cleanupSeed,
  seedKbWithMarkdown,
  seedPublishedFlow
} from '../../support/fixtures/seed'

const API_GLOB = '**/api/co-knowledge/v1/**'

test.describe('韧性', () => {
  test.afterEach(async ({ api }) => {
    if (env.modelMode === 'live') return
    await api.mockReset().catch(() => undefined)
  })

  test('@p1 RES-04 断网提示可见且恢复后可重试', async ({ page, consoleErrors }) => {
    test.setTimeout(180_000)
    consoleErrors.allow(/Failed to load resource: net::ERR_FAILED/)
    consoleErrors.allow(/获取文档知识库列表失败/)
    await page.route(API_GLOB, route => route.abort('failed'))

    // 断网时连 /auth/status 都不可达：守卫 fail-closed，登录页显示「认证服务不可用」，
    // 而不是把服务故障误当成无鉴权放行、或停在白屏。
    await page.goto(`${env.baseURL}/#/knowledge`)
    await expect(page.getByText('认证服务不可用')).toBeVisible({ timeout: 30_000 })

    await page.unroute(API_GLOB)
    await page.getByRole('button', { name: '重试' }).click()
    await expect(page.getByRole('button', { name: '免登录体验' })).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: '免登录体验' }).click()
    await expect(page.locator('.knowledge-page')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.el-pagination').first()).toBeVisible()
  })

  test('@p1 RES-05 API 超时后 loading 结束且可重试', async ({ page, consoleErrors }) => {
    test.setTimeout(180_000)
    consoleErrors.allow(/Failed to load resource/)
    consoleErrors.allow(/获取文档知识库列表失败/)
    await page.route('**/api/co-knowledge/v1/knowledge-bases**', async route => {
      await new Promise(resolve => setTimeout(resolve, 8_000))
      await route.abort('timedout')
    })

    const navigation = page.goto(`${env.baseURL}/#/knowledge`)
    // 列表加载中由空态行显示「加载中」（原生表格已不再挂 el-loading 遮罩）。
    await expect(page.locator('.empty-row')).toContainText('加载中', { timeout: 10_000 })
    await navigation
    await expect(page.locator('.el-loading-mask')).toHaveCount(0, { timeout: 30_000 })
    // 页面不能卡死/白屏：导航和列表壳仍然在，错误行给出「重试」。
    await expect(page.locator('.sidebar')).toBeVisible()
    await expect(page.locator('.knowledge-page')).toBeVisible()
    await expect(page.locator('.empty-row')).toContainText('数据获取失败', { timeout: 30_000 })

    await page.unroute('**/api/co-knowledge/v1/knowledge-bases**')
    await page.getByRole('button', { name: '重试' }).click()
    // 重试成功后错误行消失（有数据时表格不再渲染 .empty-row）。
    await expect(page.getByText('数据获取失败，请稍后重试')).toHaveCount(0, { timeout: 30_000 })
    await expect(page.locator('.knowledge-page')).toBeVisible()
  })

  test('@p1 RES-06 SSE 中断保留已收内容并可重发', async ({ page, api }) => {
    test.setTimeout(300_000)
    const seeded = await seedKbWithMarkdown(api, 'RES-06-KB')
    let flowId = ''
    try {
      flowId = await seedPublishedFlow(api, seeded, 'RES-06')
      await api.mockConfig({
        streamFrames: 80,
        delayMs: 200,
        answerMarker: 'E2E_RESUME_ANSWER'
      })
      const chat = new ChatPage(page)
      await chat.goto()
      await chat.selectWorkflow(resourceName('RES-06'))
      await chat.ask(`慢慢回答 ${seeded.marker}`)
      await expect(chat.stopButton).toBeVisible({ timeout: 30_000 })
      await page.waitForTimeout(600)
      await chat.stopButton.click()
      await expect(chat.root.locator('.chat-stopped').first()).toBeVisible({
        timeout: 20_000
      })
      await expect(chat.assistantBubbles().last()).not.toBeEmpty()

      await api.mockConfig({ streamFrames: 2, delayMs: 10, answerMarker: 'E2E_RESEND_ANSWER' })
      await chat.ask('中断后重发')
      await chat.waitForIdle()
      await expect(chat.assistantBubbles().last()).toContainText('E2E_RESEND_ANSWER')
    } finally {
      await cleanupSeed(api, seeded, flowId)
    }
  })

  test('@p1 RES-07 双击创建只产生一条记录', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = resourceName('RES-07').toLowerCase()
    let modelId = ''
    try {
      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('大语言模型')
      await modelPage.openCreate()
      await modelPage.fill('模型名称', name)
      await modelPage.fill('端点地址', 'http://fake-model-gateway:8000/v1')

      let posts = 0
      page.on('request', request => {
        if (request.method() === 'POST' && /\/api\/co-knowledge\/v1\/models$/.test(request.url())) {
          posts += 1
        }
      })
      await modelPage.dialog.getByRole('button', { name: '添加模型', exact: true })
        .evaluate(element => {
          const button = element as HTMLElement
          button.click()
          button.click()
        })
      await expect(page.getByText('保存成功')).toBeVisible({ timeout: 20_000 })

      const rows = (await api.model.list('llm')).filter(row => row.modelName === name)
      // 后端按名称去重，记录只有一条；前端 submitHandle 入口也做了同步防重。
      expect(rows).toHaveLength(1)
      modelId = rows[0].modelId
      expect(posts, '按钮未防重：双击发出了两次 POST').toBeLessThanOrEqual(1)
    } finally {
      if (modelId) {
        try { await api.model.delete(modelId) } catch { /* best effort */ }
      }
    }
  })

  test('@p1 RES-08 两上下文并发编辑同一模型', async ({ browser, api }) => {
    test.setTimeout(180_000)
    const name = resourceName('RES-08').toLowerCase()
    const created = await api.model.create({
      modelKind: 'llm',
      modelName: name,
      displayName: 'original',
      baseUrl: 'http://fake-model-gateway:8000/v1'
    })
    const contextA = await browser.newContext()
    const contextB = await browser.newContext()
    try {
      const pageA = await contextA.newPage()
      const pageB = await contextB.newPage()
      const modelA = new ModelPage(pageA)
      const modelB = new ModelPage(pageB)
      await modelA.goto()
      await modelA.selectTab('大语言模型')
      await modelA.openEdit(name)
      await modelA.fill('显示名称', 'edited-by-A')

      await modelB.goto()
      await modelB.selectTab('大语言模型')
      await modelB.openEdit(name)
      await modelB.fill('显示名称', 'edited-by-B')

      await modelA.save()
      await expect(pageA.getByText('保存成功')).toBeVisible({ timeout: 20_000 })
      await modelB.save()
      await expect(pageB.getByText('保存成功')).toBeVisible({ timeout: 20_000 })

      const record = await api.model.get(created.modelId)
      // 后写覆盖：整行没有被写坏（类型/名称/端点仍然完整）
      expect(record.displayName).toBe('edited-by-B')
      expect(record.modelKind).toBe('llm')
      expect(record.modelName).toBe(name)
      expect(record.baseUrl).toBe('http://fake-model-gateway:8000/v1')
    } finally {
      await contextA.close()
      await contextB.close()
      try { await api.model.delete(created.modelId) } catch { /* best effort */ }
    }
  })

  test('@p2 RES-10 浏览器上下文存储隔离', async ({ browser }) => {
    test.setTimeout(120_000)
    const contextA = await browser.newContext()
    const contextB = await browser.newContext()
    try {
      await contextA.addInitScript(() => {
        localStorage.setItem('language-option', JSON.stringify('en-US'))
        localStorage.setItem('chat-test:session:isolation', '{"version":1}')
      })
      const pageA = await contextA.newPage()
      const pageB = await contextB.newPage()
      await pageA.goto(`${env.baseURL}/#/knowledge`)
      await pageB.goto(`${env.baseURL}/#/knowledge`)

      await expect(pageA.locator('html')).toHaveAttribute('lang', 'en-US')
      await expect(pageB.locator('html')).toHaveAttribute('lang', 'zh-CN')
      await expect(pageA.locator('.nav-item').filter({ hasText: 'Document Knowledge Base' }).first())
        .toBeVisible()
      await expect(pageB.locator('.nav-item').filter({ hasText: '文档知识库' }).first())
        .toBeVisible()

      const storageA = await pageA.evaluate(() => Object.keys(localStorage).sort())
      const storageB = await pageB.evaluate(() => Object.keys(localStorage).sort())
      expect(storageA).toContain('chat-test:session:isolation')
      expect(storageB).not.toContain('chat-test:session:isolation')
    } finally {
      await contextA.close()
      await contextB.close()
    }
  })
})
