# 模块接入说明：smart-factory → 专家 / `Agent开发. 评估`

本文档有两个主题，各自分"我们这边做了什么 / 需要你们配合什么"两半：

1. **页面接入**（第 1–7 节）：怎么把 `smart-factory/web` 挂到左侧栏的「专家」与
   `Agent开发. 评估` 上。我们这边的记录在 **第 1–4 节**，需要你们配合的在 **第 5–7 节**。
2. **模型配置对接**（第 8 节）：怎么让你们的引擎从框架取到模型配置，而不是靠手填 `.env`。
   **第 8.1 节**是我们的记录，**第 8.2 节**是当时提出的三处改动（现已落地，留作说明）。

第 9 节是开发态启动顺序，第 10 节指向"进产物"的对接要求。

两件事的结论都先说：页面接入**宿主侧只需要注册清单**（`/agent-dev` 与 `/experts`
两条路由本来就挂的是 `ModuleHost`，缺的只是"注册一个模块"这一步）；
模型配置对接**两侧都已完成**（你们已经在 `shared/framework/client.ts` 里接上模块面）。

> **2026-10-20 更新**：框架已删掉原生的「专家」页，`/experts` 改挂本模块的 `/agents`。
> 清单新增 `mounts[].entryPath` 用来指明"这个能力在模块里的哪一页"。
> 这一段不需要你们改任何代码——你们的 `/agents` 路由本来就在。

---

## 1. 接入怎么做

```bash
# 在仓库根执行。$COSIGHT_HOME 默认 ~/.cosight-harness（D26 = A）
mkdir -p ~/.cosight-harness/modules/smart-factory
cp docs/modules/smart-factory.module.json \
   ~/.cosight-harness/modules/smart-factory/module.json
```

然后**整页刷新浏览器**（⌘/Ctrl+Shift+R）打开 <http://localhost:4310/experts>
（专家页，落在模块的 `/agents`）或 <http://localhost:4310/agent-dev>。

- **必须整页刷新**，不能只切路由：模块清单走 `useModules()`，它的 `staleTime` 是
  `Infinity`（`framework/web/src/api/system.ts:50-58`），一个页面生命周期内只拉一次。
- **服务端不用重启**：`scanModules` 每次请求现读磁盘
  （`framework/server/src/modules/registry.ts:48`）。
- 扫描规则是**只扫一层**：`$COSIGHT_HOME/modules/<任意目录名>/module.json`。
  目录名不影响任何东西，真正的 `id` 取自清单内容。

改完用这条确认（不要跳过——见第 4 节的"最容易忽略的失败形态"）：

```bash
curl -s localhost:4300/api/modules | python3 -m json.tool
# 期望：modules 里有一项 id = "smart-factory"，invalid 为空数组
```

## 2. 清单里每个字段为什么是那个值

| 字段 | 值 | 说明 |
|---|---|---|
| `id` | `smart-factory` | 必须匹配 `^[a-z][a-z0-9-]{1,62}$`；全小写 |
| `name` / `description` | 双语 | **`zh-CN` 与 `en-US` 两个键都必填**，少一个直接判非法 |
| `entry` | `http://localhost:4110/` | iframe 的基址，见第 3 节 |
| `allowedOrigins` | `["http://localhost:4110"]` | 三条硬规则：必须是**裸源**（不带路径/查询串/尾斜杠）、必须**包含 `entry` 的源**、`entry` 的源必须**不等于宿主源**（D24 要求模块跨源，否则 sandbox 失去隔离意义） |
| `mounts` | `[{ capability: "experts", path: "/experts", entryPath: "/agents" }, { capability: "agent-dev", path: "/agent-dev" }]` | 宿主按 `capability` 选模块。`path` 仍是**声明式的元数据**（宿主路由表硬编码），`entryPath` **会**被消费：它把 iframe 落到模块内的那一页（见第 7 节） |
| `healthcheck` | `http://localhost:4110/` | 只被 `pnpm start` 的探活报告消费。缺了不影响功能，只是报告里显示"已注册，未声明 healthcheck" |

## 3. `entry` 必须写 `localhost`，不能写 `127.0.0.1`

这不是风格问题。他们的 `smart-factory/web/vite.config.ts` 没有设 `server.host`，
Vite 7 的默认值 `localhost` 在本机解析成 `::1`，于是**只绑 IPv6**：

```
$ ss -ltnp | grep 4110
LISTEN  [::1]:4110          ← 只有 IPv6

$ curl -o /dev/null -w '%{http_code}' http://127.0.0.1:4110/
000                          ← IPv4 回环上什么都没有
$ curl -o /dev/null -w '%{http_code}' http://localhost:4110/
200
```

清单校验**发现不了**这个问题——`http://127.0.0.1:4110` 是个合法裸源，也不等于宿主源，
`GET /api/modules` 照样返回合法。它只会在浏览器里表现为 **iframe 白屏**。

> **同网段其他机器访问宿主时**，清单仍是这份 `localhost`，不需要改。`GET /api/modules`
> 会在**请求主机名不是回环**时，把 `entry` / `allowedOrigins` / `healthcheck` 里的回环
> 主机名投影成请求方用的那个（如 `http://<module-host>:4110/`），本机访问则原样返回。
> 投影只发生在响应里，落盘文件与契约校验都按原值走（`registry.ts` 的
> `rebaseLoopbackManifests`）。前提是模块前端确实绑在所有网卡上——开发态 Vite 要
> `server.host: true`，产物态由 `module-web-server.mjs` 默认的 `--host 0.0.0.0` 保证。
所以 `framework/server/tests/module-manifests-doc.test.ts` 里专门钉了一条断言。

> 顺带：我们框架自己的前端（4310）有一模一样的成因，而且真的踩到了——
> `framework/web/playwright.config.ts` 原来探 `http://127.0.0.1:4310`，
> e2e 每次都卡在 `webServer` 60s 超时、一条用例都跑不到。现在那条探针改成了
> `http://localhost:4310`（后端仍探 `127.0.0.1`，Fastify 绑的就是 IPv4）。
> 更彻底的解法是两边各自在 vite 配置里显式 `server.host`，但那是另一件事，本文件不涉及。

## 4. 渲染链路（为什么宿主侧一行都不用改）

```
/experts
  → framework/web/src/app/routes.tsx                { path: 'experts', element: <ModuleHost capability="experts" /> }
  → ModuleHost.tsx                                 useModules() + pickModuleForCapability(...)
  → 清单 mount.entryPath = "/agents"               → <iframe src="http://localhost:4110/agents?..." />

/agent-dev
  → framework/web/src/app/routes.tsx                { path: 'agent-dev', element: <AgentDevPage /> }
  → framework/web/src/pages/AgentDevPage.tsx        <ModuleHost capability="agent-dev" />
  → 该 mount 没有 entryPath                         → <iframe src="http://localhost:4110/?..." />
```

`ModuleHost` 拼 iframe 地址的方式：以 `manifest.entry` 为基址；该能力声明了
`entryPath` 就用 `new URL(entryPath, entry)` 落过去（`entry` 自带的查询串保留，
`entryPath` 里同名参数优先）；然后 `searchParams.set('locale', <当前语言>)`，
再把**宿主当前 URL 的全部 query 原样合并**。所以宿主的
`/agent-dev?expert=abc&mode=evaluate` 会变成
`http://localhost:4110/?locale=zh-CN&capability=agent-dev&expert=abc&mode=evaluate`，
而 `/experts` 会变成 `http://localhost:4110/agents?locale=zh-CN&capability=experts`。

**`/experts` 还有一个额外行为**：smart-factory 的列表按框架「当前工作区」取数，
而切换工作区发生在宿主侧，iframe 收不到事件。所以这条路由开了
`reloadOnContextChange`——工作区或全局模型一变，宿主重建 iframe，页面重新拉一遍。

**最容易忽略的失败形态**：清单写错时 `GET /api/modules` 依然返回 **HTTP 200**，
只是把坏清单挪进 `invalid` 数组（`registry.ts:52-90` 的设计是"坏清单不阻断扫描"）。
前端此时**不会报错**，只是回到"模块尚未接入"的兜底文案。
所以第 1 节那条 `curl` 不是可选的——它和"页面看起来一样"是两种不同的排查信号。

## 5. 嵌入模式（已落地）

整站刚嵌进 iframe 时**同时出现两个左侧栏**（你们 220px + 我们 264–420px）。
现在你们已经按下面的方式关掉了自己的外壳（`web/src/shared/embed.ts` +
`App.tsx` 的 `!embedded && <aside>`），所以这一节保留为设计记录。

### 当时的改法

`smart-factory/web/src/App.tsx`：加一个"是否被嵌入"的判断，命中时不渲染
`<aside className="app-sidebar">`，只渲染 `<main>`。

```tsx
/**
 * 被别的宿主用 iframe 嵌进来时不渲染自己的侧栏与品牌，避免出现两层外壳。
 *
 * 用 window.self !== window.top 自动判定，而不是只认 ?embed=1：嵌入方无需做任何
 * 配合，也不会因为谁忘了带参数就退化回双栏。跨源下这个比较是**安全**的——
 * 只比较 window 引用，不读取 top 的任何属性，不会触发 SecurityError。
 * ?embed=1 保留为手动强制开关，方便我们自己单独验证嵌入态。
 */
const params = new URLSearchParams(window.location.search);
const isEmbedded = window.self !== window.top || params.get('embed') === '1';
```

然后 `{isEmbedded ? null : <aside className="app-sidebar">…</aside>}`。

宿主侧**不需要跟着改**：`ModuleHost` 会把 `entry` 自带的查询串保留下来，
所以将来要显式带开关，只需把清单里的 `entry` 改成
`http://localhost:4110/?embed=1` 即可（`new URL(entry)` 后只做 `set`，不清空已有参数）。
但按上面的自动判定，这一步也可以不做。

### 顺带请你们定一个我们定不了的问题

**拿掉侧栏 = 拿掉你们唯一的页面导航。** 嵌进宿主后，模块内部怎么从首页切到
「智能体创建 / 智能体运行」？两个方向：

- **(a) 宿主驱动**：我们用 `?mode=` 传意图，你们按参数渲染对应页。宿主已经有这个约定
  （见第 6 节），优点是 URL 可深链、可被宿主的"设计/评估/优化"按钮直接调用；
- **(b) 模块自带顶部分段控件**：你们自己在内容区上方出一排切换。宿主不参与，
  但宿主的深链能力就用不上了。

这两个不是纯技术取舍，取决于你们希望"嵌入态"是一个**受宿主编排的开发工作台**，
还是一个**自成一体的小应用**。请你们决定后我们再对齐 `?mode=` 的取值。

## 6. 深链约定（我们已经在转发，你们还没消费）

`AgentDevPage.tsx:9-21` 记录了宿主的路由约定：

| 宿主 URL | 意图 |
|---|---|
| `/agent-dev?mode=create` | 专家智能体创建 |
| `/agent-dev?expert=<id>&mode=design` | 设计 |
| `/agent-dev?expert=<id>&mode=evaluate` | 评估 |
| `/agent-dev?expert=<id>&mode=optimize` | 优化 |

宿主**不解析 `mode`，原样转发**（这正是 `ModuleHost` 把整段 query 拼给 iframe 的用意）。
但你们前端目前**不读任何 query 参数**（`HomePage.tsx:114` 是全文唯一的 `window.` 命中，
是 `window.getSelection()`，与 URL 无关），且 `App.tsx:41` 的 `path="*"` 会把一切
重定向回 `/`。后果：**专家卡片上的"设计 / 评估 / 优化"三个按钮现在点进来长得一模一样**，
都停在首页。

本轮这是预期行为（我们就想要首页）。但如果把模块挂在 `agent-dev` 上，这四个动作
迟早要区分——否则"评估"这个能力域等于没有入口。

## 7. 已知限制（不是 bug，是当前设计边界）

- **宿主 URL 不反映模块内部导航**：你们在自己的 iframe 里点侧栏跳到 `/agent-create`，
  宿主地址栏仍是 `/agent-dev`。宿主不实现 postMessage（`ModuleHost.tsx:15-27` 明确写了
  这三件"刻意不做"的事），模块 → 宿主**没有消息通路**。
  2026-10-21 起 sandbox 给了 `allow-top-navigation-by-user-activation`：用户**主动点**
  的整页跳转（设计页「返回」、卡片「使用」）可以带顶层一起走；脚本自己发起的顶层跳转
  仍被挡（`allow-top-navigation` 没给），所以"内部路由切换"仍然只影响 iframe。
- **宿主自己触发重渲染会重置模块**：`locale` 变化会让 iframe 的 `src` 变，iframe 重载，
  模块回到首页。可以接受，但宿主侧不加状态时这是必然。
- **`mounts[].path` 仍是死字段**：契约校验它、但没有代码消费它（我们 grep 过全仓）。
  真实路由硬编码在 `routes.tsx`。也就是说模块无法靠"声明一个 mount"引入新的宿主路由。
  **`mounts[].entryPath` 则真的会被消费**：它只决定"已经在宿主里的那条路由打开模块的哪一页"，
  同样不能新增宿主路由。它必须是以单个 `/` 开头的同源绝对路径——`//other-host` 会被契约
  直接拒绝（D24 的跨源白名单）。
- **本轮不解决双侧栏**：跨源 iframe 的内部样式改不了。宿主侧唯一零改动的手段是
  "把 iframe 加宽 + 外层 `overflow:hidden` 裁剪"，那要**硬编码你们的侧栏宽度 220px**，
  你们一改样式就错位——不值当，所以走第 5 节的正式改法。
- **会话页右上角有一小块是宿主的，不是你们的。** 那个「展开工作区文件」的悬浮按钮由宿主画在
  `<main>` 之上、浮在 iframe 的右上角（32×32，距内容区右缘与上缘各 8px，与面板的
  `--panel-inset` 同口径）；点开后右侧出现一块工作区文件面板，收起按钮在面板自己的标题栏上，
  那块悬浮按钮随即消失。面板内部自己分两栏：左边是目录树（基准 260px），
  右边是文件预览，多出来的宽度全给右边。
  **只在会话页（`/` 那条路由）出现**，别的页面没有。
  理由见 [`framework-decisions.md`](./framework-decisions.md) 的 D35：宿主与你们之间没有桥，
  我们画不进 iframe 里面，只能由宿主画在外面。
  **代价要说清楚**：你们以后在自己页面的右上角加东西（工具条、状态、按钮）**会被它压住**，
  而你们看不见我们的组件。如果那一步非要在那个角落，请告诉我们，我们改位置——
  这是能商量的一处优先级，不是不能动的东西。
- **面板打开时你们的 iframe 会被挤窄，请自己验一遍窄下来的样子。**
  面板宽度默认 = 上限 = **页面宽度的三分之一**（1440 的窗口 → 480px），可以拖窄到 320px，
  也可以**全屏展示**（那时铺满整个内容区，左侧栏留着）。
  面板打开期间，你们的 iframe 宽度就是"原来的宽度减去面板宽度"——**不是被盖住，是真的变窄了**。
  于是有两件事请你们自己确认：
  1. **大约 2/3 宽度下布局不塌**：侧栏 + 内容在这种宽度下的断点、横向滚动、
     图表/表格的宽度是不是还成立。
  2. **连续变宽撑得住**：打开/收起面板时留白有 300ms 过渡，那 300ms 里你们的页面是
     **逐帧重排**的（拖拽期间我们关掉了过渡，所以拖拽本身是逐帧跟手的）。
     如果你们的页面里有对 resize 敏感的图表或 canvas，请确认它不会在那 300ms 里疯狂重绘或报错。
  这条不是"能不能商量"的问题，是需求方明确要的形态（会话区跟着让开），
  所以只能请你们适配。理由见 D39（它推翻了 D35 当年"宁可盖住"的那条结论）。

## 8. 模型配置对接

### 8.1 模块面模型接口（已完成）与你们的落地状态

**写这份说明时的背景**：`smart-factory/server/src/config/index.ts` 的 `model` 字段是
从 `process.env` 直接拼的（`MODEL_NAME` / `MODEL_BASE_URL` / `MODEL_API_KEY`），
`getModel()` 在缺失时抛 `模型配置缺失：MODEL_...`；
`claude-adapter.ts` 在三个字段任一为空时抛
`模型配置不完整：需要 MODEL_NAME / MODEL_BASE_URL / MODEL_API_KEY`。
也就是说本机跑起来必然卡在这里，除非有人手抄一份密钥进 `.env`——既容易过期，
又把密钥散到了第二个地方。

**现状（2026-10-19 核对）**：这一节已经落地。`server/src/shared/framework/client.ts`
每个请求现读 `{COSIGHT_HOME}/.module-token` 去调框架模块面；
`server/src/modules/model/model.service.ts` 只代理 `GET /models`（列表不含明文密钥），
把上游异常统一翻成 502。下面的背景与三处改动**保留作设计说明**，不再是待办。

我们新增了一套**模块面**接口（与你们 `/api/smart-factory/v1/…` 对称的对外面），
门禁是"回环地址 + 一枚 `$COSIGHT_HOME/.module-token` 里的令牌"：

| Method | Path | 响应 |
|---|---|---|
| `GET` | `/api/framework/v1/models` | `{ items, activeId }`，**无明文密钥** |
| `GET` | `/api/framework/v1/models/active` | 当前生效模型，**含明文 `apiKey`**；没有则 `200 + data: null` |
| `GET` | `/api/framework/v1/models/:id` | 指定模型，**含明文 `apiKey`** |

**你们要用的是这三条 GET。** 模块面现在还开了模型的 `POST`/`PATCH`/`DELETE` 与一整套
工作区接口（`/api/framework/v1/workspaces/*`）——那些是给需要"帮用户把配置建好"的模块准备的，
与你们的场景无关，**不要顺手用**：你们只是读一份配置去起模型客户端，写平台配置的权限
对你们只有坏处（多一份炸开的面）。

完整字段表、错误码、可直接粘贴的 TS 客户端与 curl、轮换方法与残余风险，
都在 **[`module-facing-api.md`](module-facing-api.md)**——请以那份为准，本节不重复。

#### 字段对应关系

你们的 `ModelConfig`（`config/index.ts`）与模块面的字段是这样对上的：

| 你们的字段 | 模块面字段 | 说明 |
|---|---|---|
| `name`（即 `MODEL_NAME`） | `modelName` | 发给供应商的模型 id，也就是你们塞进 `settings.model` 的那个值。**不是 `label`** |
| `baseUrl` | `baseUrl` | **可能为 `null`**（表示用该供应商的官方地址），见 8.2 第 1 条 |
| `apiKey` | `apiKey` | 明文；没配过时为 `null` |
| `apiType`（现在硬编码 `'anthropic'`） | `protocol` | 已派生好，**别自己推断**，见 8.2 第 2 条 |
| — | `label` | 界面上的显示名，如「Sonnet 5.5」（对应你们前端 `MODELS` 的 `label`） |
| — | `id` | 框架侧的 uuid，适合做缓存键 |

`/api/framework/v1/models` 的列表项还额外带 `activeId`，一次调用就能预选中下拉项。

#### 令牌怎么用（三条硬要求）

1. **模块进程自己读 `$COSIGHT_HOME/.module-token`，不要注入成环境变量。**
   这不是洁癖：你们的 `claude-adapter.ts` 是
   `env: { ...process.env, ...anthropicEnv }`——令牌一旦进了环境，就等于交给了
   Claude Code 能调用的工具链，被工具调起的 agent 一条 `printenv` 就拿到了。
   读文件则只存在于你们的进程内存里，不被子进程继承。
   （也**不要**写进 `.env`、`launch.json` 的 `env`。）
2. **只认 `Authorization: Bearer <令牌>`**，Query 参数和自定义头都不认。
3. **别让前端拿。** 模块面拒绝了带 `Origin` 头的请求，而浏览器发的请求必然带 `Origin`——
   密钥只该留在你们的**服务端进程**里。前端要展示模型名，走你们自己的后端转一道。

### 8.2 当时提出的三处改动（均已落地，留作说明）

#### 第 1 处：`config/index.ts` 的 `ModelConfig` 来源

`getModel()` 现在是**同步**函数，`EngineContext.model`（`shared/engine/port.ts`）也是同步读的。
所以取配置**不能**在 `getModel()` 里现发 HTTP，做法应该是：

- **启动阶段** `await` 一次模块面的 `/active`，把结果缓存在进程内存里；
- `getModel()` 保持同步，读那份缓存。

这样 `port.ts` 与 `claude-adapter.ts` 都**不用改签名**（见第 2 处）。

顺带两件事：

- `ModelConfig.baseUrl` 现在被 `?? ''` 兜成空串，把"没配"和"配了个空串"混成了一种状态。
  模块面的 `baseUrl` 可能是 `null`（用户没填自定义网关，应该用供应商官方地址）。
  建议把类型放宽成 `string | null`，**不要**把 `null` 静默当 `''` 传给 SDK——
  那会变成"把请求发到一个空地址"这种最难查的形态。
- `.env` 建议**保留为回退**（本机调试、离线场景用得上），但要**定死优先级**、
  并且只在启动日志里说一次最终取到的是哪一路。
  "名字来自框架、密钥来自 `.env`"这种两边混着取的状态必须避免。
  同时把 `getModel()` 的报错文案改掉——它现在写着 `模型配置缺失：MODEL_...`，
  改成来源之后这句话会把排查的人指向一个已经不再读的东西。

#### 第 2 处：`claude-adapter.ts` —— **零改动**

它的字段名本来就对得上：`model.name` → `settings.model`，
`model.baseUrl` / `model.apiKey` → `anthropicEnv` 里的 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY`。
只要 `getModel()` 返回的是从模块面来的 `ModelConfig`，适配器不需要知道这件事。

唯一要复核的是 `apiType`：我们 grep 过你们的仓，它**只有两处命中且没有一处读它**
（`config/index.ts` 的接口定义 + 硬编码赋值）。所以现在不动它不会出问题。
但**如果哪天真要读它，必须读模块面的 `protocol`，不要自己从供应商推断**——
`azure-openai` / `ollama` / `openai-compatible` 都不是 Anthropic，
用户把激活模型设成 OpenAI 兼容的模型时，硬编码的 `'anthropic'` 会让你们
**静默**拿 Anthropic SDK 去打一个 OpenAI 端点，表现为一句语焉不详的上游报错。
模块面已经把 `protocol`（`'anthropic' | 'openai'`）直接给出来了。

**取不到配置时不要静默降级成空配置**，要 fail fast 并打一条指明令牌文件路径的日志。
空配置的失败形态是"上游报了个跟真实原因无关的错"，比启动失败难查得多。

#### 第 3 处（次要）：前端 `features/agent-create/mock.ts` 的 `MODELS`

那是写死的三条演示数据：

```ts
export const MODELS = [
  { value: 'claude-sonnet-5-5', label: 'Sonnet 5.5' },
  …
];
```

换成真实列表时，映射是 **`value ← modelName`、`label ← label`**（形状恰好一致，
`AgentCreatePage.tsx:42` 与 `:260` 两个消费点都不用改）。

**但前端要经过你们自己的后端**：模块面拒绝带 `Origin` 的请求，浏览器直连必然 403，
而且明文密钥本来就不该进浏览器。你们的服务端取 `/active`（要列表就取 `/models`），
转成 `{ id, label, modelName }` 再给自己的前端。

#### 启动顺序上的一个坑

模块面在**框架服务端（4300）起了之后**才可用。**用 `pnpm dev:all` 就不会遇到**——
它先拉起框架、探活通过后才起各模块。单独起你们的后端时要自己确保这一点，
否则启动阶段那次取配置会失败。

### 8.3 我们这边不做的事

- **不给你们的场景配写接口，也不需要你们用。** 上一轮这里写的是"模块面不开写接口"，
  **那句话已经过期**：模型与工作区现在有写接口了（D33，见 `module-facing-api.md` 第 3、4、6 节）。
  但你们是**只读消费方**（取配置起个模型客户端），一条写接口也别碰——多要一份写权限，
  进程就多一份被利用的价值。新增 / 修改 / 删除模型仍在框架界面里做
  （设置 → 模型设置；那块界面同时给出接口基址、令牌文件路径和一条可直接复制的 curl）。
- **不改 `smart-factory/` 下的任何文件。** 本节是交接说明，不是我们替你们改。

## 9. 开发态启动顺序

**推荐：在仓库根用 `pnpm dev:all`。** 它按 `docs/modules/smart-factory.launch.json`
把模块后端（4100）与前端（4110）纳入统一监督、统一收尾，并且**先起框架（4300）**——
模型配置要走模块面，框架没起时模块启动阶段那次读取会失败。

单独跑这个模块时，用它自带的零依赖脚本（`smart-factory/scripts/dev.mjs`）：

```bash
node smart-factory/scripts/dev.mjs setup     # 首次：装依赖、生成 .env、prisma generate、建库
node smart-factory/scripts/dev.mjs start     # 后台起前后端，日志在 smart-factory/.run/logs/
node smart-factory/scripts/dev.mjs status    # 端口与可达性
node smart-factory/scripts/dev.mjs stop
```

（仓库里**没有** `scripts/start-all.sh`；早期文档提到过这个名字，实际入口就是 `dev.mjs`。
`setup` 在读旧文档的人那里也容易漏，第一次跑必须先执行它。）

这样单独跑时，也要**自己先起框架**（`pnpm dev`）；原因同上：第 8 节的模型配置
取在模块**服务端**进程里，而 4110 上的前端既不读令牌文件、也过不了模块面的 `Origin` 校验。

## 10. 进产物这一层

开发态跑通与"能装进产物"是两件事。后者要的是生产启动命令、静态前端产物、
跨平台原生件与一份 `smart-factory.artifact.json`，逐条对照见
[`module-artifact-integration.md`](module-artifact-integration.md) §3。
当前 smart-factory **没有** artifact 清单，所以打包时会把它列为「未打进」。

## 11. 知识库 API Key（宿主侧已备好，你们不用改代码）

**我们这边做了什么**（2026-10-28）：

- 「设置 → 知识库路由设置」的每条路由新增一栏 **API Key**，与登录密码同一条 D26：
  明文只进 `$COSIGHT_HOME/.credentials.yaml`，界面只显示"已配置"，浏览器面永不回显。
- 服务端可用环境变量预置一枚**默认 Key**：先读 `COSIGHT_KNOWLEDGE_API_KEY`，其次读
  `CO_KNOWLEDGE_API_KEY`（就是你们 `server/src/config/index.ts` 里那个同名变量）。
- 模块面 `GET /api/framework/v1/rag-knowledge/active` 的响应新增 `apiKey`：**路由自己的
  优先，没配就回默认**。所以模块拿到的永远是生效的那一枚，不必自己判断用哪层。
  浏览器面只被告知"有没有默认"（`GET /api/rag-knowledge/defaults`），拿不到值。
- 出厂默认路由**不带** API Key，默认值只来自环境变量，不落库、不提交仓库。

**你们这边要做的**：没有代码改动。你们现在从自己的 `CO_KNOWLEDGE_API_KEY` 读，
两种情况都能工作：

| 场景 | 你们的配置 | 结果 |
|---|---|---|
| 知识与你们部署在同一套产物里 | 在产物目录的 `cosight.env` 写一行 `CO_KNOWLEDGE_API_KEY=ragk_...` | 框架与模块进程都继承到；框架拿它当默认，你们照旧读自己的 env |
| 只给框架配、模块另配 | 框架侧写 `COSIGHT_KNOWLEDGE_API_KEY=ragk_...`；你们自己的 env 写你们那枚 | 两边互不影响（框架命名空间优先于模块同名变量） |

开发态没有 `cosight.env`：在启动 `pnpm dev:all` 的 shell 里 `export CO_KNOWLEDGE_API_KEY=...`
即可，子进程会继承。**不要**把它写进仓库里的 `.env`、`launch.json` 或任何会被提交的文件。

如果以后想让"用户在框架设置里填的那一枚"直接生效（而不是靠环境变量对齐），
建议改成从模块面 `/active` 读 `apiKey`——那件事需要你们改代码，不由我们代做。
