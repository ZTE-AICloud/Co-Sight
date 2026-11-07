import { expect } from '@playwright/test'
import { BasePage } from './base.page'

/** 检索编排画布（`#/flow/detail/:appId`）。 */
export class FlowCanvasPage extends BasePage {
  readonly canvas = this.page.locator('#advancedFLow')
  readonly saveButton = this.page.getByRole('button', { name: '保存', exact: true })
  readonly flowName = this.page.locator('.workspace-heading h1')
  readonly libraryButton = this.page.getByRole('button', { name: '添加节点', exact: true })
  readonly libraryDrawer = this.page.locator('.flow-library-drawer')

  async goto (appId: string): Promise<void> {
    await this.gotoHash(`/#/flow/detail/${appId}`)
    await expect(this.canvas).toBeVisible({ timeout: 30_000 })
  }

  async nodeCount (): Promise<number> {
    return this.page.locator('#advancedFLow g.x6-node').count()
  }

  /** 画布容器可见 ≠ X6 节点已渲染；等节点真正出现，别立刻数 DOM。 */
  async expectNodesRendered (minimum = 1): Promise<void> {
    await expect.poll(() => this.nodeCount(), {
      timeout: 30_000,
      intervals: [200, 500, 1_000]
    }).toBeGreaterThanOrEqual(minimum)
  }

  async expectNoLeftNav (): Promise<void> {
    await expect(this.page.locator('.sidebar')).toHaveCount(0)
  }

  async save (): Promise<void> {
    const response = this.page.waitForResponse(item =>
      item.url().includes('/api/co-knowledge/v1/workflows/') &&
      item.url().includes('/flow') &&
      item.request().method() === 'PUT'
    )
    await this.saveButton.click()
    // preCheck 走警告时会弹二次确认；E2E 的模型不是 reasoning 模型，通常直接保存。
    const confirm = this.page.locator('.el-message-box')
    if (await confirm.isVisible().catch(() => false)) {
      await confirm.getByRole('button', { name: '是', exact: true }).click()
    }
    const saved = await response
    expect(saved.ok()).toBeTruthy()
    await expect(this.saveButton).toBeEnabled({ timeout: 30_000 })
  }

  /**
   * 通过「添加节点」抽屉新增一个节点。
   * 0.1.x 画布已从 X6 stencil 拖拽改为抽屉点选；新增后会自动打开节点配置抽屉，
   * 这里点「取消」回到画布，再确认节点数增加。
   */
  async addLibraryNode (label = '检索器'): Promise<number> {
    const before = await this.nodeCount()
    await this.libraryButton.click()
    await expect(this.libraryDrawer).toBeVisible()
    await this.libraryDrawer.locator('.module-option')
      .filter({ hasText: label })
      .first()
      .click()
    await expect(this.libraryDrawer).toBeHidden()
    const cancel = this.page.getByRole('button', { name: '取消', exact: true })
    if (await cancel.isVisible().catch(() => false)) {
      await cancel.click()
    }
    await expect.poll(() => this.nodeCount(), { timeout: 20_000 }).toBeGreaterThan(before)
    return this.nodeCount()
  }
}
