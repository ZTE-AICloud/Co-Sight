import { expect, type Page } from '@playwright/test'

/** 页面对象基类：只放导航与“页面已渲染”的通用断言。 */
export class BasePage {
  constructor (readonly page: Page) {}

  /** history 路由：传 `/knowledge`、`#/knowledge` 或 `/#/knowledge` 均可（统一归一为 path）。 */
  async gotoPath (path: string): Promise<void> {
    let normalized = path
    if (normalized.startsWith('/#')) normalized = normalized.slice(1)
    if (normalized.startsWith('#')) normalized = normalized.slice(1)
    if (!normalized.startsWith('/')) normalized = `/${normalized}`
    await this.page.goto(normalized, { waitUntil: 'domcontentloaded' })
  }

  async expectRoot (selector: string): Promise<void> {
    await expect(this.page.locator(selector).first()).toBeVisible()
  }

  async expectPath (path: string): Promise<void> {
    let normalized = path
    if (normalized.startsWith('/#')) normalized = normalized.slice(1)
    if (normalized.startsWith('#')) normalized = normalized.slice(1)
    if (!normalized.startsWith('/')) normalized = `/${normalized}`
    const escaped = normalized.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    await expect(this.page).toHaveURL(new RegExp(`${escaped}(?:[?#].*)?$`))
  }
}
