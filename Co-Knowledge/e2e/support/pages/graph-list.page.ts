import { expect } from '@playwright/test'
import { BasePage } from './base.page'
import { confirmDeletion } from './delete-confirm.page'

/** 图谱知识库列表页（`#/graph`），含「知识图谱 / 知识图谱模版」子页签。 */
export class GraphListPage extends BasePage {
  readonly shell = this.page.locator('.knowledge-page')
  readonly root = this.page.locator('.graph-list-page')
  readonly templateRoot = this.page.locator('.knowledge-graph-template-page')
  readonly moreButton = this.root.getByRole('button', { name: '更多操作' })
  readonly createButton = this.root.getByRole('button', { name: '新建知识库', exact: true })
  readonly createTemplateButton = this.templateRoot.getByRole('button', { name: '新建图谱模版' })
  readonly searchInput = this.root.getByPlaceholder(/搜索知识库名称/)
  readonly pagination = this.shell.locator('.el-pagination:visible').first()
  readonly rows = this.root.locator('tbody tr').filter({ has: this.page.locator('.entity-title') })

  async goto (): Promise<void> {
    await this.gotoHash('/#/graph')
    await this.expectLoaded()
  }

  async expectLoaded (): Promise<void> {
    await expect(this.shell).toBeVisible()
    await expect(this.createButton).toBeVisible()
    await expect(this.pagination).toBeVisible()
  }

  async openTemplateTab (): Promise<void> {
    // 「知识图谱模版」入口已从「更多操作」菜单提到工具条。
    await this.root.getByRole('button', { name: '知识图谱模版', exact: true }).click()
    await expect(this.templateRoot).toBeVisible()
  }

  async openGraphTab (): Promise<void> {
    // 模版页顶部的返回链接（回到图谱列表）；它在 GraphTabs 里，不在模版组件根内。
    await this.page.locator('.kg-template-back button').click()
    await expect(this.root).toBeVisible()
  }

  async search (name: string): Promise<void> {
    await this.searchInput.fill(name)
  }

  rowByName (name: string) {
    return this.rows.filter({ hasText: name })
  }

  async expectRow (name: string): Promise<void> {
    await expect(this.rowByName(name).first()).toBeVisible({ timeout: 20_000 })
  }

  async openDetail (name: string): Promise<void> {
    await this.rowByName(name).first().locator('.entity-title').click()
  }

  async openMore (name: string): Promise<void> {
    await this.rowByName(name).first().getByRole('button', { name: /操作$/ }).click()
  }

  async clickMoreAction (name: string, action: '修改' | '导出图谱' | '删除'): Promise<void> {
    await this.openMore(name)
    await this.page.getByRole('menuitem', { name: action }).click()
  }

  async deleteByName (name: string): Promise<void> {
    await this.clickMoreAction(name, '删除')
    await this.confirmDangerDelete()
  }

  async confirmDangerDelete (): Promise<void> {
    await confirmDeletion(this.page)
  }

  /** 下载当前页某个模版的导出包，返回落盘路径。 */
  async exportTemplate (name: string): Promise<string> {
    const row = this.templateRoot.locator('tbody tr')
      .filter({ hasText: name })
      .first()
    const downloadPromise = this.page.waitForEvent('download')
    await row.getByRole('button', { name: '导出' }).click()
    const download = await downloadPromise
    const target = await download.path()
    if (!target) throw new Error('模版导出没有产生下载文件')
    return target
  }
}
