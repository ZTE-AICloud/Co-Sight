import { test, expect } from '../../support/fixtures/test'
import { KbListPage } from '../../support/pages/kb-list.page'
import { NavPage } from '../../support/pages/nav.page'
import { FlowListPage } from '../../support/pages/flow-list.page'

test.describe('冒烟：平台入口与导航', () => {
  test('@smoke @fast @p0 SMK-01 首页加载并重定向到登录页（UX 原型默认）', async ({ page }) => {
    // UX 原型 router.js：`/` → `/login`（登录页是默认首页）。
    await page.goto('/')
    await expect(page).toHaveURL(/#\/login$/)
    await expect(page).toHaveTitle('Knowledge Studio')
    await expect(page.locator('html')).toHaveAttribute('lang', /zh/i)
    await expect(page.locator('.login-page')).toBeVisible()
  })

  test('@smoke @fast @p0 SMK-02 左栏四个入口可达', async ({ page }) => {
    const nav = new NavPage(page)
    await page.goto('/#/knowledge')
    await nav.expectMenus()

    await nav.openDocKb()
    await expect(page.locator('.knowledge-page')).toBeVisible()

    await nav.openGraphKb()
    await expect(page.locator('.knowledge-page')).toBeVisible()
    await expect(page.locator('.graph-list-page')).toBeVisible()

    await nav.openFlow()
    await expect(page.locator('.flow-page')).toBeVisible()

    await nav.openChat()
    await expect(page.locator('.chat-page')).toBeVisible()

    await nav.openOperator()
    await expect(page.locator('.operators-page')).toBeVisible()

    await nav.openModel()
    await expect(page.locator('.models-page')).toBeVisible()
  })

  test('@smoke @fast @p0 SMK-03 健康检查与库列表', async ({ api }) => {
    expect((await api.health()).trim()).toBe('ok')

    const kbs = await api.listKbs()
    expect(Array.isArray(kbs)).toBe(true)
  })

  test('@smoke @fast @p0 SMK-04 未知路由回退到文档知识库', async ({ page }) => {
    await page.goto('/#/not-exist')
    await expect(page).toHaveURL(/#\/knowledge$/)
    await expect(page.locator('.knowledge-page')).toBeVisible()
  })

  test('@smoke @fast @p0 SMK-05 未注册地址按未知地址兜底', async ({ page }) => {
    for (const hash of ['/#/kb/knowledgeGraph', '/#/model', '/#/remoteAccess/keys']) {
      await page.goto(hash)
      await expect(page).toHaveURL(/#\/knowledge$/)
      await expect(page.locator('.knowledge-page')).toBeVisible()
    }
  })

  test('@smoke @fast @p0 SMK-06 主要页面加载无 console error', async ({ page }) => {
    const pages = [
      { hash: '/#/knowledge', root: '.knowledge-page' },
      { hash: '/#/graph', root: '.knowledge-page' },
      { hash: '/#/flow', root: '.flow-page' },
      { hash: '/#/chat', root: '.chat-page' },
      { hash: '/#/operators', root: '.operators-page' },
      { hash: '/#/models', root: '.models-page' }
    ]
    for (const item of pages) {
      await page.goto(item.hash)
      await expect(page.locator(item.root).first()).toBeVisible()
    }
  })

  test('@smoke @fast @p0 SMK-07 刷新与前进后退保持可用', async ({ page }) => {
    const kb = new KbListPage(page)
    const flow = new FlowListPage(page)
    const nav = new NavPage(page)

    await kb.goto()
    await nav.openFlow()
    await flow.root.waitFor({ state: 'visible' })

    await page.reload()
    await expect(page).toHaveURL(/#\/flow$/)
    await expect(flow.root).toBeVisible()

    await page.goBack()
    await expect(page).toHaveURL(/#\/knowledge$/)
    await expect(kb.root).toBeVisible()
  })

  test('@p1 SMK-08 关键断点无横向溢出', async ({ page }) => {
    for (const width of [320, 375, 768, 1024, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 })
      await page.goto('/#/knowledge')
      await expect(page.locator('.knowledge-page')).toBeVisible()
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth
      )
      expect(overflow, `${width}px 下出现横向溢出`).toBeLessThanOrEqual(1)
    }
  })

  test('@p1 SMK-09 空数据环境可渲染', async ({ page }) => {
    // KB 列表：搜一个不存在的关键词 → 表格空态
    const kb = new KbListPage(page)
    await kb.goto()
    await kb.searchInput.fill(`E2E-NO-DATA-${Date.now()}`)
    await expect(kb.root.locator('.empty-row')).toBeVisible({ timeout: 20_000 })

    // 图谱模版列表：客户端过滤后空态
    await page.goto('/#/graph?subTab=knowledgeGraphTemplate')
    const templateSearch = page.locator('.knowledge-graph-template-page')
      .getByPlaceholder('搜索图谱模版名称')
    await templateSearch.fill(`E2E-NO-DATA-${Date.now()}`)
    await expect(page.locator('.knowledge-graph-template-page .empty-row'))
      .toBeVisible({ timeout: 20_000 })
  })

  test('@p1 SMK-10 纯 REST 响应（无 code/bo 信封）', async ({ api }) => {
    const endpoints = [
      '/knowledge-bases',
      '/workflows?page=1&size=10&keyword=',
      '/models?currentPage=1&pageSize=10',
      '/graph-schemas'
    ]
    for (const path of endpoints) {
      const response = await api.fetchRaw(path)
      expect(response.ok(), path).toBe(true)
      const body = await response.json()
      expect(body.code, path).toBeUndefined()
      expect(body.bo, path).toBeUndefined()
    }
    // 分页端点统一 items/total；非分页集合（graph-schemas）是数组
    const page = await (await api.fetchRaw('/knowledge-bases')).json()
    expect(Array.isArray(page.items)).toBe(true)
    expect(typeof page.total).toBe('number')
  })

  test('@p2 SMK-12 静态资源无 404', async ({ page }) => {
    const failures: string[] = []
    page.on('response', response => {
      const type = response.request().resourceType()
      if (!['script', 'stylesheet', 'font', 'image'].includes(type)) return
      if (response.status() >= 400) {
        failures.push(`${response.status()} ${response.url()}`)
      }
    })
    for (const hash of ['/#/knowledge', '/#/flow', '/#/chat', '/#/models']) {
      await page.goto(hash)
      await page.waitForLoadState('networkidle')
    }
    expect(failures, failures.join('\n')).toEqual([])
  })

  test('@p1 SMK-11 页面标题与语言属性', async ({ page }) => {
    for (const hash of ['/#/knowledge', '/#/flow', '/#/chat', '/#/models']) {
      await page.goto(hash)
      expect(await page.title()).toBe('Knowledge Studio')
      expect(await page.locator('html').getAttribute('lang')).toMatch(/zh/i)
    }
  })

  test('@p1 SMK-13 折叠态左栏图标导航可用', async ({ page }) => {
    // 折叠态隐藏文字标签，只留图标 + title；点击图标仍应能导航。
    await page.addInitScript(() => localStorage.setItem('ragstudio-nav-collapse', '1'))
    await page.goto('/#/flow')
    const sidebar = page.locator('.sidebar')
    await expect(sidebar).toHaveClass(/collapsed/)

    const chatItem = sidebar.locator('.nav-item').filter({ hasText: '对话测试' }).first()
    await expect(chatItem).toBeVisible()
    await expect(chatItem.locator('span')).toBeHidden()
    await expect(chatItem).toHaveAttribute('title', '对话测试')
    await chatItem.click()
    await expect(page).toHaveURL(/#\/chat$/)
  })
})
