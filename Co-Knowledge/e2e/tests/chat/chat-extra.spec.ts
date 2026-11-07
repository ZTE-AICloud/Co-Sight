import { test, expect, resourceName } from '../../support/fixtures/test'
import { env } from '../../support/env'
import { ChatPage } from '../../support/pages/chat.page'
import { cleanupSeed, seedKbWithMarkdown, waitForKbRetrieval } from '../../support/fixtures/seed'
import type { ApiClient } from '../../support/api/api-client'
import type { SeededKb } from '../../support/fixtures/seed'

async function seedChatFlow (
  api: ApiClient,
  caseId: string
): Promise<{ kb: SeededKb; workFlowId: string; name: string }> {
  const kb = await seedKbWithMarkdown(api, `${caseId}-KB`)
  const name = resourceName(caseId)
  const workFlowId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
  await api.flow.create({
    name,
    workFlowId,
    template: 'Blended',
    knowledgeType: 'knowledgeBase',
    boundInfo: {
      running: [{
        name: kb.kbName,
        tableName: `doc_${kb.kbId}`,
        embeddingModel: kb.embeddingModel,
        type: 'document'
      }]
    }
  })
  await api.flow.publish(workFlowId)
  await api.flow.waitForPublished(workFlowId)
  return { kb, workFlowId, name }
}

async function openChatWithFlow (
  page: Parameters<typeof test>[0] extends never ? never : import('@playwright/test').Page,
  name: string
): Promise<ChatPage> {
  const chat = new ChatPage(page)
  await chat.goto()
  await chat.selectWorkflow(name)
  return chat
}

async function cleanupChatFlow (
  api: ApiClient,
  seeded: { kb: SeededKb; workFlowId: string }
): Promise<void> {
  try { await api.flow.delete(seeded.workFlowId) } catch { /* best effort */ }
  await cleanupSeed(api, seeded.kb)
}

test.describe('对话测试补充', () => {
  // mock 配置是进程级全局状态；不复位会把 answerContent/reasoning 泄漏给同目录的
  // stream.spec.ts，表现为“单跑通过、全跑失败”。
  test.afterEach(async ({ api }) => {
    if (env.modelMode === 'live') return
    await api.mockReset().catch(() => undefined)
  })

  test('@p0 CHAT-01 下拉只显示已发布工作流', async ({ page, api }) => {
    test.setTimeout(180_000)
    const draftKb = await seedKbWithMarkdown(api, 'CHAT-01-DRAFT-KB')
    const published = await seedChatFlow(api, 'CHAT-01-PUB')
    const draftName = resourceName('CHAT-01-DRAFT')
    const draftId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
    try {
      await api.flow.create({
        name: draftName,
        workFlowId: draftId,
        template: 'Blended',
        boundInfo: {
          running: [{
            name: draftKb.kbName,
            tableName: `doc_${draftKb.kbId}`,
            embeddingModel: draftKb.embeddingModel,
            type: 'document'
          }]
        }
      })

      const chat = new ChatPage(page)
      await chat.goto()
      await chat.workflowSelect.click()
      await expect(page.locator('.el-select-dropdown__item').filter({ hasText: published.name }).first())
        .toBeVisible()
      await expect(page.locator('.el-select-dropdown__item').filter({ hasText: draftName }))
        .toHaveCount(0)
      await page.keyboard.press('Escape')
    } finally {
      try { await api.flow.delete(draftId) } catch { /* best effort */ }
      await cleanupChatFlow(api, published)
      await cleanupSeed(api, draftKb)
    }
  })

  test('@p1 CHAT-03 思考过程展开/收起', async ({ page, api }) => {
    test.setTimeout(240_000)
    const seeded = await seedChatFlow(api, 'CHAT-03')
    try {
      await api.mockReset()
      await api.mockConfig({
        reasoning: true,
        streamFrames: 8,
        delayMs: 60,
        answerMarker: 'E2E_REASON_ANSWER'
      })
      const chat = await openChatWithFlow(page, seeded.name)
      await chat.ask(`请回答：${seeded.kb.marker}`)

      await expect(chat.root.locator('.chat-reasoning').first())
        .toBeVisible({ timeout: 60_000 })
      await expect(chat.root.locator('.chat-reasoning__body').first())
        .toContainText('E2E 思考中')
      await expect(chat.assistantBubbles().last()).toContainText('E2E_REASON_ANSWER', {
        timeout: 120_000
      })
      await chat.waitForIdle()
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p0 CHAT-04 停止生成保留已收到内容', async ({ page, api }) => {
    test.setTimeout(240_000)
    const seeded = await seedChatFlow(api, 'CHAT-04')
    try {
      await api.mockReset()
      await api.mockConfig({
        streamFrames: 60,
        delayMs: 250,
        answerMarker: 'E2E_STOP_ANSWER'
      })
      const chat = await openChatWithFlow(page, seeded.name)
      await chat.ask(`请慢慢回答：${seeded.kb.marker}`)

      await expect(chat.stopButton).toBeVisible({ timeout: 30_000 })
      await page.waitForTimeout(600)
      await chat.stopButton.click()
      await expect(chat.root.locator('.chat-stopped').first()).toBeVisible({
        timeout: 20_000
      })
      await expect(chat.assistantBubbles().last()).not.toBeEmpty()
      await chat.waitForIdle(30_000)
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p0 CHAT-05 多轮上下文与新会话对照', async ({ page, api }) => {
    test.setTimeout(300_000)
    const seeded = await seedChatFlow(api, 'CHAT-05')
    try {
      await api.mockReset()
      await api.mockConfig({ streamFrames: 2, delayMs: 10 })
      const first = `第一轮主题-${Date.now()}`
      const chat = await openChatWithFlow(page, seeded.name)

      await chat.ask(first)
      await chat.waitForIdle()
      await chat.ask('那它有什么缺点？')
      await chat.waitForIdle()

      let requests = await api.mockRequests()
      let rewritePrompts = requests
        .filter(item => item.promptKind === 'rewrite')
        .map(item => String(item.promptFull || ''))
      expect(rewritePrompts.some(prompt => prompt.includes(first))).toBe(true)

      await chat.newSession()
      await chat.ask('这是新会话的问题')
      await chat.waitForIdle()

      requests = await api.mockRequests()
      rewritePrompts = requests
        .filter(item => item.promptKind === 'rewrite')
        .map(item => String(item.promptFull || ''))
      const newSessionPrompt = rewritePrompts[rewritePrompts.length - 1] || ''
      expect(newSessionPrompt).not.toContain(first)
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p0 CHAT-06 刷新持久化与新会话清空', async ({ page, api }) => {
    test.setTimeout(240_000)
    const seeded = await seedChatFlow(api, 'CHAT-06')
    try {
      await api.mockReset()
      await api.mockConfig({ streamFrames: 2, delayMs: 10 })
      const chat = await openChatWithFlow(page, seeded.name)
      const marker = `E2E_PERSIST_${Date.now()}`
      await chat.ask(marker)
      await chat.waitForIdle()
      await expect(chat.messages).toHaveCount(2)

      await page.reload()
      await chat.goto()
      await expect(chat.messages).toHaveCount(2, { timeout: 30_000 })
      await chat.newSession()
      await expect(chat.messages).toHaveCount(0)
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p1 CHAT-07 切换工作流历史隔离', async ({ page, api }) => {
    test.setTimeout(300_000)
    const first = await seedChatFlow(api, 'CHAT-07-A')
    const second = await seedChatFlow(api, 'CHAT-07-B')
    try {
      await api.mockReset()
      await api.mockConfig({ streamFrames: 2, delayMs: 10 })
      const chat = await openChatWithFlow(page, first.name)
      await chat.ask(`只属于第一条流的标记 ${first.kb.marker}`)
      await chat.waitForIdle()
      expect(await chat.messages.count()).toBe(2)

      await chat.selectWorkflow(second.name)
      await expect(chat.messages).toHaveCount(0, { timeout: 20_000 })
      await chat.ask('第二条流的问题')
      await chat.waitForIdle()
      expect(await chat.messages.count()).toBe(2)

      await chat.selectWorkflow(first.name)
      await expect(chat.messages.filter({ hasText: first.kb.marker }).first())
        .toBeVisible({ timeout: 20_000 })
    } finally {
      await cleanupChatFlow(api, first)
      await cleanupChatFlow(api, second)
    }
  })

  test('@p1 CHAT-08 绑定知识库被删除时显示告警', async ({ page, api }) => {
    test.setTimeout(180_000)
    const models = await api.listEmbeddingModels()
    const kbName = resourceName('CHAT-08-KB')
    const kb = await api.kb.create({
      name: kbName,
      description: 'empty for chat binding',
      props: { embeddingModel: models[0] }
    })
    const name = resourceName('CHAT-08')
    const workFlowId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
    try {
      await api.flow.create({
        name,
        workFlowId,
        template: 'Blended',
        boundInfo: {
          running: [{
            name: kbName,
            tableName: `doc_${kb.id}`,
            embeddingModel: models[0],
            type: 'document'
          }]
        }
      })
      await api.flow.publish(workFlowId)
      await api.flow.waitForPublished(workFlowId)
      await api.kb.delete(kb.id)

      const chat = new ChatPage(page)
      await chat.goto()
      await chat.selectWorkflow(name)
      await expect(chat.root.getByText('知识检索绑定的知识库已不存在')).toBeVisible({
        timeout: 30_000
      })
      await expect(chat.root.getByText(kbName)).toBeVisible({ timeout: 30_000 })
    } finally {
      try { await api.flow.delete(workFlowId) } catch { /* best effort */ }
      try { await api.kb.delete(kb.id) } catch { /* best effort */ }
    }
  })

  test('@p1 CHAT-09 网络错误可见且可重试', async ({ page, api, consoleErrors }) => {
    test.setTimeout(180_000)
    // 故意 abort 请求，浏览器必然会报一条资源加载失败的 console error。
    consoleErrors.allow(/Failed to load resource: net::ERR_FAILED/)
    const seeded = await seedChatFlow(api, 'CHAT-09')
    try {
      await page.route('**/api/co-knowledge/v1/query', route => route.abort('failed'))
      const chat = await openChatWithFlow(page, seeded.name)
      await chat.ask('网络错误测试')
      await expect(
        chat.root.locator('.assistant-bubble--error, .el-alert--error').first()
      ).toBeVisible({ timeout: 30_000 })
      await chat.waitForIdle(30_000)
      await page.unroute('**/api/co-knowledge/v1/query')
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p1 CHAT-10 Enter 发送 / Shift+Enter 换行', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedChatFlow(api, 'CHAT-10')
    try {
      await api.mockReset()
      await api.mockConfig({ streamFrames: 2, delayMs: 10 })
      const chat = await openChatWithFlow(page, seeded.name)
      await chat.input.fill('第一行')
      await chat.input.press('Shift+Enter')
      await expect(chat.messages).toHaveCount(0)
      await expect(chat.input).toHaveValue(/第一行\s/)
      await chat.input.press('Enter')
      await expect(chat.messages.first()).toBeVisible({ timeout: 20_000 })
      await chat.waitForIdle()
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p1 CHAT-11 Markdown 渲染与 XSS 清理', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedChatFlow(api, 'CHAT-11')
    try {
      await api.mockReset()
      await api.mockConfig({
        streamFrames: 4,
        delayMs: 10,
        answerContent: [
          '## E2E Markdown 标题',
          '',
          '```js',
          'console.log(1)',
          '```',
          '',
          '| A | B |',
          '| - | - |',
          '| 1 | 2 |',
          '',
          '<script>window.__xss = 1</script>',
          '<img src=x onerror="window.__xss = 2">'
        ].join('\n')
      })
      const chat = await openChatWithFlow(page, seeded.name)
      await chat.ask('请输出 Markdown')
      await chat.waitForIdle()
      const markdown = chat.root.locator('.chat-markdown').last()
      await expect(markdown.locator('h2')).toContainText('E2E Markdown 标题')
      await expect(markdown.locator('pre code')).toBeVisible()
      await expect(markdown.locator('table')).toBeVisible()
      expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss))
        .toBeUndefined()
      await expect(markdown.locator('script')).toHaveCount(0)
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p2 CHAT-12 长回答自动滚动', async ({ page, api }) => {
    test.setTimeout(240_000)
    const seeded = await seedChatFlow(api, 'CHAT-12')
    try {
      await api.mockReset()
      await api.mockConfig({
        streamFrames: 20,
        delayMs: 20,
        answerContent: Array.from({ length: 120 }, (_, index) => `第 ${index + 1} 行长回答内容。`).join('\n\n')
      })
      const chat = await openChatWithFlow(page, seeded.name)
      await chat.ask('请输出长回答')
      await chat.waitForIdle()
      const position = await chat.root.locator('.conversation').evaluate(element => ({
        scrollTop: element.scrollTop,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight
      }))
      expect(position.scrollTop + position.clientHeight)
        .toBeGreaterThanOrEqual(position.scrollHeight - 60)
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  // 已知限制：没有独立环境移除生成模型注册表；CHAT-09 已覆盖网络错误可见性。
  test.fixme('@p2 CHAT-13 未配置生成模型', async ({ page, api }) => {
    const seeded = await seedChatFlow(api, 'CHAT-13')
    await openChatWithFlow(page, seeded.name)
  })

  test('@p0 CHAT-14 回答上方显示知识库依据（先于正文，刷新后仍在）', async ({ page, api }) => {
    test.setTimeout(300_000)
    const seeded = await seedChatFlow(api, 'CHAT-14')
    try {
      // status=1 只代表文件上传完成；切片/向量落库是异步的，先等到一次真实命中
      await waitForKbRetrieval(api, seeded.kb)
      await api.mockReset()
      // 放大帧间隔：确保「证据已出现、正文还在流」的窗口足够断言
      await api.mockConfig({
        streamFrames: 60,
        delayMs: 150,
        answerMarker: 'E2E_EVIDENCE_ANSWER'
      })
      const chat = await openChatWithFlow(page, seeded.name)
      // 问句与切片要有足够词元重叠：工作流 vector 路带 score_threshold=0.3，
      // mock embedding 是词法相似度，只报 marker 可能被挡成零命中。
      await chat.ask(`请回答 Knowledge Studio 端到端测试文档里的唯一标记：${seeded.kb.marker}`)

      // 证据帧先于正文：生成还没结束时摘要行就应该出现
      const evidence = chat.evidence.last()
      await expect(evidence).toBeVisible({ timeout: 60_000 })
      await expect(evidence).toContainText('正在生成回答')
      await expect(chat.stopButton).toBeVisible()

      await expect(chat.assistantBubbles().last()).toContainText('E2E_EVIDENCE_ANSWER', {
        timeout: 120_000
      })
      await chat.waitForIdle()

      // 右侧链路面板：Blended 模板含改写 + 重排 + 向量/关键字两路检索，各段都显示实测毫秒
      for (const stage of ['understanding', 'retrieval', 'keyword', 'rerank', 'generate'] as const) {
        await expect(chat.traceStep(stage)).toContainText(/\d+(\.\d+)?\s*(ms|s)/)
      }

      // 结束后换成可展开面板：来源文件名、片段正文、检索问句
      await expect(evidence.locator('summary')).toBeVisible()
      await evidence.locator('summary').click()
      await expect(evidence).toContainText(`${seeded.kb.kbName}.md`)
      await expect(evidence).toContainText(seeded.kb.marker)
      await expect(evidence).toContainText('检索问句')

      // 刷新后证据随历史会话恢复（落盘时正文被压缩，但来源仍在）
      await page.reload()
      await chat.goto()
      const restored = chat.evidence.last()
      await expect(restored).toBeVisible({ timeout: 30_000 })
      await restored.locator('summary').click()
      await expect(restored).toContainText(`${seeded.kb.kbName}.md`)

      // 阶段耗时同样跨刷新：服务端 timings 随证据落盘，客户端相位随消息落盘
      for (const stage of ['understanding', 'retrieval', 'keyword', 'rerank', 'generate'] as const) {
        await expect(chat.traceStep(stage)).toContainText(/\d+(\.\d+)?\s*(ms|s)/)
      }
    } finally {
      await cleanupChatFlow(api, seeded)
    }
  })

  test('@p1 CHAT-15 零命中时明确告警且不伪造依据', async ({ page, api }) => {
    test.setTimeout(240_000)
    const models = await api.listEmbeddingModels()
    const kbName = resourceName('CHAT-15-KB')
    const kb = await api.kb.create({
      name: kbName,
      description: 'empty for zero-hit evidence',
      props: { embeddingModel: models[0] }
    })
    const name = resourceName('CHAT-15')
    const workFlowId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
    try {
      await api.flow.create({
        name,
        workFlowId,
        template: 'Blended',
        knowledgeType: 'knowledgeBase',
        boundInfo: {
          running: [{
            name: kbName,
            tableName: `doc_${kb.id}`,
            embeddingModel: models[0],
            type: 'document'
          }]
        }
      })
      await api.flow.publish(workFlowId)
      await api.flow.waitForPublished(workFlowId)

      await api.mockReset()
      await api.mockConfig({ streamFrames: 2, delayMs: 10 })
      const chat = await openChatWithFlow(page, name)
      await chat.ask('这个空知识库里有什么？')
      await chat.waitForIdle()

      const evidence = chat.evidence.last()
      await expect(evidence).toBeVisible({ timeout: 30_000 })
      await expect(evidence).toContainText('未命中知识库')
      await expect(chat.evidenceItems).toHaveCount(0)
    } finally {
      try { await api.flow.delete(workFlowId) } catch { /* best effort */ }
      try { await api.kb.delete(kb.id) } catch { /* best effort */ }
    }
  })
})
