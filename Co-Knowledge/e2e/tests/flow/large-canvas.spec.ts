import { test, expect, resourceName } from '../../support/fixtures/test'
import { FlowCanvasPage } from '../../support/pages/flow-canvas.page'
import { cleanupSeed, seedKbWithMarkdown, seedPublishedFlow } from '../../support/fixtures/seed'

test.describe('大画布', () => {
  test('@p2 FLOW-20 20+ 节点仍可保存/发布且画布可交互', async ({ page, api }) => {
    test.setTimeout(300_000)
    const seeded = await seedKbWithMarkdown(api, 'FLOW-20-KB')
    let flowId = ''
    try {
      flowId = await seedPublishedFlow(api, seeded, 'FLOW-20')
      const config = await api.flow.getConfig(flowId)
      const template = config.nodeConfigDTOList.find(node => node.shape === 'QUERY') ||
        config.nodeConfigDTOList[0]
      expect(template).toBeTruthy()

      // 模板本身约 8 个节点，再克隆 16 个 QUERY 节点（无算子、无连线，不影响可运行性校验）
      for (let index = 0; index < 16; index += 1) {
        const clone = JSON.parse(JSON.stringify(template)) as Record<string, any>
        const unique = `e2e-${Date.now()}-${index}`
        clone.id = unique
        clone.nodeId = unique
        clone.label = `QUERY-${index}`
        clone.position = {
          x: 100 + (index % 4) * 220,
          y: 500 + Math.floor(index / 4) * 160
        }
        config.nodeConfigDTOList.push(clone)
      }
      expect(config.nodeConfigDTOList.length).toBeGreaterThanOrEqual(20)

      const saveStarted = Date.now()
      await api.flow.saveConfig(flowId, config)
      const saveMs = Date.now() - saveStarted
      expect(saveMs, `保存 20+ 节点耗时 ${saveMs}ms`).toBeLessThan(30_000)

      const publishStarted = Date.now()
      await api.flow.publish(flowId)
      await api.flow.waitForPublished(flowId)
      const publishMs = Date.now() - publishStarted
      expect(publishMs, `发布 20+ 节点耗时 ${publishMs}ms`).toBeLessThan(60_000)

      const canvas = new FlowCanvasPage(page)
      const navStarted = Date.now()
      await canvas.goto(flowId)
      const navMs = Date.now() - navStarted
      expect(navMs, `画布加载 ${navMs}ms`).toBeLessThan(30_000)
      await expect.poll(() => canvas.nodeCount(), { timeout: 20_000 }).toBeGreaterThanOrEqual(20)

      // 交互仍然可用：保存按钮可点、点击后网络请求返回成功
      await expect(canvas.saveButton).toBeEnabled({ timeout: 10_000 })
      await canvas.save()
      await expect(canvas.flowName).toBeVisible()
    } finally {
      await cleanupSeed(api, seeded, flowId)
    }
  })
})
