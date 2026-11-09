/**
 * Playwright 配置（D10 = A：Vitest 测单元/组件，Playwright 测真实浏览器）。
 *
 * 为什么在已经有 300 个组件测试之后还要 e2e：jsdom 没有布局。侧栏固定与主面板内滚
 * （`position: sticky` + 溢出裁剪）、focus trap 在真实 Tab 顺序下的表现——这些在
 * jsdom 里全部测不了，而它们恰恰是最容易悄悄坏掉的部分。
 *
 * 两个前置：
 * - **后端与前端一起起**：`/api` 是前端代理过去的，只起前端会满屏"无法连接服务端"；
 * - **浏览器要装**：`pnpm exec playwright install chromium`。
 */

import { defineConfig, devices } from '@playwright/test';

/**
 * 与 `vite.config.ts` 的 `WEB_PORT` / `API_PORT` 对应。
 *
 * 这里是**另外写死的一份**，不是 import 过来的：Playwright 要在 Vite 没起来时就能
 * 算出探测地址，而 import 一份 ESM 配置会把它自己的 `defineConfig` 也拖进来。
 * 代价是这三个数字必须一起改（另一处是 `config/env.ts` 的 `readOrigins` 默认值）。
 */
const WEB_PORT = 4310;
const API_PORT = 4300;

/**
 * 前端探 `localhost`，后端探 `127.0.0.1`——不是笔误。
 *
 * Vite 没设 `server.host`，Node 把 `localhost` 解析成 `::1`，于是它**只绑 IPv6**：
 * 探 `http://127.0.0.1:4310` 会一直等到 `webServer` 超时（60s），整份 e2e 一条都跑不到。
 * 浏览器打开 `localhost:4310` 却正常，因为浏览器自己会试两个地址。
 * 后端（Fastify）绑的就是 `127.0.0.1`，所以那一条保持 IPv4。
 */
const WEB_URL = `http://localhost:${String(WEB_PORT)}`;
const API_URL = `http://127.0.0.1:${String(API_PORT)}`;

const isCi = process.env.CI !== undefined && process.env.CI !== '';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  // CI 上不留 `test.only`：它会静默跳过整个套件，是最难发现的 CI 退化。
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  reporter: isCi ? [['github'], ['html', { open: 'never' }]] : [['list']],

  use: {
    baseURL: WEB_URL,
    /*
     * 固定浏览器语言。
     *
     * 这不是为了"跑得过"——框架启动时按浏览器语言决定界面语言（D28 = B），
     * 而 Playwright 默认是 `en-US`。不固定的话，同一份断言在开发机（中文系统）
     * 与 CI 上是两种语言，失败信息只会说"文字不匹配"。
     */
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  webServer: [
    {
      // 启动脚本由需求 2.4 统一提供，这里刻意只依赖包级脚本，不复制启动参数。
      command: 'pnpm --filter harness-server run start',
      url: `${API_URL}/api/health`,
      reuseExistingServer: !isCi,
      stdout: 'pipe',
      stderr: 'pipe',
      timeout: 60_000,
    },
    {
      command: 'pnpm --filter harness-web run dev',
      url: WEB_URL,
      reuseExistingServer: !isCi,
      stdout: 'pipe',
      stderr: 'pipe',
      timeout: 60_000,
    },
  ],
});
