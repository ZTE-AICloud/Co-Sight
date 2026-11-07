/**
 * Vitest 配置（前端单测运行器）。
 *
 * ⚠️ 为什么是 `.mjs` 而不是 `.ts` / `.js`：
 *   - `frontend/` 没有 `"type": "module"`，`.js` 会被 Node 当 CJS 解析，而配置里用了 `import`；
 *     加 `"type": "module"` 又会把 `vue.config.js` / `babel.config.js` / `postcss.config.js`
 *     这些 vue-cli 的 CJS 配置一起改成 ESM，直接打不起来。
 *   - `.mjs` 后缀让只有这一个文件按 ESM 解析，两边的模块体系互不干扰。
 *
 * ⚠️ 为什么 `environment: 'node'` 而不是 jsdom：现有 `tests/unit/**.spec.js` 全是纯对象
 * 断言（i18n 键集比对），`lib/*` 也是零 DOM 依赖的纯函数；上 jsdom 只会拖慢启动。
 * 需要 DOM 的 spec **按文件** opt-in：文件头写 `// @vitest-environment jsdom`
 * （见 `chat.markdown.spec.js`）。组件测试（`Component.spec.js`）一律要走 jsdom，
 * 用 `tests/unit/helpers/mount.js` 的 `mountWithPlugins()`，别在这里改成全局 jsdom
 * —— 那会让十几条零 DOM 依赖的 spec 白跑一遍 jsdom 环境。
 *
 * ⚠️ `plugins: [vue()]` 只服务 vitest：让 spec 能 `import` `.vue` 单文件组件（`<script setup>`
 * 必须编译才能挂载）。它**不影响** vue-cli/webpack 那条构建链 —— 那条链的 vue-loader 配置
 * 在 `vue.config.js` 里，`dist/` 产物只由 `npm run build` 产出。
 */
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    // 与 `vue.config.js` 的 `resolve.alias` 保持一致：spec 与源码里都在用 `@/`
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  test: {
    // 现有 spec 用的是 Jest 风格的全局 describe/it/expect（没有 import vitest）
    globals: true,
    environment: 'node',
    include: ['tests/unit/**/*.spec.js'],
    // `src/shared/lib/nameValidator.test.js` 是历史遗留的 `console.log` 冒烟脚本（0 断言），
    // 已按原意改写为 `tests/unit/nameValidator.spec.js`；这里显式排除旧路径，
    // 防止以后有人放宽 include 时又把它当测试收集进来。
    exclude: ['**/node_modules/**', '**/dist/**', 'src/**'],
    server: {
      deps: {
        // `@popperjs/core` 是 Element Plus 的 tooltip/popper 链引入的 CJS 包
        // （`main: dist/cjs/popper.js`，没有 `exports` 字段），Node 原生 ESM 加载它
        // 拿不到命名导出 —— 组件 spec 会直接报
        // `Named export 'placements' not found`。
        // ⚠️ 只内联 `@popperjs/core` 不够：`element-plus` 本身也被外部化，那个
        //    `import { placements } from '@popperjs/core'` 是 Node 自己解析的，
        //    Vite 的 alias/module 字段都插手不了；必须把 element-plus 一起内联，
        //    让它的依赖走 Vite 的解析（Vite 按 `module` 字段取 popper 的 ESM 版）。
        // ⛔ 与 webpack 构建链无关：webpack 处理 CJS 本来就没问题，只有 vitest 的
        //    「node_modules 默认外部化」才会踩到。
        inline: [/element-plus/, /@popperjs\/core/, /@element-plus\/icons-vue/]
      }
    }
  }
})
