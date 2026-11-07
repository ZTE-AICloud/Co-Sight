import { test, expect, resourceName } from '../../support/fixtures/test'
import { FlowListPage } from '../../support/pages/flow-list.page'
import { cleanupSeed, seedKbWithMarkdown } from '../../support/fixtures/seed'

test.describe('检索编排', () => {
  test('@fast @p0 FLOW-07 发布后在列表中显示已发布', async ({ page, api }) => {
    test.setTimeout(180_000)
    const seeded = await seedKbWithMarkdown(api, 'FLOW-07-KB')
    let workFlowId = ''
    try {
      const flowName = resourceName('FLOW-07')
      workFlowId = `RAG_Workflow_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6)}`
      await api.createWorkflow({
        name: flowName,
        workFlowId,
        template: 'Blended',
        knowledgeType: 'knowledgeBase',
        boundInfo: {
          running: [{
            name: seeded.kbName,
            tableName: `doc_${seeded.kbId}`,
            embeddingModel: seeded.embeddingModel,
            type: 'document'
          }]
        }
      })

      const flowPage = new FlowListPage(page)
      await flowPage.goto()
      const row = flowPage.rowByName(flowName)
      await expect(row).toBeVisible()
      await expect(row).toContainText('未发布')

      const publishResponse = page.waitForResponse(response =>
        response.url().includes(`/workflows/${encodeURIComponent(workFlowId)}/publication`) &&
        response.request().method() === 'POST'
      )
      await flowPage.publish(flowName)
      // 发布前有「下游 Agent 与对话测试即可使用」确认框
      const box = page.locator('.el-message-box')
      if (await box.isVisible().catch(() => false)) {
        await box.getByRole('button', { name: '确定', exact: true }).click()
      }
      const response = await publishResponse
      expect(response.ok()).toBeTruthy()

      await expect(flowPage.rowByName(flowName)).toContainText('已发布', { timeout: 15_000 })
      await api.waitForWorkflowPublished(workFlowId)
    } finally {
      await cleanupSeed(api, seeded, workFlowId)
    }
  })
})
