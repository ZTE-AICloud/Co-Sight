/**
 * 本地账号登录（AUTH_MODE=local）。
 *
 * 跑法：
 *   AUTH_MODE=local E2E_AUTH_MODE=local RKB_ADMIN_PASSWORD='...' \
 *     bash e2e/scripts/stack-up.sh
 *   E2E_AUTH_MODE=local npx playwright test tests/auth/login.spec.ts
 *
 * 每条用例使用独立的浏览器上下文（Playwright 默认），因此都从匿名开始。
 * 强制改密流程由前端单测覆盖；E2E 栈用 RKB_ADMIN_MUST_CHANGE=false 播种。
 */
import { expect, test, type Page } from '@playwright/test'

import { env } from '../../support/env'

test.describe('@auth 本地账号登录', () => {
  test.beforeEach(() => {
    test.skip(env.authMode !== 'local', '需要 E2E_AUTH_MODE=local 且栈以 AUTH_MODE=local 启动')
  })

  async function login (page: Page) {
    await page.locator('#login-account').fill(env.adminUsername)
    await page.locator('#login-password').fill(env.adminPassword)
    await page.locator('form.login-form button[type="submit"]').click()
  }

  test('匿名访问业务页 → 登录 → 回到原地址', async ({ page }) => {
    await page.goto('/#/knowledge')

    await expect(page).toHaveURL(/#\/login\?redirect=/)
    await login(page)

    await expect(page).toHaveURL(/#\/knowledge$/)
  })

  test('错误口令：内联报错且不跳转', async ({ page }) => {
    await page.goto('/#/login')
    await page.locator('#login-account').fill(env.adminUsername)
    await page.locator('#login-password').fill('definitely-wrong')
    await page.locator('form.login-form button[type="submit"]').click()

    await expect(page.locator('#login-password-error')).toContainText('账号或密码不正确')
    await expect(page).toHaveURL(/#\/login/)
  })

  test('登录后刷新仍保持会话', async ({ page }) => {
    await page.goto('/#/login')
    await login(page)
    await expect(page).toHaveURL(/#\/knowledge$/)

    await page.reload()

    await expect(page).toHaveURL(/#\/knowledge$/)
    await expect(page.locator('form.login-form')).toHaveCount(0)
  })

  test('深链登录后回到原页面', async ({ page }) => {
    await page.goto('/#/chat')

    await expect(page).toHaveURL(/#\/login\?redirect=/)
    await login(page)

    await expect(page).toHaveURL(/#\/chat$/)
  })

  test('退出登录后再次访问被挡回登录页', async ({ page }) => {
    await page.goto('/#/login')
    await login(page)
    await expect(page).toHaveURL(/#\/knowledge$/)

    await page.locator('.user-trigger').click()
    await page.locator('.user-item--danger').click()

    await expect(page).toHaveURL(/#\/login/)

    await page.goto('/#/knowledge')
    await expect(page).toHaveURL(/#\/login\?redirect=/)
  })

  test('后端直接访问：业务接口 401 problem+json，健康检查公开', async ({ request }) => {
    const protectedResponse = await request.get('/api/co-knowledge/v1/knowledge-bases')
    expect(protectedResponse.status()).toBe(401)
    expect(protectedResponse.headers()['content-type']).toContain('application/problem+json')
    expect((await protectedResponse.json()).code).toBe('unauthorized')

    const health = await request.get('/api/co-knowledge/v1/health')
    expect(health.status()).toBe(200)
    expect((await health.text()).trim()).toBe('ok')
  })
})
