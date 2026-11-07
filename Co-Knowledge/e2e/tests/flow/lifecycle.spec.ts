import { test, expect, resourceName } from '../../support/fixtures/test'
import { FlowListPage } from '../../support/pages/flow-list.page'
import { FlowCanvasPage } from '../../support/pages/flow-canvas.page'
import { cleanupSeed, seedKbWithMarkdown } from '../../support/fixtures/seed'
import type { ApiClient } from '../../support/api/api-client'
import type { SeededKb } from '../../support/fixtures/seed'

async function createFlow (
  api: ApiClient,
  kb: SeededKb,
  name: string,
  template: 'Sequential' | 'Blended' | 'Conditional' = 'Blended'
): Promise<string> {
  const workFlowId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
  await api.flow.create({
    name,
    workFlowId,
    template,
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
  return workFlowId
}

async function seedFlow (
  api: ApiClient,
  caseId: string,
  options: { publish?: boolean; template?: 'Sequential' | 'Blended' | 'Conditional' } = {}
): Promise<{ kb: SeededKb; workFlowId: string; name: string }> {
  const kb = await seedKbWithMarkdown(api, `${caseId}-KB`)
  const name = resourceName(caseId)
  const workFlowId = await createFlow(api, kb, name, options.template || 'Blended')
  if (options.publish) {
    await api.flow.publish(workFlowId)
    await api.flow.waitForPublished(workFlowId)
  }
  return { kb, workFlowId, name }
}

async function cleanupFlow (
  api: ApiClient,
  seeded: { kb: SeededKb; workFlowId: string }
): Promise<void> {
  try { await api.flow.delete(seeded.workFlowId) } catch { /* best effort */ }
  await cleanupSeed(api, seeded.kb)
}

test.describe('检索编排生命周期', () => {
  test('@p0 FLOW-01 列表加载', async ({ page }) => {
    const flow = new FlowListPage(page)
    await flow.goto()
    await expect(flow.createButton).toBeVisible()
    await expect(page.locator('.flow-page table.list-table')).toBeVisible()
  })

  test('@p0 FLOW-02 通过 UI 新建工作流', async ({ page, api }) => {
    test.setTimeout(180_000)
    const kb = await seedKbWithMarkdown(api, 'FLOW-02-KB')
    const name = resourceName('FLOW-02')
    let workFlowId = ''
    try {
      const flow = new FlowListPage(page)
      await flow.goto()
      await flow.createButton.click()

      const dialog = page.getByRole('dialog').filter({ hasText: '新建知识检索' })
      await expect(dialog).toBeVisible({ timeout: 30_000 })
      await dialog.getByRole('textbox', { name: '检索名称' }).fill(name)
      await dialog.locator('.el-select__wrapper').click()
      await page.locator('.el-select-dropdown__item').filter({ hasText: kb.kbName }).first().click()
      // 多选下拉不会自动收起，点名称输入框把弹层关掉。
      await dialog.getByRole('textbox', { name: '检索名称' }).click()
      await dialog.getByRole('button', { name: '创建并编排' }).click()

      await expect(page).toHaveURL(/#\/flow\/detail\//, { timeout: 30_000 })
      workFlowId = decodeURIComponent(page.url().split('/flow/detail/')[1])
      const canvas = new FlowCanvasPage(page)
      await expect(canvas.canvas).toBeVisible({ timeout: 30_000 })
      await expect.poll(async () => canvas.nodeCount(), { timeout: 30_000 }).toBeGreaterThan(0)
    } finally {
      if (workFlowId) {
        try { await api.flow.delete(workFlowId) } catch { /* best effort */ }
      } else {
        const row = await api.flow.findByName(name)
        if (row) {
          workFlowId = row.workFlowId
          try { await api.flow.delete(workFlowId) } catch { /* best effort */ }
        }
      }
      await cleanupSeed(api, kb)
    }
  })

  test('@p0 FLOW-03 画布加载（节点/连线/标题）', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-03', { publish: true })
    try {
      const canvas = new FlowCanvasPage(page)
      await canvas.goto(seeded.workFlowId)
      // 画布容器先可见、节点后渲染；直接数 DOM 会偶发 0（已知 flake）。
      await canvas.expectNodesRendered()
      await expect(canvas.flowName).toContainText(seeded.name)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p0 FLOW-04 拖拽新增节点', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-04')
    try {
      const canvas = new FlowCanvasPage(page)
      await canvas.goto(seeded.workFlowId)
      await canvas.addLibraryNode('检索器')
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p0 FLOW-05 保存草稿', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-05')
    try {
      const canvas = new FlowCanvasPage(page)
      await canvas.goto(seeded.workFlowId)
      await canvas.save()
      const draft = await api.flow.getConfig(seeded.workFlowId)
      expect(Array.isArray(draft.nodeConfigDTOList)).toBe(true)
      expect(draft.nodeConfigDTOList.length).toBeGreaterThan(0)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p0 FLOW-06 保存后刷新还原节点', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedFlow(api, 'FLOW-06')
    try {
      const canvas = new FlowCanvasPage(page)
      await canvas.goto(seeded.workFlowId)
      const before = await canvas.nodeCount()
      await canvas.addLibraryNode('检索器')
      const afterDrag = await canvas.nodeCount()
      await canvas.save()
      await page.reload()
      await expect(canvas.canvas).toBeVisible({ timeout: 30_000 })
      // 刷新后画布壳先出现、X6 节点后渲染；直接数 DOM 会偶发 0（已知 flake）。
      await expect.poll(() => canvas.nodeCount(), {
        timeout: 30_000,
        intervals: [200, 500, 1_000]
      }).toBe(afterDrag)
      expect(afterDrag).toBeGreaterThan(before)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p0 FLOW-08 重新发布版本递增', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-08', { publish: true })
    try {
      const before = (await api.flow.getConfig(seeded.workFlowId)).version || 0
      const flow = new FlowListPage(page)
      await flow.goto()

      // 已发布工作流的行菜单同时给出「重新发布」与「取消发布」，
      // 不再需要先取消再发布（那样会短暂中断线上引用）。
      const response = page.waitForResponse(item =>
        item.url().includes(`/workflows/${encodeURIComponent(seeded.workFlowId)}/publication`) &&
        item.request().method() === 'POST'
      )
      await flow.clickMoreAction(seeded.name, '重新发布')
      const box = page.locator('.el-message-box')
      if (await box.isVisible().catch(() => false)) {
        await box.getByRole('button', { name: '确定', exact: true }).click()
      }
      await response
      await expect.poll(async () => {
        const draft = await api.flow.getConfig(seeded.workFlowId)
        return Number(draft.version || 0)
      }, { timeout: 15_000 }).toBeGreaterThan(before)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p0 FLOW-09 未发布工作流禁止执行', async ({ api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-09')
    try {
      let error: unknown
      try {
        await api.flow.query({
          question: '未发布工作流',
          workFlowId: seeded.workFlowId
        })
      } catch (caught) {
        error = caught
      }
      expect(error, '未发布工作流应返回明确业务错误').toBeTruthy()
      expect(String(error)).toMatch(/没有已发布|published|发布/i)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p0 FLOW-10 已发布工作流可执行', async ({ api }) => {
    test.setTimeout(180_000)
    const seeded = await seedFlow(api, 'FLOW-10', { publish: true })
    try {
      const result = await api.flow.query({
        question: `请回答：${seeded.kb.marker}`,
        workFlowId: seeded.workFlowId
      })
      const answer = String(result.answer || '')
      expect(answer.length).toBeGreaterThan(0)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p1 FLOW-11 删除工作流（验证码）', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-11')
    try {
      const flow = new FlowListPage(page)
      await flow.goto()
      await flow.deleteByName(seeded.name)
      await expect(flow.rowByName(seeded.name)).toHaveCount(0, { timeout: 20_000 })
      expect(await api.flow.findByName(seeded.name)).toBeUndefined()
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p1 FLOW-12 导出画布 JSON', async ({ api }) => {
    const seeded = await seedFlow(api, 'FLOW-12')
    try {
      const exported = await api.flow.exportStatus(seeded.workFlowId)
      expect(exported.status).toBe(200)
      expect(exported.contentType).toMatch(/octet-stream|json|application/i)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p1 FLOW-13 三种模板均可建流', async ({ api }) => {
    test.setTimeout(180_000)
    for (const template of ['Sequential', 'Blended', 'Conditional'] as const) {
      const seeded = await seedFlow(api, `FLOW13${template[0]}`, { template })
      try {
        const draft = await api.flow.getConfig(seeded.workFlowId)
        expect(draft.nodeConfigDTOList.length).toBeGreaterThan(0)
      } finally {
        await cleanupFlow(api, seeded)
      }
    }
  })

  test('@p1 FLOW-14 绑定多个知识库', async ({ api }) => {
    test.setTimeout(180_000)
    const first = await seedKbWithMarkdown(api, 'FLOW-14-A')
    const second = await seedKbWithMarkdown(api, 'FLOW-14-B')
    const name = resourceName('FLOW-14')
    const workFlowId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
    try {
      await api.flow.create({
        name,
        workFlowId,
        template: 'Blended',
        boundInfo: {
          running: [
            {
              name: first.kbName,
              tableName: `doc_${first.kbId}`,
              embeddingModel: first.embeddingModel,
              type: 'document'
            },
            {
              name: second.kbName,
              tableName: `doc_${second.kbId}`,
              embeddingModel: second.embeddingModel,
              type: 'document'
            }
          ]
        }
      })
      const draft = await api.flow.getConfig(workFlowId)
      const text = JSON.stringify(draft)
      expect(text).toContain(`doc_${first.kbId}`)
      expect(text).toContain(`doc_${second.kbId}`)
    } finally {
      try { await api.flow.delete(workFlowId) } catch { /* best effort */ }
      await cleanupSeed(api, first)
      await cleanupSeed(api, second)
    }
  })

  test('@p1 FLOW-15 preCheck 结构校验', async ({ api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-15')
    try {
      const draft = await api.flow.getConfig(seeded.workFlowId)
      const ok = await api.flow.precheck(seeded.workFlowId, draft)
      expect(ok.success).toBe(true)

      const broken = { ...draft, nodeConfigDTOList: [] }
      let error: unknown
      try {
        await api.flow.precheck(seeded.workFlowId, broken)
      } catch (caught) {
        error = caught
      }
      expect(error, '空画布应被结构校验拒绝').toBeTruthy()
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p1 FLOW-16 编辑工作流元信息', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-16')
    try {
      const nextName = `${seeded.name}-改`
      const flow = new FlowListPage(page)
      await flow.goto()
      await flow.clickMoreAction(seeded.name, '修改')
      const dialog = page.locator('.el-dialog').filter({ hasText: '修改' })
      await dialog.locator('.app-name-input input').fill(nextName)
      await dialog.getByRole('button', { name: '确定', exact: true }).click()
      await expect(flow.rowByName(nextName)).toBeVisible({ timeout: 20_000 })
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p1 FLOW-17 发布状态 0/1/2', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await seedFlow(api, 'FLOW-17')
    try {
      const flow = new FlowListPage(page)
      await flow.goto()
      await flow.expectStatus(seeded.name, '未发布')

      await api.flow.publish(seeded.workFlowId)
      await api.flow.waitForPublished(seeded.workFlowId)
      await page.reload()
      await flow.expectStatus(seeded.name, '已发布')

      const draft = await api.flow.getConfig(seeded.workFlowId)
      await api.flow.saveConfig(seeded.workFlowId, draft)
      await expect.poll(async () => {
        const row = await api.flow.findByName(seeded.name)
        return Number(row?.publishType)
      }, { timeout: 15_000 }).toBe(2)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  test('@p2 FLOW-18 全屏覆盖左栏与 Esc 退出', async ({ page, api }) => {
    const seeded = await seedFlow(api, 'FLOW-18')
    try {
      const canvas = new FlowCanvasPage(page)
      await canvas.goto(seeded.workFlowId)
      await page.getByRole('button', { name: '全屏查看', exact: true }).click()
      await expect(page.locator('.workspace-page')).toHaveClass(/is-flow-fullscreen/)
      // 固定层覆盖整屏：左上角命中的应是工作区，而不是左栏
      expect(await page.evaluate(() => !!document.elementFromPoint(40, 40)?.closest('.workspace-page'))).toBe(true)
      await page.keyboard.press('Escape')
      await expect(page.locator('.workspace-page')).not.toHaveClass(/is-flow-fullscreen/)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })

  // 后端只校验 workFlowId 唯一；重名由新建弹窗的 uniqueNameRule 在提交前拦下。
  test('@p2 FLOW-19 重名工作流', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedFlow(api, 'FLOW-19')
    try {
      const flow = new FlowListPage(page)
      await flow.goto()
      await flow.createButton.click()
      const dialog = page.getByRole('dialog').filter({ hasText: '新建知识检索' })
      await expect(dialog).toBeVisible({ timeout: 30_000 })
      await dialog.getByRole('textbox', { name: '检索名称' }).fill(seeded.name)
      await dialog.locator('.el-select__wrapper').click()
      await page.locator('.el-select-dropdown__item')
        .filter({ hasText: seeded.kb.kbName }).first().click()
      await dialog.getByRole('textbox', { name: '检索名称' }).click()
      await dialog.getByRole('button', { name: '创建并编排' }).click()

      await expect(page.getByText(/此名称已存在/).first()).toBeVisible({
        timeout: 20_000
      })
      await expect(page).toHaveURL(/#\/flow$/)
      const rows = await api.flow.findAll()
      expect(rows.filter(row => row.name === seeded.name)).toHaveLength(1)
    } finally {
      await cleanupFlow(api, seeded)
    }
  })
})
