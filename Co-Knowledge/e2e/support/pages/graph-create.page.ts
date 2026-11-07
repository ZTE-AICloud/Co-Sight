import { expect } from '@playwright/test'
import { BasePage } from './base.page'

/** 新建图谱知识库页（`#/graph/create`）。 */
export class GraphCreatePage extends BasePage {
  readonly root = this.page.locator('.create-knowledge-graph-page')
  readonly nameInput = this.root.getByPlaceholder('请输入知识图谱名称')
  readonly descriptionInput = this.root.getByPlaceholder('请输入知识图谱描述')
  readonly uploadInput = this.root.locator('.upload-demo input[type="file"]')
  readonly buildButton = this.root.getByRole('button', { name: '构建知识图谱' })
  readonly fileRows = this.root.locator('.file-list-table .el-table__body tbody tr')

  async goto (): Promise<void> {
    await this.gotoHash('/#/graph/create')
    await expect(this.root).toBeVisible({ timeout: 30_000 })
  }

  async fillBasics (name: string, description = `E2E ${name}`): Promise<void> {
    await this.nameInput.fill(name)
    await this.descriptionInput.fill(description)
  }

  async uploadMarkdown (fileName: string, content: string): Promise<void> {
    await this.uploadInput.setInputFiles({
      name: fileName,
      mimeType: 'text/markdown',
      buffer: Buffer.from(content, 'utf8')
    })
    await expect(this.root.getByText(fileName)).toBeVisible({ timeout: 20_000 })
  }

  private configItem (label: string) {
    return this.root.locator('.config-form .el-form-item')
      .filter({ hasText: label })
      .first()
  }

  async selectConfig (label: string, optionText: string): Promise<void> {
    const item = this.configItem(label)
    await expect(item).toBeVisible({ timeout: 20_000 })
    await item.locator('.el-select').click()
    await this.page.locator('.el-select-dropdown__item:visible')
      .filter({ hasText: optionText })
      .first()
      .click()
  }

  async fillArg (label: string, value: string): Promise<void> {
    const item = this.configItem(label)
    await item.locator('input').fill(value)
  }

  async expectBuildEnabled (): Promise<void> {
    await expect(this.buildButton).toBeEnabled({ timeout: 20_000 })
  }

  async expectBuildDisabled (): Promise<void> {
    await expect(this.buildButton).toBeDisabled()
  }

  async build (): Promise<void> {
    await this.buildButton.click()
    await expect(this.page).toHaveURL(/#\/graph/, { timeout: 60_000 })
  }
}
