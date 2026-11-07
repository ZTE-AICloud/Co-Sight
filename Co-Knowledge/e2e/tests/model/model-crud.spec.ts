import { test, expect, resourceName } from '../../support/fixtures/test'
import { env } from '../../support/env'
import { ModelPage } from '../../support/pages/model.page'
import { cleanupSeed, seedKbWithMarkdown, seedPublishedFlow } from '../../support/fixtures/seed'
import type { ApiClient } from '../../support/api/api-client'
import type { ModelRecord } from '../../support/api/model-api'

const GATEWAY = 'http://fake-model-gateway:8000/v1'

function modelName (caseId: string): string {
  return resourceName(caseId).toLowerCase().replace(/[^a-z0-9._-]/g, '-')
}

async function deleteModel (api: ApiClient, modelId?: string): Promise<void> {
  if (!modelId) return
  try { await api.model.delete(modelId) } catch { /* best effort */ }
}

test.describe('模型管理 CRUD', () => {
  test.afterEach(async ({ api }) => {
    if (env.modelMode === 'live') return
    await api.mockReset().catch(() => undefined)
  })

  test('@p0 MODEL-02 新增 LLM：校验与即时生效', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = modelName('MODEL-02')
    let modelId = ''
    try {
      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('大语言模型')
      await modelPage.openCreate()

      // 空表单：名称与端点地址都是必填
      await modelPage.save()
      await expect(modelPage.dialog.getByText('请输入模型名称')).toBeVisible()
      await expect(modelPage.dialog.getByText('请输入有效的 HTTP 或 HTTPS 端点地址')).toBeVisible()

      await modelPage.fill('模型名称', name)
      await modelPage.fill('端点地址', 'ftp://invalid-endpoint')
      await modelPage.save()
      await expect(modelPage.dialog.getByText('请输入有效的 HTTP 或 HTTPS 端点地址'))
        .toBeVisible()

      await modelPage.fill('端点地址', GATEWAY)
      await modelPage.fill('显示名称', 'E2E LLM')
      await modelPage.save()
      await expect(page.getByText('保存成功')).toBeVisible({ timeout: 20_000 })
      await modelPage.expectRow(name)

      const record = await api.model.findByName('llm', name)
      expect(record).toBeTruthy()
      expect(record?.enabled).toBe(true)
      modelId = record!.modelId

      // 无需重启：建流时的 LLM 下拉直接能看到
      const flowModels = await api.flow.llmModels()
      expect(JSON.stringify(flowModels)).toContain(name)
    } finally {
      await deleteModel(api, modelId)
    }
  })

  test('@p0 MODEL-03 新增 Embedding 并立即用于建库', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = modelName('MODEL-03')
    const kbName = resourceName('MODEL-03-KB')
    let modelId = ''
    let kbId = ''
    try {
      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('向量模型')
      await modelPage.openCreate()
      await modelPage.selectKind('向量模型')
      await modelPage.fill('模型名称', name)
      await modelPage.fill('端点地址', GATEWAY)
      await modelPage.fill('向量维度', '1024')
      await modelPage.save()
      await expect(page.getByText('保存成功')).toBeVisible({ timeout: 20_000 })
      await modelPage.expectRow(name)

      modelId = (await api.model.findByName('embedding', name))!.modelId
      expect(await api.listEmbeddingModels()).toContain(name)

      const kb = await api.createKb(kbName, name)
      kbId = kb.id
    } finally {
      if (kbId) await api.cleanupKb(kbId)
      await deleteModel(api, modelId)
    }
  })

  test('@p1 MODEL-04 新增 Reranker 并发布编排', async ({ page, api }) => {
    test.setTimeout(240_000)
    const name = modelName('MODEL-04')
    const seeded = await seedKbWithMarkdown(api, 'MODEL-04-KB')
    let flowId = ''
    let modelId = ''
    try {
      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('重排模型')
      await modelPage.openCreate()
      await modelPage.selectKind('重排模型')
      await modelPage.fill('模型名称', name)
      await modelPage.fill('端点地址', GATEWAY)
      await modelPage.save()
      await expect(page.getByText('保存成功')).toBeVisible({ timeout: 20_000 })
      await modelPage.expectRow(name)

      const record = await api.model.findByName('rerank', name)
      expect(record).toBeTruthy()
      modelId = record!.modelId
      expect(record?.rerankPath).toBe('/rerank')

      // 画布的 ExternalModelReranker 有独立的「重排模型」下拉
      // （/system/rerank-models）；这里仍只验证「有启用的重排端点」这条发布前置条件，
      // 下拉切换的 UI 行为由前端单测（canvasNodeDrawers.spec.js）覆盖。
      flowId = await seedPublishedFlow(api, seeded, 'MODEL-04-FLOW')
      const published = await api.flow.getPublished(flowId)
      expect(published.nodeConfigDTOList.length).toBeGreaterThan(0)
    } finally {
      await cleanupSeed(api, seeded, flowId)
      await deleteModel(api, modelId)
    }
  })

  test('@p1 MODEL-05 连接测试成功与失败', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = modelName('MODEL-05')
    let modelId = ''
    try {
      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('大语言模型')
      await modelPage.openCreate()
      await modelPage.fill('模型名称', name)
      await modelPage.fill('端点地址', GATEWAY)

      await modelPage.runConnectionTest()
      // HEAD 998c46e 起，LLM 连接测试以**真实调用**为准（chatOk），不再只看端点可达。
      await expect(modelPage.testStatus()).resolves.toContain('模型调用成功')
      await expect(modelPage.dialog.locator('.model-test-result'))
        .toContainText('e2e-llm')

      await api.mockConfig({
        failChat: { status: 500, message: 'E2E chat failure' }
      })
      await modelPage.runConnectionTest()
      // 真实调用失败 → chatOk=false →「模型调用失败」（端点本身仍可达）。
      await expect.poll(() => modelPage.testStatus())
        .toContain('模型调用失败')

      // 失败本身在 API 结果里可读：ok=false + 真实调用失败原因
      await api.mockConfig({
        failChat: { status: 500, message: 'E2E chat failure' }
      })
      const failure = await api.model.testConfig({
        modelKind: 'llm',
        modelName: name,
        baseUrl: GATEWAY
      })
      expect(failure.ok).toBe(false)
      expect(String(failure.message)).toContain('E2E chat failure')

      await modelPage.save()
      await expect(page.getByText('保存成功')).toBeVisible({ timeout: 20_000 })
      modelId = (await api.model.findByName('llm', name))!.modelId
    } finally {
      await deleteModel(api, modelId)
    }
  })

  test('@p1 MODEL-06 编辑模型：类型不可改，路径可改', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = modelName('MODEL-06')
    let modelId = ''
    try {
      const created = await api.model.create({
        modelKind: 'llm',
        modelName: name,
        displayName: 'before',
        baseUrl: GATEWAY
      })
      modelId = created.modelId

      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('大语言模型')
      await modelPage.openEdit(name)

      // 类型是 radio 卡片；编辑态整组禁用（后端虽接受 modelKind，但改类型会让已有引用语义漂移）。
      const kindRadios = modelPage.formItem('模型类型').getByRole('radio')
      await expect(kindRadios.first()).toBeDisabled()
      await modelPage.fill('显示名称', 'after')
      await modelPage.fill('端点地址', 'http://fake-model-gateway:8000')
      await modelPage.toggleAdvanced()
      await modelPage.fill('模型请求路径', '/custom/chat/completions')
      await modelPage.save()
      await expect(page.getByText('保存成功')).toBeVisible({ timeout: 20_000 })

      const record = await api.model.get(modelId)
      expect(record.displayName).toBe('after')
      expect(record.baseUrl).toBe('http://fake-model-gateway:8000')
      expect(record.chatPath).toBe('/custom/chat/completions')
      expect(record.modelKind).toBe('llm')
      expect(record.modelName).toBe(name)
    } finally {
      await deleteModel(api, modelId)
    }
  })

  test('@p1 MODEL-07 删除模型与引用保护', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = modelName('MODEL-07')
    const referencedName = modelName('MODEL-07-REF')
    const kbName = resourceName('MODEL-07-KB')
    let modelId = ''
    let referencedId = ''
    let kbId = ''
    try {
      const created = await api.model.create({
        modelKind: 'llm',
        modelName: name,
        baseUrl: GATEWAY
      })
      modelId = created.modelId

      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('大语言模型')
      await modelPage.expectRow(name)
      await modelPage.deleteByName(name)
      await modelPage.expectNoRow(name)
      expect((await api.model.list('llm')).find(row => row.modelId === modelId)).toBeUndefined()
      modelId = ''

      const ref = await api.model.create({
        modelKind: 'embedding',
        modelName: referencedName,
        baseUrl: GATEWAY,
        dimension: 1024
      })
      referencedId = ref.modelId
      const kb = await api.createKb(kbName, referencedName)
      kbId = kb.id
      await expect(api.model.delete(referencedId)).rejects.toThrow(/同名|used|使用|引/)
    } finally {
      if (kbId) await api.cleanupKb(kbId)
      await deleteModel(api, referencedId)
      await deleteModel(api, modelId)
    }
  })

  test('@p1 MODEL-08 路径覆盖：models/embeddings/chat/rerank', async ({ api }) => {
    test.setTimeout(300_000)
    // 固定名：发布探测有 60s TTL 缓存，runId 变化会让上一次缓存的清单跟不上
    const llmName = 'e2e-path-llm'
    const embName = modelName('MODEL-08-EMB')
    const rerankName = modelName('MODEL-08-RR')
    // 重排只在候选 >1 时触发：造一篇能切出多个 chunk 的文档，否则 ExternalModelReranker
    // 会在 `len(knowledge_infos) <= 1` 处短路，永远测不到 rerank 路径。
    const marker = `E2E-MODEL-08-${Date.now()}`
    const kbName = resourceName('MODEL-08-KB')
    const models = await api.listEmbeddingModels()
    // 切分按**词**数（maxWordCount=512），中文段落按空格分出来的词很少；
    // 每段补 40 个英文 token，保证整篇超过 512 词、能切出多个 chunk。
    const paragraphs = Array.from({ length: 60 }, (_, index) => {
      const words = Array.from({ length: 40 }, (_, word) => `slice${index}x${word}`).join(' ')
      return `## 第 ${index + 1} 段\n\n${marker} ${words} 路径覆盖测试语料。`
    })
    const upload = await api.createKbWithMarkdown(
      kbName,
      models[0],
      `${kbName}.md`,
      ['# E2E 路径覆盖', '', ...paragraphs].join('\n\n')
    )
    const seeded = {
      ...upload,
      kbName,
      marker,
      embeddingModel: models[0]
    }
    let llmId = ''
    let embId = ''
    let rerankId = ''
    let flowId = ''
    let seededRerank: ModelRecord | undefined
    try {
      // 上一次异常退出可能留下同名模型
      const stale = await api.model.findByName('llm', llmName)
      if (stale) await api.model.delete(stale.modelId)
      const llm = await api.model.create({
        modelKind: 'llm',
        modelName: llmName,
        // 发布校验会真打 /models 核对“端点确实提供这个模型”；替身的清单是 e2e-llm
        apiModel: 'e2e-llm',
        baseUrl: 'http://fake-model-gateway:8000',
        modelsPath: '/custom/models',
        chatPath: '/custom/chat/completions'
      })
      llmId = llm.modelId
      const emb = await api.model.create({
        modelKind: 'embedding',
        modelName: embName,
        baseUrl: 'http://fake-model-gateway:8000',
        embeddingsPath: '/custom/embeddings',
        dimension: 1024
      })
      embId = emb.modelId
      const rerank = await api.model.create({
        modelKind: 'rerank',
        modelName: rerankName,
        apiModel: 'custom-reranker',
        baseUrl: 'http://fake-model-gateway:8000',
        rerankPath: '/custom/rerank',
        isDefault: true
      })
      rerankId = rerank.modelId

      // 1) modelsPath
      await api.mockReset()
      const llmProbe = await api.model.testConfig({
        modelKind: 'llm',
        modelName: llmName,
        baseUrl: 'http://fake-model-gateway:8000',
        modelsPath: '/custom/models'
      })
      expect(llmProbe.ok).toBe(true)
      let requests = await api.mockRequests()
      expect(requests.some(item => item.path === '/custom/models')).toBe(true)

      // 2) embeddingsPath + 实测维度
      await api.mockReset()
      const embProbe = await api.model.testConfig({
        modelKind: 'embedding',
        modelName: embName,
        baseUrl: 'http://fake-model-gateway:8000',
        embeddingsPath: '/custom/embeddings',
        dimension: 1024
      })
      expect(embProbe.dimension).toBe(1024)
      requests = await api.mockRequests()
      expect(requests.some(item => item.path === '/custom/embeddings')).toBe(true)

      // 3/4) chatPath + rerankPath：改一条真实编排，让生成与重排都走覆盖路径
      // 发布探测有 60s TTL 缓存：必须在 seedPublishedFlow 之前把自定义模型名补进清单，
      // 否则首次发布缓存下来的是固定清单，后续 publish 一直拿旧值。
      await api.mockConfig({ extraModels: [llmName] })
      seededRerank = await api.model.findByName('rerank', 'e2e-reranker')
      if (seededRerank) {
        await api.model.update(seededRerank.modelId, { isDefault: false })
      }
      flowId = await seedPublishedFlow(api, seeded, 'MODEL-08-FLOW')
      const config = await api.flow.getConfig(flowId)
      for (const node of config.nodeConfigDTOList) {
        rewriteLlmFields(node, llmName)
        // 检索阈值 0.3 会把哈希替身下只命中部分词的切片全过滤掉；重排需要 >1 个候选。
        lowerScoreFields(node)
      }
      const postRetriever = config.nodeConfigDTOList.find(node =>
        String(node.shape || node.componentType) === 'POST_RETRIEVER'
      ) as Record<string, any> | undefined
      if (postRetriever) {
        const variables = (postRetriever.variables || {}) as Record<string, any>
        variables.postretriever = [{
          package: 'core.rag.post_retriever.external_model_reranker',
          operator: 'ExternalModelReranker',
          kwargs: { top_n: 5, score: 0.01 }
        }]
        postRetriever.variables = variables
        const data = (postRetriever.data || {}) as Record<string, any>
        data.variables = variables
        postRetriever.data = data
      }
      await api.flow.saveConfig(flowId, config)
      await api.flow.publish(flowId)
      await api.flow.waitForPublished(flowId)

      const publishedConfig = await api.flow.getPublished(flowId)
      expect(JSON.stringify(publishedConfig)).toContain('external_model_reranker')

      const chunkPage = await api.kb.chunks(seeded.kbId)
      expect(chunkPage.total).toBeGreaterThan(1)

      const hits = await api.retrieve({
        question: `路径覆盖测试 ${seeded.marker}`,
        kbId: seeded.kbId,
        topK: 15
      })
      const hitCount = hits.reduce((total, group) => total + (group.docs?.length || 0), 0)
      expect(hitCount).toBeGreaterThan(1)

      await api.mockReset()
      await api.flow.query({
        question: `路径覆盖测试 ${seeded.marker}`,
        workFlowId: flowId
      })
      await expect.poll(async () => {
        const rows = await api.mockRequests()
        return rows.map(item => item.path)
      }, { timeout: 30_000 }).toEqual(
        expect.arrayContaining(['/custom/chat/completions', '/custom/rerank'])
      )
    } finally {
      await cleanupSeed(api, seeded, flowId)
      await deleteModel(api, rerankId)
      if (seededRerank) {
        try { await api.model.update(seededRerank.modelId, { isDefault: true }) } catch { /* best effort */ }
      }
      await deleteModel(api, embId)
      await deleteModel(api, llmId)
    }
  })

  test('@p1 MODEL-09 密钥不回显', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = modelName('MODEL-09')
    const secret = 'sk-e2e-secret-1234'
    let modelId = ''
    try {
      const created = await api.model.create({
        modelKind: 'llm',
        modelName: name,
        baseUrl: GATEWAY,
        apiKey: secret
      })
      modelId = created.modelId

      const listed = (await api.model.list('llm')).find(row => row.modelId === modelId)!
      expect(JSON.stringify(listed)).not.toContain(secret)
      expect(String(listed.apiKeyMasked)).toContain('1234')

      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('大语言模型')
      await modelPage.expectRow(name)
      const rowText = await modelPage.rowByName(name).first().innerText()
      expect(rowText).not.toContain(secret)
      expect(rowText).toContain('1234')

      await modelPage.openEdit(name)
      const keyInput = modelPage.formItem('API 密钥').locator('input[type="password"]')
      await expect(keyInput).toHaveValue('')
      // 0.1.x 起编辑弹窗不回显密钥的任何片段，只提示留空保留。
      await expect(keyInput).toHaveAttribute('placeholder', '留空保留原密钥')
      await modelPage.closeDialog()
    } finally {
      await deleteModel(api, modelId)
    }
  })

  test('@p2 MODEL-10 非法 URL 与重复名称', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = modelName('MODEL-10')
    let modelId = ''
    try {
      const created = await api.model.create({
        modelKind: 'llm',
        modelName: name,
        baseUrl: GATEWAY
      })
      modelId = created.modelId

      const modelPage = new ModelPage(page)
      await modelPage.goto()
      await modelPage.selectTab('大语言模型')
      await modelPage.openCreate()
      await modelPage.fill('模型名称', name)
      await modelPage.fill('端点地址', GATEWAY)
      await modelPage.save()
      await expect(page.getByText(/该类型中已存在此模型名称/).first()).toBeVisible({
        timeout: 20_000
      })
      await expect(modelPage.dialog).toBeVisible()
      await modelPage.closeDialog()
    } finally {
      await deleteModel(api, modelId)
    }
  })
})

function lowerScoreFields (value: unknown): void {
  if (!value || typeof value !== 'object') return
  if (Array.isArray(value)) {
    for (const item of value) lowerScoreFields(item)
    return
  }
  const record = value as Record<string, unknown>
  if (typeof record.score === 'number') record.score = 0
  for (const child of Object.values(record)) lowerScoreFields(child)
}

/** 递归把 flow 节点里所有空的 `llm` 字段指向指定模型（画布/模板用空串表示默认）。 */
function rewriteLlmFields (value: unknown, llmName: string): void {
  if (!value || typeof value !== 'object') return
  if (Array.isArray(value)) {
    for (const item of value) rewriteLlmFields(item, llmName)
    return
  }
  const record = value as Record<string, unknown>
  if (record.llm === '') record.llm = llmName
  for (const child of Object.values(record)) rewriteLlmFields(child, llmName)
}
