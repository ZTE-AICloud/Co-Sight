import { expect, type Page } from '@playwright/test'

/** 页面对象基类：只放导航与“页面已渲染”的通用断言。 */
export class BasePage {
  constructor (readonly page: Page) {}

  /** hash 路由：传 `/#/knowledge`、`#/knowledge` 或 `/knowledge` 均可。 */
  async gotoHash (hash: string): Promise<void> {
    let normalized = hash
    if (normalized.startsWith('/#')) normalized = normalized.slice(1)
    else if (!normalized.startsWith('#')) {
      normalized = `#${normalized.startsWith('/') ? '' : '/'}${normalized}`
    }
    await this.page.goto(`/${normalized}`, { waitUntil: 'domcontentloaded' })
  }

  async expectRoot (selector: string): Promise<void> {
    await expect(this.page.locator(selector).first()).toBeVisible()
  }

  async expectHash (hash: string): Promise<void> {
    const escaped = hash.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    await expect(this.page).toHaveURL(new RegExp(`${escaped}$`))
  }
}
