import fs from 'node:fs'
import path from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { test, expect, resourceName } from '../../support/fixtures/test'
import { env } from '../../support/env'
import { GraphListPage } from '../../support/pages/graph-list.page'
import { deleteConfirmDialog } from '../../support/pages/delete-confirm.page'

/**
 * axe 已知问题基线。
 *
 * 计数是“最多允许”的节点数：数量下降仍然通过；超过上限（新增同类问题）才失败。
 * - color-contrast：主按钮白字压主题蓝，对比度不足；
 * - label-content-name-mismatch：语言按钮 aria-label=切换语言，可见文字=English；
 * - label：Element Plus 的 select 内部 combobox input 没有可访问名称。
 */
const A11Y_BASELINE: Record<string, Record<string, number>> = {
  '#/knowledge': { 'color-contrast': 1, 'label-content-name-mismatch': 1, label: 1 },
  '#/graph': { 'color-contrast': 4, 'label-content-name-mismatch': 1, label: 1 },
  '#/flow': { 'color-contrast': 1, 'label-content-name-mismatch': 1, label: 1 },
  '#/chat': { 'color-contrast': 4, 'label-content-name-mismatch': 1, label: 1 },
  '#/models': { 'color-contrast': 1, 'label-content-name-mismatch': 1, label: 1 }
}

interface RawKeyHit {
  source: 'text' | 'placeholder' | 'title' | 'aria-label'
  value: string
}

async function collectRawKeys (page: import('@playwright/test').Page): Promise<RawKeyHit[]> {
  return page.evaluate(() => {
    const pattern = /\b(?:modules|public|app|prompt|advancedFlow|ragFlow|knowledge|nav|messageBox|retrievalTest|modelManagement)\.[A-Za-z][A-Za-z0-9_.]*/g
    const hits: Array<{ source: 'text' | 'placeholder' | 'title' | 'aria-label', value: string }> = []
    const collect = (source: 'text' | 'placeholder' | 'title' | 'aria-label', value: string | null): void => {
      if (!value) return
      const matches = value.match(pattern)
      if (matches) {
        for (const match of new Set(matches)) hits.push({ source, value: match })
      }
    }
    collect('text', document.body.innerText)
    for (const element of Array.from(document.querySelectorAll('input, textarea'))) {
      collect('placeholder', element.getAttribute('placeholder'))
    }
    for (const element of Array.from(document.querySelectorAll('[title], [aria-label]'))) {
      collect('title', element.getAttribute('title'))
      collect('aria-label', element.getAttribute('aria-label'))
    }
    const unique = new Map<string, { source: 'text' | 'placeholder' | 'title' | 'aria-label', value: string }>()
    for (const hit of hits) unique.set(`${hit.source}:${hit.value}`, hit)
    return Array.from(unique.values())
  })
}

async function gotoHash (page: import('@playwright/test').Page, hash: string): Promise<void> {
  await page.goto(`${env.baseURL}/${hash}`)
  await page.waitForLoadState('networkidle')
}


async function switchLanguage (
  page: import('@playwright/test').Page,
  lang: 'zh' | 'en'
): Promise<void> {
  await page.locator('.settings-button').click()
  await page.locator('.language-option')
    .filter({ hasText: lang === 'en' ? 'English' : '简体中文' })
    .click()
  // 切换语言会整页重载（见 LeftNav.selectLanguage 的注释）
  await page.waitForLoadState('networkidle')
}

test.describe('界面与可访问性', () => {
  /**
   * 深色是默认主题。这组基线因此是**深色基线**；
   * 浅色只作为可切换的回落态，不再用同一组数字同时约束两套主题。
   * 只在没有偏好时写入，避免覆盖将来显式测浅色的用例。
   */
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      if (!localStorage.getItem('ragstudio-theme')) {
        localStorage.setItem('ragstudio-theme', 'dark')
      }
    })
  })

  test('@p0 UI-01 中文界面无裸 i18n key', async ({ page }) => {
    test.setTimeout(180_000)
    const pages = ['#/knowledge', '#/graph', '#/flow', '#/chat', '#/models']
    const found: Record<string, RawKeyHit[]> = {}
    for (const hash of pages) {
      await gotoHash(page, hash)
      found[hash] = await collectRawKeys(page)
    }
    const problems = Object.entries(found)
      .filter(([, hits]) => hits.length > 0)
      .map(([hash, hits]) => `${hash}: ${hits.map(hit => `${hit.source}=${hit.value}`).join(', ')}`)
    expect(problems, problems.join('\n')).toEqual([])
  })

  test('@p0 UI-02 英文界面完整性', async ({ page }) => {
    test.setTimeout(180_000)
    await gotoHash(page, '#/knowledge')
    await switchLanguage(page, 'en')

    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
    await expect(page.locator('.nav-item').filter({ hasText: 'Document Knowledge Base' }).first())
      .toBeVisible()
    expect(await collectRawKeys(page)).toEqual([])

    // 后端错误文案跟随 Accept-Language
    const response = await page.request.post('/api/co-knowledge/v1/knowledge-bases?type=graph', {
      headers: { 'Accept-Language': 'en-US' },
      data: { name: 'x', description: 'e2e', category: 1, props: { embeddingModel: 'e2e-embedding' } }
    })
    const body = await response.text()
    expect(body).not.toMatch(/[\u4e00-\u9fa5]/)
  })

  test('@p0 UI-02b html lang 标记', async ({ page }) => {
    await gotoHash(page, '#/knowledge')
    await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
    await switchLanguage(page, 'en')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
  })

  test('@p1 UI-03 语言持久化', async ({ page }) => {
    test.setTimeout(120_000)
    await gotoHash(page, '#/knowledge')
    await switchLanguage(page, 'en')
    await page.reload()
    await page.waitForLoadState('networkidle')

    const stored = await page.evaluate(() => localStorage.getItem('language-option'))
    expect(JSON.parse(stored || 'null')).toBe('en-US')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
    await expect(page.locator('.nav-item').filter({ hasText: 'Document Knowledge Base' }).first())
      .toBeVisible()
  })

  test('@p1 UI-05 320/375/1920 响应式无横向滚动', async ({ page }) => {
    test.setTimeout(180_000)
    const widths = [320, 375, 1920]
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 })
      await gotoHash(page, '#/knowledge')
      if (width < 768) {
        // 窄屏先收起导航，内容区才有可用宽度
        const collapse = page.locator('.sidebar .side-footer .icon-button').last()
        if (await collapse.isVisible().catch(() => false)) {
          await collapse.click()
          await page.waitForTimeout(200)
        }
      }
      const metrics = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth
      }))
      expect(metrics.scrollWidth, `${width}px 出现横向滚动`).toBeLessThanOrEqual(
        metrics.clientWidth + 1
      )
      // KB 列表使用原生 table + .table-pagination。
      await expect(page.locator('.table-pagination').first()).toBeVisible()
      await expect(page.getByRole('button', { name: /新建知识库/ })).toBeVisible()
    }
  })

  test('@p1 UI-06 键盘焦点与 Esc 关闭对话框', async ({ page, api }) => {
    test.setTimeout(180_000)
    await gotoHash(page, '#/knowledge')
    await page.locator('.settings-button').focus()
    const focusStyle = await page.locator('.settings-button').evaluate(element => {
      const style = getComputedStyle(element)
      return { outline: style.outlineStyle, shadow: style.boxShadow }
    })
    expect(
      focusStyle.outline !== 'none' || focusStyle.shadow !== 'none',
      '偏好设置按钮缺少可见焦点样式'
    ).toBe(true)

    const seeded = await api.graph.createKb({
      name: resourceName('UI-06'),
      description: 'E2E keyboard',
      embeddingModel: (await api.listEmbeddingModels())[0]
    })
    try {
      const list = new GraphListPage(page)
      await list.goto()
      await list.search(seeded.name)
      await list.expectRow(seeded.name)
      await list.openMore(seeded.name)
      await page.getByRole('menuitem', { name: '删除' }).click()
      const dialog = deleteConfirmDialog(page)
      await expect(dialog).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden({ timeout: 10_000 })
    } finally {
      await api.graph.cleanup(seeded.id)
    }
  })

  test('@p1 UI-07 axe 可访问性（critical/serious）', async ({ page }) => {
    test.setTimeout(240_000)
    const pages = ['#/knowledge', '#/graph', '#/flow', '#/chat', '#/models']
    const serious: string[] = []
    for (const hash of pages) {
      await gotoHash(page, hash)
      const results = await new AxeBuilder({ page }).analyze()
      for (const violation of results.violations) {
        if (violation.impact !== 'critical' && violation.impact !== 'serious') continue
        const allowed = A11Y_BASELINE[hash]?.[violation.id] ?? 0
        if (violation.nodes.length > allowed) {
          serious.push(
            `${hash}: [${violation.impact}] ${violation.id} × ${violation.nodes.length}` +
            `（基线 ${allowed}）`
          )
        }
      }
    }
    expect(serious, serious.join('\n')).toEqual([])
  })

  test('@p2 UI-08 reduced-motion 下无必要动画', async ({ page }) => {
    test.setTimeout(120_000)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await gotoHash(page, '#/knowledge')
    const durations = await page.evaluate(() => {
      const selectors = ['.el-loading-spinner .circular', '.el-button', '.el-tag', '.el-menu-item']
      const values: Record<string, string> = {}
      for (const selector of selectors) {
        const element = document.querySelector(selector)
        if (!element) continue
        const style = getComputedStyle(element)
        values[selector] = `${style.animationDuration}/${style.transitionDuration}`
      }
      return values
    })
    const maxSeconds = (value: string): number => Math.max(
      ...value.split(',').map(item => Number.parseFloat(item) || 0)
    )
    for (const [selector, value] of Object.entries(durations)) {
      const [animation, transition] = value.split('/')
      // 全局 reduced-motion 规则把时长压到 0.01ms（= 1e-05s）。
      expect(maxSeconds(animation), `${selector} animation=${animation}`)
        .toBeLessThanOrEqual(0.001)
      expect(maxSeconds(transition), `${selector} transition=${transition}`)
        .toBeLessThanOrEqual(0.001)
    }
  })

  test('@p2 UI-09 颜色对比度（axe color-contrast）', async ({ page }) => {
    test.setTimeout(180_000)
    const pages = ['#/knowledge', '#/models', '#/chat']
    const violations: string[] = []
    for (const hash of pages) {
      await gotoHash(page, hash)
      const results = await new AxeBuilder({ page })
        .withRules(['color-contrast'])
        .analyze()
      for (const violation of results.violations) {
        const allowed = A11Y_BASELINE[hash]?.['color-contrast'] ?? 0
        if (violation.nodes.length > allowed) {
          violations.push(`${hash}: ${violation.nodes.length} node(s)（基线 ${allowed}）`)
        }
      }
    }
    expect(violations, violations.join('\n')).toEqual([])
  })

  test('@p2 UI-10 表格布局回归（1440×700）', async ({ page, api }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1440, height: 700 })
    const name = resourceName('UI-10-LONG-NAME')
    const kb = await api.createKb(name, (await api.listEmbeddingModels())[0])
    try {
      for (const hash of ['#/knowledge', '#/graph', '#/models']) {
        await gotoHash(page, hash)
        const metrics = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth
        }))
        expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1)
        if (hash === '#/knowledge') {
          // 列表用原生 table + .table-pagination；分页在表格卡片之后，
          // 由 .page 整页滚动，因此先滚到分页再断言可见。
          const pager = page.locator('.table-pagination:visible').first()
          await expect(pager).toBeVisible()
          await pager.scrollIntoViewIfNeeded()
          await expect(pager).toBeInViewport()
        } else {
          await expect(page.locator('.el-pagination:visible').first()).toBeVisible()
          await expect(page.locator('.el-pagination:visible').first()).toBeInViewport()
        }
      }
      // 1440 下 960px 的最小表宽仍能放下，不触发横向滚动；用 1024 窄屏验证溢出契约。
      await page.setViewportSize({ width: 1024, height: 700 })
      await gotoHash(page, '#/knowledge')
      const row = page.locator('table.knowledge-table tbody tr').filter({ hasText: name }).first()
      await expect(row).toBeVisible()
      // 布局契约：超长内容由 .table-card 横向滚动，页面本身不得出现横向滚动。
      const overflow = await page.evaluate(() => {
        const card = document.querySelector('.table-card') as HTMLElement | null
        return {
          cardScrolls: Boolean(card && card.scrollWidth > card.clientWidth + 1),
          docScrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
        }
      })
      expect(overflow.docScrolls).toBe(false)
      expect(overflow.cardScrolls).toBe(true)
    } finally {
      await api.cleanupKb(kb.id)
    }
  })

  test('@p1 UI-04 关键页面截图基线（按需）', async ({ page }) => {
    test.skip(process.env.E2E_VISUAL !== '1', '设置 E2E_VISUAL=1 时生成/比对截图基线')
    test.setTimeout(300_000)
    const pages: Array<[string, string]> = [
      ['kb', '#/knowledge'],
      ['graph', '#/graph'],
      ['flow', '#/flow'],
      ['chat', '#/chat'],
      ['model', '#/models']
    ]
    const widths = [320, 768, 1024, 1440, 1920]
    const outDir = path.join('test-results', 'visual')
    fs.mkdirSync(outDir, { recursive: true })
    for (const [name, hash] of pages) {
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 })
        await gotoHash(page, hash)
        await page.screenshot({
          path: path.join(outDir, `${name}-${width}.png`),
          fullPage: true
        })
      }
    }
  })
})
