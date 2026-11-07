import { defineConfig, devices } from '@playwright/test'
import { env } from './support/env'

const isCI = !!process.env.CI
const includeLive = process.env.E2E_INCLUDE_LIVE === '1'

/**
 * Playwright 配置。
 *
 * 速度约定：
 * - PR 门禁用 `npm run test:fast`（`@fast` 15 条），不要在这里把全量塞进 PR。
 * - 本地默认 2 worker；CI 也是 2（后端单副本 + 共享 ES，更多并发收益有限）。
 * - 失败产物：trace 本地保留、CI 首次重试保留；video 仅失败保留。
 */
export default defineConfig({
  testDir: './tests',
  outputDir: 'test-results',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  // 全量默认 1 worker：fake 模型的 `/__mock__/config` 与 `/__mock__/requests` 是
  // **进程级全局状态**，chat/graph/model/resilience 多个文件都会改它；并发跑会互相
  // 污染（实测 CHAT-11 与 MODEL-05 在 workers=2 下失败）。快速门禁只用到一处配置，
  // 用 `npm run test:fast` 显式开 2 worker（25s 左右跑完 14 条）。
  workers: Number(process.env.E2E_WORKERS || 1),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  globalSetup: './support/global-setup.ts',
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['junit', { outputFile: 'test-results/junit.xml' }]
  ],
  grepInvert: includeLive ? undefined : /@live/,
  use: {
    baseURL: env.baseURL,
    locale: env.locale,
    timezoneId: env.timezone,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: isCI ? 'on-first-retry' : 'retain-on-failure',
    // 本地不录视频：Playwright 的 video 依赖它自带的 ffmpeg，未安装时连 page 都起不来。
    // CI 的 `playwright install --with-deps chromium` 会装上 ffmpeg，那里再开。
    video: isCI ? 'retain-on-failure' : 'off',
    screenshot: 'only-on-failure',
    // 本地默认用系统 Chrome（E2E_BROWSER_CHANNEL=chrome）；CI 留空用 Playwright 自带 Chromium。
    ...(env.browserChannel ? { channel: env.browserChannel } : {})
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    },
    // 夜间跨浏览器：默认不装 Firefox/WebKit 的机器不会因缺浏览器直接失败。
    //   E2E_ALL_BROWSERS=1 npx playwright test --workers=1
    ...(process.env.E2E_ALL_BROWSERS === '1'
      ? [
          {
            name: 'firefox',
            use: { ...devices['Desktop Firefox'], channel: undefined }
          },
          {
            name: 'webkit',
            use: { ...devices['Desktop Safari'], channel: undefined }
          }
        ]
      : [])
  ]
})
