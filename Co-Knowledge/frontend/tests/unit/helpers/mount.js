/**
 * 组件测试脚手架。
 *
 * 目的：拆 UI 组件时能直接 `mount` 一个 `.vue`，而不用每个 spec 各配一遍
 * i18n / Element Plus / router / stub。
 *
 * 用法（⚠️ 文件头必须写 `// @vitest-environment jsdom`，全局 environment 是 node，
 * helper 不负责切环境）：
 *
 * ```js
 * // @vitest-environment jsdom
 * import { mountWithPlugins, expectNoI18nMisses, findByText } from './helpers/mount'
 * import LeftNav from '@/app/layout/nav/LeftNav.vue'
 *
 * const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })
 * expect(findByText(wrapper, '对话测试')).not.toBeNull()
 * expectNoI18nMisses(wrapper)
 * ```
 *
 * 三个设计决定（踩过坑，别改回去）：
 *
 * 1) **i18n 用真词条**（`@/i18n/zh.js`），不 mock。
 *    组件里写错键名（`$t('modules.kb.dockb2')`）时 vue-i18n 会把**键名本身**渲染成文本，
 *    断言文案的用例立刻红 —— 这正是仓里真实出过的 bug 类型。用 mock 就只会返回一个
 *    永远匹配的假字符串，把这类 bug 全放过去。`fallbackLocale: false` 同理：回落会让
 *    「en 里缺的键」悄悄翻成中文，测试就测不出来了（zh/en 键集一致已由
 *    `i18n.consistency.spec.js` 保证）。
 *
 * 2) **Element Plus 只注册用到的组件**，不 `app.use(ElementPlus)`。
 *    全量注册要拉 80+ 个组件（含 popper / 全量样式）并把它们装进每个被测实例，
 *    既慢又会带出与断言无关的副作用（例如 config-provider 的暗色侦测）。
 *    这里按 EP 的 `es/components/<name>` 单点引入，只装 `EP_BASE_COMPONENTS` 那几张。
 *    重型组件（el-table / el-upload / el-select…）不真渲染，注册成 **占位组件**
 *    （见 `EP_STUB_COMPONENTS`）—— 它们仍是「已注册的全局组件」，所以模板里
 *    `<el-table>` 会解析到占位件而不是退化成未注册元素 + Vue 警告。
 *    需要真渲染某个重型组件时，spec 用 `global.components` 覆盖即可
 *    （VTU 先装 plugins 再注册 `global.components`，后者覆盖前者）。
 *
 * 3) **router 默认就有**（memory history），默认给 `route: '/'`。
 *    `useRoute()` 在没装 router 的实例上返回 undefined，组件一渲染就炸；
 *    默认装一个 0 成本的 memory router 可以让所有组件 spec 用同一套写法。
 *    初始路由在 mount **之前** push 完并 `await isReady()`，组件首次渲染就能拿到
 *    正确路由（不是先 '/' 再跳）。不需要路由的用例传 `{ router: null }`。
 */
import { h } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises, mount } from '@vue/test-utils'
import { expect } from 'vitest'

import zh from '@/app/i18n/zh.js'
import en from '@/app/i18n/en.js'

// ── Element Plus ────────────────────────────────────────────────────────────
// 单点引入：只把下面这几张表拉进模块图。加组件 = 加一行 import + 加进表里，
// 别改回 `import ElementPlus from 'element-plus'`（会把整包都拖进来）。
import { ElAside } from 'element-plus/es/components/container/index'
import { ElMenu, ElMenuItem, ElMenuItemGroup, ElSubMenu } from 'element-plus/es/components/menu/index'
import { ElIcon } from 'element-plus/es/components/icon/index'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import { ElInput } from 'element-plus/es/components/input/index'
// 面包屑：知识库两个列表页（Kbase.vue / KnowledgeGraphPage.vue）的页标题都用它，
// 页标题文案是这两个页面的可见骨架，要在用例里真渲染、真断言
// （ElBreadcrumbItem 与 ElMenuItem 同理：子项也从父组件目录一起导出）
import { ElBreadcrumb, ElBreadcrumbItem } from 'element-plus/es/components/breadcrumb/index'
// 页签：图谱知识库页的「知识图谱 / 知识图谱模版」页签（knowledgeGraphtab.vue）——
// 页签文案与「不带 pills 类」是产品惯例的一部分，要真渲染才能断言
import { ElTabs, ElTabPane } from 'element-plus/es/components/tabs/index'

/** 默认注册的 EP 组件（轻量、断言里常要真渲染）。 */
export const EP_BASE_COMPONENTS = {
  ElAside,
  ElMenu,
  ElSubMenu,
  ElMenuItem,
  ElMenuItemGroup,
  ElIcon,
  ElButton,
  ElTag,
  ElInput,
  ElBreadcrumb,
  ElBreadcrumbItem,
  ElTabs,
  ElTabPane
}

/**
 * 重型组件的占位件。渲染成一个带 `data-ep-stub="<kebab-name>"` 的 div + 默认插槽，
 * 断言里可以用 `find('[data-ep-stub="el-upload"]')` 确认「这个组件被用到了」。
 * ⛔ 不要拿占位件断言真实行为（表格没行、上传没交互）——那种断言要换成真组件。
 */
export const EP_STUB_COMPONENTS = Object.fromEntries(
  [
    'ElUpload',
    'ElTable',
    'ElTableColumn',
    'ElSelect',
    'ElOption',
    'ElDialog',
    'ElDrawer',
    'ElTree',
    'ElDatePicker',
    'ElCascader'
  ].map(name => [name, createPlaceholder(name)])
)

function createPlaceholder (name) {
  const kebab = name.replace(/\B([A-Z])/g, '-$1').toLowerCase()
  return {
    name,
    setup (_, { slots }) {
      return () => h('div', { class: 'ep-stub', 'data-ep-stub': kebab }, slots.default ? slots.default() : [])
    }
  }
}

/** `app.use()` 这个插件即可按最小集注册 EP（`mountWithPlugins` 已默认装）。 */
export const ElementPlusLite = {
  install (app) {
    for (const [name, component] of Object.entries(EP_BASE_COMPONENTS)) {
      app.component(name, component)
    }
    for (const [name, component] of Object.entries(EP_STUB_COMPONENTS)) {
      app.component(name, component)
    }
  }
}

// ── i18n ────────────────────────────────────────────────────────────────────

export const TEST_MESSAGES = { zh, en }

/**
 * 造一个真词条的 i18n 实例（composition API 模式，与 `src/i18n/i18n.js` 一致）。
 * @param {{ locale?: string, onMissing?: (key: string) => void }} [options]
 */
export function createTestI18n ({ locale = 'zh', onMissing } = {}) {
  return createI18n({
    legacy: false,
    locale,
    // ⛔ 不回落：见文件头注释 1)。缺键就是把键名渲染出来。
    fallbackLocale: false,
    messages: TEST_MESSAGES,
    // 挂上 missing 处理器后 vue-i18n 不再往控制台刷警告，改由收集器转给断言
    // （`expectNoI18nMisses`）。
    missing: onMissing ? (_locale, key) => onMissing(key) : undefined
  })
}

// ── router ──────────────────────────────────────────────────────────────────

/** 路由记录用的空壳组件：左侧导航不需要渲染 RouterView，但记录必须有 component。 */
const BlankRoute = { name: 'BlankRouteView', render: () => null }

/**
 * 默认路由表：覆盖左栏菜单的全部目标 + `/:pathMatch(.*)*` 兜底。
 * 兜底是必要的：push 到未匹配的路径会被 vue-router 拒绝（`No match found`），
 * 而 `resolveActiveMenu` 的用例恰恰要试各种「不在菜单里」的路径。
 */
export const DEFAULT_ROUTES = [
  { path: '/', component: BlankRoute },
  { path: '/login', name: 'login', component: BlankRoute },
  { path: '/knowledge', name: 'knowledge', component: BlankRoute },
  { path: '/knowledge/detail/:id', name: 'knowledge-detail', component: BlankRoute },
  { path: '/knowledge/detail/:id/documents', name: 'knowledge-documents', component: BlankRoute },
  { path: '/graph', name: 'graph', component: BlankRoute },
  { path: '/graph/detail/:id', name: 'graph-detail', component: BlankRoute },
  { path: '/graph/edit/:id', name: 'graph-edit', component: BlankRoute },
  { path: '/graph/create', name: 'graph-create', component: BlankRoute },
  { path: '/graph/createTemplate/:templateId', name: 'graph-template', component: BlankRoute },
  { path: '/flow', name: 'flow', component: BlankRoute },
  { path: '/chat', name: 'chat', component: BlankRoute },
  { path: '/operators', name: 'operators', component: BlankRoute },
  { path: '/models', name: 'models', component: BlankRoute },
  { path: '/access', name: 'access', component: BlankRoute },
  { path: '/keys', name: 'keys', component: BlankRoute },
  { path: '/approve', component: BlankRoute },
  { path: '/:pathMatch(.*)*', component: BlankRoute }
]

/**
 * 造一个 memory history 的 router 并把它导航到 `initialRoute`。
 * @param {{ routes?: Array, initialRoute?: string | Record<string, unknown> }} [options]
 */
export async function createTestRouter ({ routes = DEFAULT_ROUTES, initialRoute = '/' } = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes })
  // 先 push 再 await：这样 `route` 在挂载前就稳定了（组件首次渲染即可断言）。
  await router.push(initialRoute)
  await router.isReady()
  return router
}

// ── mount ───────────────────────────────────────────────────────────────────

/**
 * 挂载一个组件，预先注入 i18n（真词条）+ Element Plus（最小集）+ router，
 * 并返回带诊断信息的 wrapper。
 *
 * @param {object} Component 已编译的 SFC / 组件定义
 * @param {object} [options]
 * @param {string | Record<string, unknown>} [options.route='/'] 初始路由（可带 query）
 * @param {Array} [options.routes] 自定义路由表（默认 `DEFAULT_ROUTES`）
 * @param {object} [options.router] 自备 router（传 `null` 表示不装 router）
 * @param {string} [options.locale='zh'] i18n 语言（`zh` / `en`）
 * @param {object} [options.i18n] 自备 i18n 实例
 * @param {object} [options.global] 原样透传给 VTU 的 `global`（`plugins` / `stubs` / `components` 会合并）
 * @param {object} [options.props] / [options.slots] / [options.attachTo] 等 VTU mount 选项
 * @returns {Promise<object>} VTU wrapper，另挂 `router` / `i18n` / `i18nMisses` / `flush`
 */
export async function mountWithPlugins (Component, options = {}) {
  const {
    route = '/',
    routes,
    router: providedRouter,
    locale = 'zh',
    i18n: providedI18n,
    global: globalOptions = {},
    ...mountOptions
  } = options

  const { plugins: extraPlugins = [], stubs: extraStubs = {}, components: extraComponents = {}, ...restGlobal } = globalOptions

  const i18nMisses = []
  const i18n = providedI18n || createTestI18n({ locale, onMissing: key => i18nMisses.push(key) })

  let router = providedRouter
  if (router === undefined) {
    router = await createTestRouter({ routes, initialRoute: route })
  } else if (router && router.currentRoute.value.matched.length) {
    // 自备 router：已经导航过（大多来自 `createTestRouter`）才等它就绪。
    // ⚠️ 一次都没 push 过的 router 不要 await `isReady()` —— 那个 promise 要等首次导航
    //    完成才 resolve，而首次导航由 `app.use(router)` 触发（发生在 mount 里），
    //    在这里 await 会把用例挂到超时。
    await router.isReady()
  }

  const wrapper = mount(Component, {
    ...mountOptions,
    global: {
      ...restGlobal,
      plugins: [ElementPlusLite, i18n, ...(router ? [router] : []), ...extraPlugins],
      stubs: { ...extraStubs },
      components: extraComponents
    }
  })

  // 诊断信息直接挂在 wrapper 上：spec 里一句 `expectNoI18nMisses(wrapper)` 就能用，
  // 不用再多解构一层（这几个键与 VueWrapper 自身的成员不冲突）。
  wrapper.router = router || null
  wrapper.i18n = i18n
  wrapper.i18nMisses = i18nMisses
  wrapper.flush = flush

  return wrapper
}

// ── 便捷断言 / 工具 ─────────────────────────────────────────────────────────

/** 等所有已排队的 microtask（组件里 `await` 过的 promise 回调等）落地。 */
export async function flush () {
  await flushPromises()
}

/** 把空白折叠成单空格并去掉首尾空白（模板换行/缩进不是行为，比较前先抹掉）。 */
export function normalizeText (value) {
  return String(value)
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * 归一化文本：把 `textContent` 折叠成单空格。
 * 直接比较裸 textContent 会被模板里的换行/缩进打败（`\n        对话测试\n      `），
 * 那是 HTML 排版噪声，不是行为。
 */
export function textOf (node) {
  return normalizeText(node.text !== undefined ? node.text() : node.textContent || '')
}

/**
 * 在 `root` 里按可见文案找元素（用于「菜单/按钮上出现的是文案而不是 i18n 键名」这类断言）。
 * @returns {object|null} DOMWrapper，找不到返回 null（便于 `expect(...).not.toBeNull()`）
 */
export function findByText (root, text, selector = '*') {
  const normalized = normalizeText(text)
  return root.findAll(selector).find(node => textOf(node) === normalized) || null
}

/**
 * 断言该组件渲染过程中**没有**解析不到的 i18n 键。
 * 拼错键名时 vue-i18n 会把键名当文案渲染出来，这条会先把键名列出来，
 * 比"某个文案对不上"更容易定位。
 */
export function expectNoI18nMisses (wrapper) {
  expect(wrapper.i18nMisses, `组件渲染时缺失的 i18n 键：${JSON.stringify(wrapper.i18nMisses)}`).toEqual([])
}
