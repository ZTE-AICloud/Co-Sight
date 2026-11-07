import { expect } from '@playwright/test'
import { BasePage } from './base.page'

/** 对话测试页（`#/chat`）。 */
export class ChatPage extends BasePage {
  readonly root = this.page.locator('.chat-page')
  readonly workflowSelect = this.root.locator('.chat-workflow-select')
  readonly input = this.root.locator('textarea')
  readonly sendButton = this.root.getByRole('button', { name: '发送' })
  readonly stopButton = this.root.getByRole('button', { name: '停止' })
  // 页面上有两个「新会话」：工具栏一个、历史会话标题栏一个（后者只在有会话时出现）。
  // 不限定作用域会触发 Playwright strict mode（CHAT-05/06 因此失败）。
  readonly newSessionButton = this.root.locator('.chat-toolbar')
    .getByRole('button', { name: '新会话' })
  readonly messages = this.root.locator('.message-line')
  /** 知识库依据：流式中是 `--live` 摘要，结束后是 `<details>` 面板 */
  readonly evidence = this.root.locator('.chat-evidence')
  readonly evidenceItems = this.root.locator('.chat-evidence__item')

  /** 右侧检索链路面板的单个阶段（stable hook，避免依赖 i18n 文案） */
  traceStep (stage: 'understanding' | 'retrieval' | 'keyword' | 'rerank' | 'generate') {
    return this.root.locator(`.trace-step[data-stage="${stage}"]`)
  }

  async goto (): Promise<void> {
    await this.gotoHash('/#/chat')
    await expect(this.root).toBeVisible()
  }

  async selectWorkflow (name: string): Promise<void> {
    await expect(this.workflowSelect).toBeEnabled({ timeout: 30_000 })
    await this.workflowSelect.click()
    const option = this.page.locator('.el-select-dropdown__item')
      .filter({ hasText: name })
      .first()
    await expect(option).toBeVisible()
    await option.click()
  }

  async ask (question: string): Promise<void> {
    await this.input.fill(question)
    await this.sendButton.click()
  }

  async waitForIdle (timeout = 180_000): Promise<void> {
    await expect(this.stopButton).toBeHidden({ timeout })
  }

  async expectAnswer (text: string): Promise<void> {
    await expect(this.root.locator('.assistant-bubble').filter({ hasText: text }).first())
      .toBeVisible()
  }

  assistantBubbles () {
    return this.root.locator('.message-line.assistant .assistant-bubble')
  }

  async newSession (): Promise<void> {
    await this.newSessionButton.click()
  }
}
