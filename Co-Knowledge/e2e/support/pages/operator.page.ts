import { expect } from '@playwright/test'
import { BasePage } from './base.page'

/** 自定义算子页（`#/operators`）。 */
export class OperatorPage extends BasePage {
  readonly root = this.page.locator('.operators-page')
  readonly tabs = this.root.getByRole('tab')
  readonly importButton = this.root.getByRole('button', { name: '导入算子文件' })
  readonly rows = this.root.locator('.operator-table tbody tr').filter({ has: this.page.locator('.entity-title') })

  async goto (): Promise<void> {
    await this.gotoHash('/#/operators')
    await expect(this.root).toBeVisible()
    await expect(this.importButton).toBeVisible()
  }
}
