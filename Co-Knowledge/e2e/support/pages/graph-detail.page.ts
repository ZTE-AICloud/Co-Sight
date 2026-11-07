import { expect } from '@playwright/test'
import { BasePage } from './base.page'

/** 图谱详情页（`#/graph/detail/:id`）：可视化 + 基本信息。 */
export class GraphDetailPage extends BasePage {
  readonly root = this.page.locator('.knowledge-graph-detail-page')
  readonly canvas = this.root.locator('.graph-canvas-vis-core canvas')
  readonly controls = this.root.locator('.controls-wrapper')
  readonly stats = this.root.locator('.control-item--stat')
  readonly legend = this.root.locator('.legend')
  readonly basicTab = this.root.getByRole('tab', { name: '基本信息' })
  readonly fileTable = this.root.locator('.gi-table .list-table')

  async goto (kbId: string): Promise<void> {
    await this.gotoHash(`/#/graph/detail/${kbId}`)
    await expect(this.root).toBeVisible({ timeout: 30_000 })
    await expect(this.controls).toBeVisible({ timeout: 30_000 })
  }

  async expectCanvas (): Promise<void> {
    await expect(this.canvas).toBeVisible({ timeout: 30_000 })
  }

  async statValue (label: string): Promise<string> {
    const item = this.stats.filter({ hasText: label }).first()
    return (await item.locator('.value').innerText()).trim()
  }

  async toggleLegend (): Promise<void> {
    await this.root.locator('.zoom-btn img[alt="legend"]').click()
  }

  async selectQueryType (label: '实体查询' | '关系查询' | '子图/路径查询'): Promise<void> {
    // 查询类型收在「高级查询」抽屉里。
    const drawer = this.page.locator('.el-drawer.graph-advanced-drawer')
    if (!(await drawer.isVisible())) {
      await this.root.getByRole('button', { name: '高级查询' }).click()
    }
    await expect(drawer).toBeVisible()
    await drawer.locator('.advanced-query-type .el-select').click()
    await this.page.locator('.el-select-dropdown__item:visible')
      .filter({ hasText: label })
      .first()
      .click()
  }

  async runQuery (): Promise<void> {
    // 查询动作已收进「高级查询」抽屉的底部。
    const drawer = this.page.locator('.el-drawer.graph-advanced-drawer')
    await drawer.locator('.controls-drawer-footer .control-button').click()
  }

  async openBasicInfo (): Promise<void> {
    await this.basicTab.click()
    await expect(this.root.locator('.gi-files')).toBeVisible()
  }
}
