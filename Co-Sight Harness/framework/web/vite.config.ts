/**
 * Vite 配置（D3 = A：CSS Modules + CSS 自定义属性 + lightningcss）。
 *
 * 三处值得说明：
 *
 * 1. **CSS 走 lightningcss 而不是 postcss**。Vite 默认用 postcss；换成 lightningcss
 *    后自动加前缀、降级语法、压缩都发生在同一步，不需要再配 autoprefixer。
 *    CSS Modules 的类名规则要在这里显式给出——lightningcss 的默认 pattern 与
 *    Vite 自带的不同，不写死会在换预处理器时悄悄改变产物的类名。
 *
 * 2. **开发态代理 `/api` 到后端**。前端与 API 同源是刻意的：只有同源，
 *    `SameSite=Lax` 的桥接 cookie 才会被带上（见 framework/server/src/routes/bridge.ts）。
 *    若改成直连 :4300，开发态与生产态的 cookie 行为就不一致了。
 *
 * 3. **契约包 `harness-shared` 不参与 optimizeDeps**。它以 `src/*.ts` 源码形式导出，
 *    预打包会把 TS 当成不可处理的产物；排除后由 Vite 走正常编译链。
 */

/// <reference types="vitest/config" />

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/** 后端默认端口，与 framework/server/src/config/env.ts 的 DEFAULT_PORT 保持一致。 */
const API_PORT = 4300;

/**
 * 前端开发态端口，**刻意不用 Vite 默认的 5173**。
 *
 * 全仓开发端口按模块分段，统一落在 4xxx：框架 43xx（API 4300 / 前端 4310）、
 * smart-factory 41xx（API 4100 / 前端 4110）、cosight-viewer 48xx。
 * 5173 是 Vite 默认值，大量 AI 生成的项目也用它，容易撞车，所以不用。
 *
 * 改动这里要同步三处：`framework/server/src/config/env.ts` 的 `readOrigins` 默认值
 * （否则开发态前端会被 CORS 拒掉）、`playwright.config.ts` 的 `WEB_PORT`、
 * 以及 `framework/server/docs/architecture.md` 里的环境变量表。
 */
const WEB_PORT = 4310;

export default defineConfig({
  plugins: [react()],

  css: {
    transformer: 'lightningcss',
    lightningcss: {
      // 生产态压缩；开发态保持可读，方便在 DevTools 里对照设计稿。
      cssModules: { pattern: 'cs-[hash]_[local]' },
    },
  },

  server: {
    port: WEB_PORT,
    strictPort: true,
    /*
     * 绑所有网卡：默认的 `localhost` 在部分机器上只落到 IPv6 回环（`::1`），
     * 容器端口映射或局域网访问会 ERR_CONNECTION_REFUSED。仅本机开发时可用
     * `--host 127.0.0.1` 覆盖。
     *
     * 注意这只是 Vite 自己的监听面。模块 iframe 的 entry 是浏览器要访问的地址，
     * 不能跟着写成 `0.0.0.0`（见 docs/modules/*.module.json）。
     */
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${String(API_PORT)}`,
        changeOrigin: false,
      },
    },
  },

  build: {
    outDir: 'dist',
    sourcemap: true,
  },

  optimizeDeps: {
    exclude: ['harness-shared'],
  },

  test: {
    environment: 'jsdom',
    globals: false,
    // 组件测试要断言布局相关的样式（如卡片高度、网格列数），因此需要真实处理 CSS。
    css: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/main.tsx',
        'src/**/*.d.ts',
        // 纯样式与纯文案：没有可执行分支，纳入覆盖率只会稀释信号。
        'src/styles/**',
        'src/i18n/messages/**',
      ],
      thresholds: { statements: 80, branches: 80, functions: 80, lines: 80 },
    },
  },
});
