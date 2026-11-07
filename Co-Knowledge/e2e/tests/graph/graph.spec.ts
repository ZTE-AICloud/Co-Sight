import fs from 'node:fs'
import JSZip from 'jszip'
import { test, expect, resourceName } from '../../support/fixtures/test'
import { env } from '../../support/env'
import { GraphListPage } from '../../support/pages/graph-list.page'
import { GraphDetailPage } from '../../support/pages/graph-detail.page'
import { GraphCreatePage } from '../../support/pages/graph-create.page'
import {
  cleanupGraphExtract,
  findGraphKbByName,
  renameGraphZip,
  seedEmptyGraph,
  seedGraphByExtract,
  seedGraphByImport,
  seedGraphOperator,
  seedGraphSchema,
  uniqueGraphSchema
} from '../../support/fixtures/graph'

test.describe('知识图谱', () => {
  test.afterEach(async ({ api }) => {
    if (env.modelMode === 'live') return
    await api.mockReset().catch(() => undefined)
  })

  test('@p0 GRAPH-01 列表与模版子页签', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedGraphByImport(api, 'GRAPH-01')
    try {
      const list = new GraphListPage(page)
      await list.goto()
      await expect(list.root).toBeVisible()
      await list.search(seeded.name)
      await list.expectRow(seeded.name)

      await list.openTemplateTab()
      await expect(list.createTemplateButton).toBeVisible()
      await expect(list.templateRoot.getByRole('button', { name: '导入' })).toBeVisible()
      await list.openGraphTab()
      await list.expectRow(seeded.name)
    } finally {
      await api.graph.cleanup(seeded.kbId)
    }
  })

  test('@p0 GRAPH-02 新建图谱：校验、构建、文件入库', async ({ page, api }) => {
    test.setTimeout(300_000)
    const schema = await seedGraphSchema(api, 'GRAPH-02-SCHEMA')
    const operator = await seedGraphOperator(api, 'GRAPH-02')
    const name = resourceName('GRAPH-02')
    let kbId = ''
    try {
      const create = new GraphCreatePage(page)
      await create.goto()
      await expect(create.buildButton).toBeDisabled()

      await create.fillBasics(name)
      await create.uploadMarkdown('graph-source.md', '# E2E 图谱\n\nAlice 在 Acme 工作。\n')
      await create.selectConfig('Embedding模型', 'e2e-embedding')
      await create.selectConfig('知识图谱算子', operator.name)
      await create.selectConfig('知识图谱模版', String(schema.schema_name))
      await create.selectConfig('LLM模型', 'E2E LLM')
      await create.fillArg('其他可选参数', 'none')
      await create.expectBuildEnabled()
      await create.build()

      const list = new GraphListPage(page)
      await list.search(name)
      await list.expectRow(name)

      kbId = (await findGraphKbByName(api, name)).id
      await api.graph.waitForExtract(kbId)

      const detail = new GraphDetailPage(page)
      await detail.goto(kbId)
      await detail.openBasicInfo()
      await expect(detail.fileTable).toContainText('graph-source.md')
      await expect(detail.root).toContainText(name)
    } finally {
      if (kbId) await api.graph.cleanup(kbId)
      try { await api.operator.delete(operator.id) } catch { /* best effort */ }
      try { await api.graph.deleteSchema(String(schema.schema_id)) } catch { /* best effort */ }
    }
  })

  test('@p1 GRAPH-03 抽取文件状态与详情文件列表', async ({ page, api }) => {
    test.setTimeout(300_000)
    const seeded = await seedGraphByExtract(api, 'GRAPH-03', {
      fileName: 'graph-03-source.md'
    })
    try {
      const detail = new GraphDetailPage(page)
      await detail.goto(seeded.kbId)
      await detail.openBasicInfo()
      await expect(detail.fileTable).toContainText('graph-03-source.md')
      await expect(detail.fileTable.locator('tbody tr')).toHaveCount(1)
    } finally {
      await cleanupGraphExtract(api, seeded)
    }
  })

  test('@p1 GRAPH-04 自动抽取产生实体与关系', async ({ page, api }) => {
    test.setTimeout(300_000)
    await api.mockReset()
    const seeded = await seedGraphByExtract(api, 'GRAPH-04')
    try {
      const requests = await api.mockRequests()
      expect(requests.some(item => item.promptKind === 'graph')).toBe(true)
      expect(requests.filter(item => item.promptKind === 'graph').length).toBeGreaterThan(0)

      const result = await api.graph.query(seeded.kbId, { queryType: 'entity' })
      const entities = result.entities || []
      const edges = result.edges || []
      expect(entities.length).toBeGreaterThanOrEqual(3)
      expect(edges.length).toBeGreaterThanOrEqual(1)
      const names = entities.map(item => String(item.entity_name || ''))
      expect(names).toEqual(expect.arrayContaining(['Alice', 'Bob', 'Acme']))

      const detail = new GraphDetailPage(page)
      await detail.goto(seeded.kbId)
      await expect.poll(() => detail.statValue('节点总数')).toBe(String(entities.length))
      await expect.poll(() => detail.statValue('关系总数')).toBe(String(edges.length))
    } finally {
      await cleanupGraphExtract(api, seeded)
    }
  })

  test('@p1 GRAPH-05 可视化画布与缩放图例', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedGraphByImport(api, 'GRAPH-05')
    try {
      const detail = new GraphDetailPage(page)
      await detail.goto(seeded.kbId)
      await detail.expectCanvas()
      await expect.poll(() => detail.statValue('节点总数')).toBe('3')
      await expect.poll(() => detail.statValue('关系总数')).toBe('2')

      await detail.toggleLegend()
      await expect(detail.legend).toBeVisible()
      await expect(detail.legend).toContainText('Person')
      await expect(detail.legend).toContainText('Organization')

      await detail.root.locator('.zoom-select-btn').click()
      await detail.root.locator('.zoom-option-btn').filter({ hasText: '200%' }).click()
      await expect(detail.root.locator('.zoom-select-btn')).toHaveText('200%')
      await detail.root.locator('.zoom-btn img[alt="reset"]').click()
      await expect(detail.root.locator('.zoom-select-btn')).toHaveText('100%')
    } finally {
      await api.graph.cleanup(seeded.kbId)
    }
  })

  test('@p1 GRAPH-06 实体/关系/子图查询', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedGraphByImport(api, 'GRAPH-06')
    try {
      const personQuery = await api.graph.query(seeded.kbId, {
        queryType: 'entity',
        filters: [{ entity_type: ['Person'], properties: {} }]
      })
      expect(personQuery.entities?.length).toBe(2)
      expect((personQuery.entities || []).every(item => item.entity_type === 'Person')).toBe(true)

      const relationQuery = await api.graph.query(seeded.kbId, { queryType: 'edge' })
      expect((relationQuery.edges || []).length).toBe(2)

      const subgraphQuery = await api.graph.query(seeded.kbId, {
        queryType: 'sub_graph',
        limit: 50,
        depth: 2
      })
      expect((subgraphQuery.entities || []).length).toBeGreaterThanOrEqual(3)

      const detail = new GraphDetailPage(page)
      await detail.goto(seeded.kbId)
      await detail.selectQueryType('关系查询')
      await detail.runQuery()
      await expect(page.getByText(/成功加载知识图谱数据/).first()).toBeVisible({
        timeout: 30_000
      })
      await expect.poll(() => detail.statValue('关系总数')).toBe('2')
    } finally {
      await api.graph.cleanup(seeded.kbId)
    }
  })

  test('@p1 GRAPH-07 实体/边 CRUD 与查询同步', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedGraphByImport(api, 'GRAPH-07')
    try {
      await api.graph.createEntity(seeded.kbId, 'Person_carol', 'Person', {
        name: 'Carol',
        age: 33
      })
      let result = await findEntity(api, seeded.kbId, 'Person_carol')
      expect(result?.properties).toMatchObject({ name: 'Carol', age: 33 })

      await api.graph.updateEntity(seeded.kbId, 'Person_carol', 'Person', {
        name: 'Carol',
        age: 34
      })
      result = await findEntity(api, seeded.kbId, 'Person_carol')
      expect(result?.properties).toMatchObject({ name: 'Carol', age: 34 })

      await api.graph.createEntity(seeded.kbId, 'Person_dave', 'Person', {
        name: 'Dave',
        age: 40
      })
      await api.graph.createEdge(
        seeded.kbId, 'Knows_carol-bob', 'Knows', 'Person_carol', 'Person_dave',
        { since: '2024-01-01' }
      )
      let edge = await findEdge(api, seeded.kbId, 'Knows_carol-bob')
      expect(edge?.properties).toMatchObject({ since: '2024-01-01 00:00:00' })

      await api.graph.updateEdge(seeded.kbId, 'Knows_carol-bob', 'Knows', {
        since: '2025-05-05'
      })
      edge = await findEdge(api, seeded.kbId, 'Knows_carol-bob')
      expect(edge?.properties).toMatchObject({ since: '2025-05-05 00:00:00' })

      await api.graph.deleteEdge(seeded.kbId, 'Knows_carol-bob', 'Knows')
      expect(await findEdge(api, seeded.kbId, 'Knows_carol-bob')).toBeUndefined()

      await api.graph.deleteEntity(seeded.kbId, 'Person_carol', 'Person')
      await api.graph.deleteEntity(seeded.kbId, 'Person_dave', 'Person')
      expect(await findEntity(api, seeded.kbId, 'Person_carol')).toBeUndefined()
      expect(await findEntity(api, seeded.kbId, 'Person_dave')).toBeUndefined()

      const detail = new GraphDetailPage(page)
      await detail.goto(seeded.kbId)
      await expect.poll(() => detail.statValue('节点总数')).toBe('3')
    } finally {
      await api.graph.cleanup(seeded.kbId)
    }
  })

  test('@p1 GRAPH-08 模版设计器创建/保存/导出/再导入', async ({ page, api }) => {
    test.setTimeout(300_000)
    const schema = uniqueGraphSchema('GRAPH-08')
    const name = String(schema.schema_name)
    const description = 'E2E 模版设计器'
    try {
      const list = new GraphListPage(page)
      await list.goto()
      await list.openTemplateTab()
      await list.createTemplateButton.click()

      const dialog = page.locator('.el-dialog').filter({ hasText: '新建图谱模版' })
      await expect(dialog).toBeVisible()
      await dialog.locator('input').first().fill(name)
      await dialog.locator('textarea').fill(description)
      await dialog.getByRole('button', { name: '新建', exact: true }).click()

      await expect(page).toHaveURL(/createTemplate\/new/, { timeout: 30_000 })
      const designer = page.locator('.graph-template-designer')
      await expect(designer).toBeVisible({ timeout: 30_000 })

      await designer.getByRole('button', { name: '增加实体' }).click()
      // “增加实体”只往画布加节点，不会自动选中（addNode 里主动 unselect）；
      // 必须点一下画布上的节点才会 emit node-select → 打开属性抽屉。
      const node = designer.locator('g.x6-node').last()
      await expect(node).toBeVisible({ timeout: 20_000 })
      await node.dblclick()
      const drawer = page.locator('.el-drawer').filter({ hasText: '实体配置' })
      await expect(drawer).toBeVisible({ timeout: 20_000 })
      await drawer.getByPlaceholder('请输入实体类名').fill('Person')
      await drawer.getByPlaceholder('请输入实体的描述信息').fill('E2E 人物')
      await drawer.getByPlaceholder('请输入属性名称').fill('name')
      await drawer.getByPlaceholder('请输入属性的描述信息').fill('姓名')
      // 实体必须至少有一个主键属性，否则保存被后端 0005 拒绝。
      await drawer.locator('.el-radio').filter({ hasText: '是' }).first().click()
      await drawer.getByRole('button', { name: '确定', exact: true }).click()
      await expect(drawer).toBeHidden({ timeout: 20_000 })

      await designer.getByRole('button', { name: '保存', exact: true }).click()
      await expect(page.getByText('图谱模板创建成功')).toBeVisible({ timeout: 30_000 })
      await expect(page).toHaveURL(/subTab=knowledgeGraphTemplate/, { timeout: 30_000 })
      await expect(list.templateRoot).toBeVisible({ timeout: 30_000 })
      await expect(list.templateRoot.getByText(name).first()).toBeVisible({
        timeout: 30_000
      })

      const exportedPath = await list.exportTemplate(name)
      const exported = fs.readFileSync(exportedPath)
      const zip = await JSZip.loadAsync(exported)
      const entries = Object.keys(zip.files)
      expect(entries.some(entry => entry.endsWith('.json'))).toBe(true)
      const schemaEntry = entries.find(entry => entry.endsWith('schema.json')) || entries.find(entry => entry.endsWith('.json'))!
      const exportedSchema = JSON.parse(await zip.file(schemaEntry)!.async('string'))
      expect(String(exportedSchema.schema_name || '')).toBe(name)

      // 原样再导入会撞名称/ID（后端 0005 “模板名称或模板ID已存在”）；导出包是
      // 可再导入格式，换个 schema_id/schema_name 后导入即可验证往返。
      const reimportId = `schema_reimport_${Date.now().toString(36)}`
      const reimportName = `E2Ereimport${Date.now().toString(36)}`
      exportedSchema.schema_id = reimportId
      exportedSchema.schema_name = reimportName
      const reimportZip = new JSZip()
      reimportZip.file('schema.json', JSON.stringify(exportedSchema, null, 2))
      await list.templateRoot.locator('input[type="file"]').setInputFiles({
        name: 'template-reimport.zip',
        mimeType: 'application/zip',
        buffer: await reimportZip.generateAsync({ type: 'nodebuffer' })
      })
      await expect(page.getByText(/导入成功/).first()).toBeVisible({ timeout: 30_000 })
      await expect(list.templateRoot.getByText(reimportName).first()).toBeVisible({
        timeout: 30_000
      })
    } finally {
      const rows = await api.graph.listSchemas()
      // 设计器保存时自己生成 schema_id（UUID），不是 fixture 里预造的 id；
      // 按名称回收原始模版 + 再导入变体，否则每次运行都会泄漏一条。
      const targets = new Set<string>()
      for (const row of rows) {
        const rowName = String(row.schemaName || '')
        const rowId = String(row.schemaId || '')
        if (rowId === String(schema.schema_id) || rowName === name || rowName.startsWith('E2Ereimport')) {
          if (rowId) targets.add(rowId)
        }
      }
      for (const id of targets) {
        try { await api.graph.deleteSchema(id) } catch { /* best effort */ }
      }
    }
  })

  test('@p1 GRAPH-09 图谱导出后可再导入', async ({ api }) => {
    test.setTimeout(240_000)
    const source = await seedGraphByImport(api, 'GRAPH-09-SRC')
    let reimportId = ''
    let reimportName = ''
    try {
      const exported = await api.graph.exportZip(source.kbId)
      expect(exported.subarray(0, 2).toString()).toBe('PK')
      const exportedZip = await JSZip.loadAsync(exported)
      expect(Object.keys(exportedZip.files)).toEqual(
        expect.arrayContaining(['desc.json', 'schema.json', 'entities.jsonl', 'edges.jsonl'])
      )

      reimportName = resourceName('GRAPH-09-DST')
      await api.graph.importGraph(await renameGraphZip(exported, reimportName))
      const row = await findGraphKbByName(api, reimportName)
      reimportId = row.id
      await api.graph.waitForGraphData(reimportId)
      // 导入是「先实体、后边」两段异步：waitForGraphData 只看实体数 > 0，
      // 那一刻边可能只落了一半。等状态 5（导入引擎在全部落图与建索引之后才回写）
      // 再取一次快照，否则断言的是实体刚出现时的半成品。
      await api.graph.waitForReady(reimportId)
      const data = await api.graph.query(reimportId, { queryType: 'entity' })
      expect((data.entities || []).length).toBe(3)
      expect((data.edges || []).length).toBe(2)

      const sourceData = await api.graph.query(source.kbId, { queryType: 'entity' })
      expect((sourceData.entities || []).length).toBe((data.entities || []).length)
    } finally {
      if (reimportId) await api.graph.cleanup(reimportId)
      await api.graph.cleanup(source.kbId)
    }
  })

  test('@p1 GRAPH-10 删除图谱库', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedGraphByImport(api, 'GRAPH-10')
    try {
      const list = new GraphListPage(page)
      await list.goto()
      await list.search(seeded.name)
      await list.expectRow(seeded.name)
      await list.deleteByName(seeded.name)
      await expect(list.rowByName(seeded.name)).toHaveCount(0, { timeout: 30_000 })

      const pageData = await api.graph.listKbs(seeded.name)
      expect((pageData?.items || []).find(row => row.id === seeded.kbId)).toBeUndefined()
      await expect(api.graph.query(seeded.kbId, { queryType: 'entity' }))
        .rejects.toThrow()
    } finally {
      await api.graph.cleanup(seeded.kbId)
    }
  })

  test('@p1 GRAPH-11 抽取失败可见且原因可读', async ({ api }) => {
    test.setTimeout(360_000)
    const schema = await seedGraphSchema(api, 'GRAPH-11-SCHEMA')
    const operator = await seedGraphOperator(api, 'GRAPH-11')
    const name = resourceName('GRAPH-11')
    let kbId = ''
    try {
      await api.mockConfig({
        failChat: { status: 500, message: 'E2E injected graph LLM failure' }
      })
      const models = await api.listEmbeddingModels()
      const created = await api.graph.extract(
        [{
          name: 'graph-11.md',
          mimeType: 'text/markdown',
          buffer: Buffer.from('# E2E 失败\n\nAlice 在 Acme。\n', 'utf8')
        }],
        {
          name,
          description: 'E2E graph failure',
          category: 10,
          props: { embeddingModel: models[0] || 'e2e-embedding' },
          operatorId: operator.id,
          coverFlag: true,
          schemaId: schema.schema_id,
          kwargs: { llm: 'e2e-llm' }
        }
      )
      kbId = String(created?.id || '')
      expect(kbId).toBeTruthy()

      await expect(api.graph.waitForExtract(kbId, 300_000)).rejects.toThrow(/status=103/)
      // failReason 由异步线程在状态置 103 之后紧接着写，列表可能是最终一致。
      await expect.poll(async () => {
        const pageData = await api.graph.listKbs(name)
        const row = (pageData?.items || []).find(item => item.id === kbId)
        return String(row?.failReason || '')
      }, { timeout: 30_000, intervals: [500, 1_000, 2_000] }).not.toBe('')
      const pageData = await api.graph.listKbs(name)
      const row = (pageData?.items || []).find(item => item.id === kbId)
      expect(Number(row?.status)).toBe(103)
    } finally {
      if (kbId) await api.graph.cleanup(kbId)
      try { await api.operator.delete(operator.id) } catch { /* best effort */ }
      try { await api.graph.deleteSchema(String(schema.schema_id)) } catch { /* best effort */ }
    }
  })

  test('@p2 GRAPH-12 空图谱空态不白屏', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedEmptyGraph(api, 'GRAPH-12')
    try {
      const detail = new GraphDetailPage(page)
      await detail.goto(seeded.kbId)
      await expect(detail.controls).toBeVisible()
      await expect(detail.root.locator('.graph-container')).toBeVisible()
      await expect(page.getByText('查询数据为空').first()).toBeVisible({ timeout: 30_000 })
      await expect.poll(() => detail.statValue('节点总数')).toBe('0')
      await expect.poll(() => detail.statValue('关系总数')).toBe('0')
    } finally {
      await api.graph.cleanup(seeded.kbId)
    }
  })
})

async function findEntity (
  api: import('../../support/api/api-client').ApiClient,
  kbId: string,
  entityId: string
): Promise<Record<string, unknown> | undefined> {
  const result = await api.graph.query(kbId, { queryType: 'entity', limit: 100 })
  return (result.entities || []).find(item => item.entity_id === entityId)
}

async function findEdge (
  api: import('../../support/api/api-client').ApiClient,
  kbId: string,
  edgeId: string
): Promise<Record<string, unknown> | undefined> {
  const result = await api.graph.query(kbId, { queryType: 'edge', limit: 100 })
  return (result.edges || []).find(item => item.edge_id === edgeId)
}
