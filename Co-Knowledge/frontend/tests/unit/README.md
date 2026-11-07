# 前端单元测试

**当前状态：可运行。** 共 **83 个 spec / 898 条用例**。

```bash
cd frontend
npm run test:unit          # = vitest run
```

配置在 `frontend/vitest.config.mjs`（vitest 5，`environment: 'node'`，`globals: true`，
`include: ['tests/unit/**/*.spec.js']`，别名 `@` → `./src`，插件 `@vitejs/plugin-vue`
只让 vitest 能编译 `.vue`，不动 vue-cli/webpack 那条链）。
需要 DOM 的 spec 在文件头用 `// @vitest-environment jsdom` 单独覆盖环境。

## 组件测试

组件 spec 一律走 `tests/unit/helpers/mount.js` 的 `mountWithPlugins()`，
不要自己 `mount()` 从头配插件。文件头至少写：

```js
// @vitest-environment jsdom        ← 否则没有 DOM，localStorage/useRoute 全都不在
import { mountWithPlugins, findByText, textOf, expectNoI18nMisses } from './helpers/mount'
import LeftNav from '@/app/layout/nav/LeftNav.vue'

const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })
expect(findByText(wrapper, '对话测试', '.el-menu-item')).not.toBeNull()
expectNoI18nMisses(wrapper)
```

`mountWithPlugins` 是 **async**（挂载前先 `router.push` 并 `await isReady()`，
组件首次渲染就能拿到正确路由），返回的 wrapper 上额外挂了
`router` / `i18n` / `i18nMisses` / `flush`。

### 脚手架 API

| 导出 | 说明 |
|------|------|
| `mountWithPlugins(Comp, opts)` | 挂载。`opts`：`route`（初始路由，可带 query）、`routes`、`router`（自备/`null` 关掉）、`locale`（`zh`/`en`）、`i18n`（自备）、`global`（透传 VTU，其中 `plugins`/`stubs`/`components` 会合并）、其余同 VTU mount 选项 |
| `createTestI18n({ locale, onMissing })` | 真词条的 i18n 实例（`fallbackLocale: false`） |
| `createTestRouter({ routes, initialRoute })` | memory history + 已就绪的 router |
| `ElementPlusLite` / `EP_BASE_COMPONENTS` / `EP_STUB_COMPONENTS` | 最小集 EP 注册插件及两张表（见下） |
| `flush()` | 等 microtask（组件里 await 过的东西）落地 |
| `textOf(node)` / `normalizeText(v)` / `findByText(root, text, selector?)` | 归一化文本与按文案查找 |
| `expectNoI18nMisses(wrapper)` | 断言该组件没有渲染出任何「解析不到的 i18n 键」 |

### 四条硬规矩（都是踩过的坑）

1. **i18n 用真词条**（`@/app/i18n/zh.js`），别 mock。组件里键名拼错时 vue-i18n 会把
   **键名本身**渲染成文案，断言文案的用例立刻红 + `expectNoI18nMisses` 点名；
   mock 只会返回一个永远匹配的假字符串，把这类 bug 全放过去。
   `fallbackLocale: false` 同理：回落会让「en 缺的键」悄悄翻成中文。
   （自备 `i18n` 时 `i18nMisses` 收集器不生效，此时别用 `expectNoI18nMisses`。）
2. **Element Plus 只注册最小集**，不 `app.use(ElementPlus)`：全量会把 80+ 组件
   和 popper/样式一起拖进来，慢且带无关副作用。要用新组件就往
   `helpers/mount.js` 的 `EP_BASE_COMPONENTS` 里加一行（`element-plus/es/components/<name>/index`）。
3. **重型组件（el-table / el-upload / el-select …）默认是占位件**，渲染成带
   `data-ep-stub="<kebab-name>"` 的 div + 默认插槽。可以确定「用到了没」，
   但**不能拿它断言真实行为**——那种断言要 `global.components` 覆盖成真组件：
   ```js
   import { ElTable } from 'element-plus/es/components/table/index'
   await mountWithPlugins(Comp, { global: { components: { ElTable } } })
   ```
4. **全局 environment 保持 `node`**：纯逻辑 spec 不该白跑 jsdom。
   组件 spec 逐个用文件头注释 opt-in。

jsdom 目前覆盖了本仓组件用到的 API（el-menu / el-table 等用法可直接渲染）；
真遇到 `ResizeObserver` / `matchMedia` 之类缺失报错时，再往 `helpers/mount.js`
里加一个幂等的 shim，并在这里记一笔。

### 断言要求

- 钉**行为**（渲染出的文案、高亮项、事件、localStorage 往返），不钉内部变量。
- 别写「挂载成功即通过」。写之前先想：**什么改动会让它红**；
  关键用例建议手工改坏一次源码确认真的会红。

## spec 分类

| 目录 / 前缀 | 覆盖 |
|---|---|
| `api.*.spec.js` | API 客户端、请求头、401 处理、SSE 帧切分 |
| `auth.*.spec.js` / `Login.spec.js` / `changePassword.spec.js` / `LeftNav.auth*.spec.js` | 本地账号登录、会话、守卫、强制改密 |
| `chat.*.spec.js` / `ChatHistoryPanel.spec.js` | 对话推理分段、Markdown 消毒、证据、多段历史与存储 |
| `graph*.spec.js` / `entity*.spec.js` | 图谱画布、布局、全屏、实体/关系抽屉、模板 |
| `flow*.spec.js` / `canvasNodeDrawers.spec.js` | 编排列表、画布、节点抽屉、几何与表高 |
| `kb*.spec.js` / `docKb*.spec.js` / `knowledgeGraph*.spec.js` | 知识库列表/详情、文件限制、选择与路由参数 |
| `model*.spec.js` / `modelManagement.spec.js` | 模型注册、连接测试、思考配置 |
| `remoteAccess.*.spec.js` / `LeftNav.spec.js` | 远程接入、API Key、导航与路由高亮 |
| `i18n.*.spec.js` | zh/en 键集一致、键完整性、冒号提示、远程接入文案 |
| `router.*.spec.js` | 路由与 UX 原型 0.1.12 对齐、登录跳转 |
| `theme.spec.js` / `StatusText.spec.js` / `studioDialogs.spec.js` / `confirm-once.spec.js` | 主题、状态、弹窗、二次确认 |
| `mountHelper.spec.js` | 脚手架自身：缺键收集器、locale 切换、EP 占位件与真组件覆盖 |

## 历史

- 首版（v1）前端没有测试工具链；两个 i18n spec 写好了却从未被执行过。
- 2026-10-14：接入 vitest，把 i18n spec 跑起来，并新增 chat 纯逻辑与 SSE 用例。
- 2026-10-14（下午）：补 `@vue/test-utils` + `@vitejs/plugin-vue` + `helpers/mount.js`。
- 2026-10-21 起：随 UX 原型迁移到 `app / pages / features / shared`，测试路径同步更新。
