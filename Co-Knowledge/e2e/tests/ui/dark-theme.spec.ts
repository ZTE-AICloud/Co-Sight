/**
 * 深色主题验收（UI-DARK）。
 *
 * 目标不是截图比对，而是抓两类真实回归：
 *   1. 深色页面里残留的浅色大块表面（白块）—— 视觉上最刺眼的失败模式
 *   2. 断点横向溢出 / 焦点不可见 / 主题切换不持久
 *
 * 白块判据：可见、面积 > 2000px²、computed background-color 不透明、
 * 相对亮度 > 0.72，且不是图片/SVG/画布/渐变/近白主按钮。
 *
 * 运行：E2E_BASE_URL=http://127.0.0.1:8088 npx playwright test tests/ui/dark-theme.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

const ROUTES = [
  { path: '/#/knowledge', name: 'doc-kb' },
  { path: '/#/graph', name: 'graph-kb' },
  { path: '/#/flow', name: 'flow-list' },
  { path: '/#/models', name: 'model' },
  { path: '/#/chat', name: 'chat' },
  { path: '/#/access', name: 'access-guide' },
  { path: '/#/operators', name: 'operators' }
]

type LightSurface = {
  tag: string
  cls: string
  bg: string
  area: number
}

async function collectLightSurfaces (page: Page): Promise<LightSurface[]> {
  return page.evaluate(() => {
    const SKIP_TAGS = new Set([
      'IMG', 'SVG', 'CANVAS', 'VIDEO', 'PATH', 'CIRCLE', 'RECT', 'LINE', 'TEXT', 'POLYGON', 'G'
    ])
    const SKIP_SELECTORS = [
      '.el-button--primary',
      '.btn-primary',
      '.el-button--danger',
      '.el-button--success',
      '.el-loading-spinner',
      '.brand'
    ]

    const rgb = (value: string) => {
      const m = value.match(/rgba?\(([^)]+)\)/)
      if (!m) return null
      const parts = m[1].split(',').map((n) => Number(n.trim()))
      return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 }
    }
    const luminance = (c: { r: number, g: number, b: number }) => {
      const f = (v: number) => {
        const s = v / 255
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
      }
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
    }

    const visible = (el: Element) => {
      const cs = getComputedStyle(el)
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return false
      const r = el.getBoundingClientRect()
      return r.width > 0 && r.height > 0
    }

    const out: LightSurface[] = []
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      if (SKIP_TAGS.has(el.tagName)) continue
      if (SKIP_SELECTORS.some((s) => el.closest(s))) continue
      if (!visible(el)) continue
      const rect = el.getBoundingClientRect()
      const area = rect.width * rect.height
      if (area < 2000) continue
      const cs = getComputedStyle(el)
      if (cs.backgroundImage !== 'none') continue
      const c = rgb(cs.backgroundColor)
      if (!c || c.a < 0.5) continue
      if (luminance(c) <= 0.72) continue
      out.push({
        tag: el.tagName.toLowerCase(),
        cls: typeof el.className === 'string' ? el.className.slice(0, 80) : '',
        bg: cs.backgroundColor,
        area: Math.round(area)
      })
    }
    return out.sort((a, b) => b.area - a.area).slice(0, 20)
  })
}

test.describe('@ui dark theme', () => {
  test.beforeEach(async ({ page }) => {
    // 只在没有偏好时给深色，不能覆盖用户/上一个用例写入的 light，
    // 否则「切换后刷新仍保持」这条会被初始化脚本自己打回 dark。
    await page.addInitScript(() => {
      if (!localStorage.getItem('ragstudio-theme')) {
        localStorage.setItem('ragstudio-theme', 'dark')
      }
    })
  })

  for (const route of ROUTES) {
    test(`UI-DARK ${route.name}: 无白块、无横向溢出`, async ({ page }) => {
      await page.goto(route.path)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(400)

      expect(await page.locator('html').evaluate((el) => el.classList.contains('dark'))).toBe(true)

      const lights = await collectLightSurfaces(page)
      expect(lights, `${route.name} 仍有浅色大块表面：\n${JSON.stringify(lights, null, 2)}`).toEqual([])

      const overflow = await page.evaluate(() => {
        const doc = document.documentElement
        return doc.scrollWidth - doc.clientWidth
      })
      expect(overflow, `${route.name} 横向溢出 ${overflow}px`).toBeLessThanOrEqual(1)
    })
  }

  test('UI-DARK 主题切换可持久化', async ({ page }) => {
    await page.goto('/#/knowledge')
    await page.waitForLoadState('networkidle')

    await page.locator('.theme-button').click()
    await expect(page.locator('html')).not.toHaveClass(/dark/)
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem('ragstudio-theme')))
      .toBe('light')

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('html')).not.toHaveClass(/dark/)

    await page.locator('.theme-button').click()
    await expect(page.locator('html')).toHaveClass(/dark/)
  })

  test('UI-DARK 键盘焦点可见', async ({ page }) => {
    await page.goto('/#/knowledge')
    await page.waitForLoadState('networkidle')

    await page.keyboard.press('Tab')
    const focusStyle = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null
      if (!el) return null
      const cs = getComputedStyle(el)
      return { tag: el.tagName, outline: cs.outlineStyle, shadow: cs.boxShadow }
    })
    expect(focusStyle).not.toBeNull()
    expect(
      focusStyle!.outline !== 'none' || focusStyle!.shadow !== 'none',
      `焦点元素 ${focusStyle!.tag} 没有可见焦点环`
    ).toBe(true)
  })
})
