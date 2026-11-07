import { test, expect, resourceName } from '../../support/fixtures/test'
import { ChatPage } from '../../support/pages/chat.page'
import { cleanupSeed, seedKbWithMarkdown, seedPublishedFlow } from '../../support/fixtures/seed'

test.describe('对话测试', () => {
  test('@fast @p0 CHAT-02 已发布工作流的流式问答', async ({ page, api }) => {
    test.setTimeout(240_000)
    const seeded = await seedKbWithMarkdown(api, 'CHAT-02-KB')
    let workFlowId = ''
    try {
      workFlowId = await seedPublishedFlow(api, seeded, 'CHAT-02')
      const flowName = resourceName('CHAT-02')

      if (process.env.E2E_MODEL_MODE !== 'live') {
        await api.mockReset()
        await api.mockConfig({ streamFrames: 8, delayMs: 40, answerMarker: 'E2E_MOCK_ANSWER' })
      }

      const chat = new ChatPage(page)
      await chat.goto()

      await expect(chat.workflowSelect).toBeEnabled({ timeout: 30_000 })
      await chat.workflowSelect.click()
      const option = page.locator('.el-select-dropdown__item').filter({ hasText: flowName }).first()
      await expect(option).toBeVisible()
      await option.click()

      await expect(chat.input).toBeEnabled()
      await chat.ask(`请回答：${seeded.marker}`)

      // 流式过程中应出现 pending/思考状态（替身有延迟；live 模式只断言最终结果）
      if (process.env.E2E_MODEL_MODE !== 'live') {
        await expect(
          chat.root.locator('.chat-pending, .chat-reasoning').first()
        ).toBeVisible({ timeout: 30_000 })
      }

      const answer = chat.root.locator('.message-line.assistant .assistant-bubble').last()
      await expect(answer).toBeVisible({ timeout: 120_000 })
      await expect(answer).not.toHaveClass(/assistant-bubble--error/)
      if (process.env.E2E_MODEL_MODE !== 'live') {
        await expect(answer).toContainText('E2E_MOCK_ANSWER', { timeout: 120_000 })
      } else {
        await expect(answer).not.toBeEmpty()
      }

      // 生成结束后 pending/停止按钮消失；发送按钮在输入框为空时本来就是 disabled，
      // 不能拿它当“生成完成”的判据。
      await expect(chat.root.locator('.chat-pending')).toHaveCount(0, {
        timeout: 120_000
      })
      await expect(chat.stopButton).toBeHidden({ timeout: 120_000 })
    } finally {
      await cleanupSeed(api, seeded, workFlowId)
    }
  })
})
