import { expect } from '@playwright/test'
import { BasePage } from './base.page'

/**
 * 左栏导航。
 *
 * 当前界面文案是中文（用例默认 `locale=zh-CN`）。若后续要跑英文，新增一份
 * label 映射即可；不要把中文文案散落到每个 spec。
 */
export class NavPage extends BasePage {
  readonly nav = this.page.getByRole('navigation', { name: '主导航' })

  async openDocKb (): Promise<void> {
    await this.openLink('文档知识库', '#/knowledge')
  }

  async openGraphKb (): Promise<void> {
    await this.openLink('图谱知识库', '#/graph')
  }

  async openFlow (): Promise<void> {
    await this.openLink('知识检索', '#/flow')
  }

  async openChat (): Promise<void> {
    await this.openLink('对话测试', '#/chat')
  }

  async openOperator (): Promise<void> {
    await this.openLink('自定义算子', '#/operators')
  }

  async openModel (): Promise<void> {
    await this.openLink('模型管理', '#/models')
  }

  async expectMenus (): Promise<void> {
    await expect(this.nav).toBeVisible()
    for (const name of ['文档知识库', '图谱知识库', '知识检索', '对话测试', '自定义算子', '模型管理']) {
      await expect(this.nav.getByRole('link', { name }).first()).toBeVisible()
    }
  }

  private async openLink (name: string, hash: string): Promise<void> {
    await this.nav.getByRole('link', { name }).first().click()
    await this.expectHash(hash)
  }
}
