import { expect } from '@playwright/test'
import { BasePage } from './base.page'
import { confirmDeletion } from './delete-confirm.page'

/** 模型管理页（`#/models`）。 */
export class ModelPage extends BasePage {
  readonly root = this.page.locator('.models-page')
  readonly tabs = this.root.getByRole('tab')
  readonly createButton = this.root.getByRole('button', { name: '新增模型' })
  readonly rows = this.root.locator('.models-table tbody tr').filter({ has: this.page.locator('.entity-title') })
  readonly searchInput = this.root.getByPlaceholder('搜索模型名称 / 端点地址')
  readonly dialog = this.page.locator('.el-dialog:visible').last()

  async goto (): Promise<void> {
    await this.gotoHash('/#/models')
    await this.expectLoaded()
  }

  async expectLoaded (): Promise<void> {
    await expect(this.root).toBeVisible()
    await expect(this.tabs).toHaveCount(3)
    await expect(this.createButton).toBeVisible()
  }

  async selectTab (name: string): Promise<void> {
    await this.tabs.filter({ hasText: name }).click()
  }

  rowByName (name: string) {
    return this.rows.filter({ hasText: name })
  }

  async expectRow (name: string): Promise<void> {
    await expect(this.rowByName(name).first()).toBeVisible({ timeout: 20_000 })
  }

  async expectNoRow (name: string): Promise<void> {
    await expect(this.rowByName(name)).toHaveCount(0, { timeout: 20_000 })
  }

  async openCreate (): Promise<void> {
    await this.createButton.click()
    await expect(this.dialog).toBeVisible()
  }

  async openEdit (name: string): Promise<void> {
    await this.rowByName(name).first().getByRole('button', { name: '编辑' }).click()
    await expect(this.dialog).toBeVisible()
  }

  formItem (label: string) {
    // 直接用表单项的文本匹配：`filter({has: dialog.locator(...)})` 里的内层 locator
    // 自带 root，Playwright 不会把它当“相对外层元素”的后代查询（实测永不命中）。
    return this.dialog.locator('.el-form-item').filter({ hasText: label }).first()
  }

  async fill (label: string, value: string): Promise<void> {
    await this.formItem(label).locator('input, textarea').first().fill(value)
  }

  async selectKind (label: '大语言模型' | '向量模型' | '重排模型'): Promise<void> {
    // 0.1.x 起模型类型是 radio 卡片，不再是下拉。
    await this.formItem('模型类型').getByRole('radio', { name: new RegExp(label) }).click()
  }

  async toggleAdvanced (): Promise<void> {
    const details = this.dialog.locator('details.studio-disclosure')
    if (!(await details.evaluate(element => (element as HTMLDetailsElement).open))) {
      await details.locator('summary').click()
    }
  }

  async save (): Promise<void> {
    await this.dialog.getByRole('button', { name: /^(添加模型|保存更改)$/ }).click()
  }

  async runConnectionTest (): Promise<void> {
    await this.dialog.getByRole('button', { name: '连接测试', exact: true }).click()
    await expect(this.dialog.locator('.model-test-result')).toBeVisible({ timeout: 30_000 })
  }

  async testStatus (): Promise<string> {
    return (await this.dialog.locator('.model-test-result tbody tr').first().innerText()).trim()
  }

  async closeDialog (): Promise<void> {
    await this.dialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(this.dialog).toBeHidden()
  }

  async deleteByName (name: string): Promise<void> {
    await this.rowByName(name).first().getByRole('button', { name: '删除', exact: true }).click()
    await confirmDeletion(this.page)
  }
}
