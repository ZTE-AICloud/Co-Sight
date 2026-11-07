import { expect } from '@playwright/test'
import { BasePage } from './base.page'
import { confirmDeletion } from './delete-confirm.page'

/** 检索编排列表页（`#/flow`）。 */
export class FlowListPage extends BasePage {
  readonly root = this.page.locator('.flow-page')
  readonly createButton = this.root.getByRole('button', { name: '新建知识检索' })
  readonly rows = this.root.locator('.flow-table tbody tr')
    .filter({ has: this.page.locator('.entity-title') })

  async goto (): Promise<void> {
    await this.gotoHash('/#/flow')
    await expect(this.root).toBeVisible()
    await expect(this.createButton).toBeVisible()
  }

  rowByName (name: string) {
    return this.rows.filter({ hasText: name })
  }

  async openMore (name: string): Promise<void> {
    await this.rowByName(name).first().getByRole('button', { name: /操作$/ }).click()
  }

  async publish (name: string): Promise<void> {
    await this.openMore(name)
    await this.page.getByRole('menuitem', { name: '发布', exact: true }).click()
  }

  async clickMoreAction (name: string, action: '导出' | '修改' | '发布' | '重新发布' | '取消发布' | '删除'): Promise<void> {
    await this.openMore(name)
    await this.page.getByRole('menuitem', { name: action, exact: true }).click()
  }

  async deleteByName (name: string): Promise<void> {
    await this.clickMoreAction(name, '删除')
    await confirmDeletion(this.page)
  }

  async expectStatus (name: string, text: string): Promise<void> {
    await expect(this.rowByName(name).first()).toContainText(text)
  }
}
