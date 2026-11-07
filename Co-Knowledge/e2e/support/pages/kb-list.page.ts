import { expect } from '@playwright/test'
import { BasePage } from './base.page'
import { confirmDeletion } from './delete-confirm.page'

/** 文档知识库列表页（`#/knowledge`）。 */
export class KbListPage extends BasePage {
  readonly root = this.page.locator('.knowledge-page')
  readonly createButton = this.root.getByRole('button', { name: '新建知识库', exact: true })
  readonly searchInput = this.root.getByPlaceholder(/搜索知识库名称/)
  readonly pagination = this.root.locator('.el-pagination').first()
  // 表头之外的数据行：每一行都有可点击的知识库名称链接；空态行只有 .empty-row。
  readonly rows = this.root.locator('tbody tr').filter({ has: this.page.locator('.entity-title') })

  async goto (): Promise<void> {
    await this.gotoHash('/#/knowledge')
    await this.expectLoaded()
  }

  async expectLoaded (): Promise<void> {
    await expect(this.root).toBeVisible()
    await expect(this.pagination).toBeVisible()
    await expect(this.searchInput).toBeVisible()
  }

  rowByName (name: string) {
    return this.rows.filter({ hasText: name })
  }

  async search (name: string): Promise<void> {
    await this.searchInput.fill(name)
  }

  async expectRow (name: string): Promise<void> {
    await expect(this.rowByName(name).first()).toBeVisible()
  }

  async expectNoRows (): Promise<void> {
    await expect(this.root.locator('.empty-row')).toBeVisible()
  }

  async openDetail (name: string): Promise<void> {
    await this.rowByName(name).first().locator('.entity-title').click()
  }

  async openMore (name: string): Promise<void> {
    await this.rowByName(name).first().getByRole('button', { name: /操作$/ }).click()
  }

  async clickMoreAction (name: string, action: '重命名' | '删除'): Promise<void> {
    await this.openMore(name)
    await this.page.getByRole('menuitem', { name: action }).click()
  }

  async confirmDangerDelete (): Promise<void> {
    await confirmDeletion(this.page)
  }

  async deleteByName (name: string): Promise<void> {
    await this.clickMoreAction(name, '删除')
    await this.confirmDangerDelete()
  }
}
