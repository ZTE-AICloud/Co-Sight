# Co-Sight Harness 框架 · 任务清单（P0–P7）

**这份清单怎么用**：左边是阶段，右边是**可在仓库里核对**的交付物。状态一栏的判定标准不是"代码写完了"，而是"有测试钉住行为 + `pnpm run verify` 全绿"——只写了没验的东西一律算"进行中"。

**阶段编号**沿用 [framework-decisions.md](./framework-decisions.md) 里各处引用的 P0–P7（该文档在 D30 的选项说明中给出"完整方案 P0–P7 合计 31–40 人日"）。每个阶段下都写明了它覆盖哪几条需求与决策。

**一条命令验证全部**：

```bash
pnpm install && pnpm run verify      # typecheck + lint(--deny-warnings) + 三个包的全部测试
```

**当前基线（2026-10-29）**：`pnpm verify` 全绿；用例 **1165 个全过**——脚本 269、契约层 120、后端 417、前端 359。

---

## 0. 状态总览

| 阶段 | 内容 | 对应需求 / 决策 | 状态 |
|---|---|---|---|
| **P0** | 工作区结构与工具链 | D1 D2 D11 D12、D27=A | ✅ 完成 |
| **P1** | 设计系统 + 应用外壳 | 需求 1.1、D3 D6 D9 D23 | ✅ 完成（字体文件待补，见 §9.1） |
| **P2** | 契约层 + 后端地基 | 需求 2.1–2.3-1 的接口地座、D4 D5 D7 D16 D25 D26 | ✅ 完成 |
| **P3** | 工作区设置模块（前端） | 需求 1.2、D16 | ✅ 完成 |
| **P4** | 专家页端到端 | 需求 4.1–4.5 + 2.2、D13–D15 D17–D19 | ✅ 后端保留；原生界面已删除，`/experts` 改挂 smart-factory 的 `/agents`（D44）。需求 4.2 的「滑动按钮」随界面一并作废（见 §9.17） |
| **P5** | 设置模块：模型 / Agent 代理（前端） | 需求 1.3.2 / 1.3.3、2.3 / 2.3-1 | ✅ 完成 |
| **RAG** | 知识库路由设置：设置页签 + 侧栏跳转 + 模块面只读接口 | 需求旁支（与模型设置平级）、D51 | ✅ 完成（至多一条生效；模块面两个 GET；侧栏「知识库」按生效项在新标签页打开；见 §9.27） |
| **P6** | 模块接入（宿主侧） | 需求 1 的"嵌套展示"、2.4 相关、C2 D24 | 🟡 宿主侧完成，真实模块待他方交付 |
| **P7** | 启动脚本 + 打包 + 文档 | 需求 2.4 / 2.5、D27=A D29=A D31 | ✅ 完成（打包冒烟、`pnpm start` 别名均实跑通过；产物还能瘦 23 M 但有意不做，见 §P7 与 §9.21） |
| **UX** | 页面 UX 修复轮 | UX-1 / UX-2 / UX-3.1–3.6（见 §2.1） | ✅ 完成（浏览器实测 + 审查补漏，见 §UX） |
| **WF** | 会话区右栏：工作区文件预览 | D35 D36 D37 D38 D39 | ✅ 完成（宿主侧；三个只读端点 + 左右分栏面板 + 左缘可拖 + 挤窄会话区 + 全屏展示，见 §WF 与 §9.23） |
| **PKG** | 跨平台打包 + 安装启动脚本 | 需求 2.4 / 2.5、D40 | ✅ 完成（Linux 端到端真跑；**Windows 没跑过**，见 §PKG 与 §9.24） |
| **PKG-INSTALL** | 安装闸门：前置检查 → 装插件 → 启模块，异常即失败 | 需求 2.4 / 2.5、D45 D46 D47 | ✅ 完成（退出码 10/12/13；真实 CLI 跑通两轮幂等；Windows 仅单测） |

---

## P0 · 工作区结构与工具链 ✅

**交付物**

| 文件 | 作用 |
|---|---|
| `pnpm-workspace.yaml` | 工作区为 `framework/*`；`allowBuilds` 只放行 esbuild；`minimumReleaseAgeExclude` 由 pnpm 自动维护 |
| `tsconfig.base.json` | 严格档位：`strict` + `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes` + `verbatimModuleSyntax` 等 |
| `.oxlintrc.json` | D11=A；`--deny-warnings` 下带 override（测试文件放开 `no-explicit-any`、放行 `.css` 与 jest-dom 的副作用导入） |
| 根 `package.json` | `packageManager: pnpm@11.28.5`、`engines: node ^22.19.0 \|\| >=24`、`verify` 脚本 |

**三个包**：`framework/shared/`（契约，不构建、直接导出 `src/*.ts`）、`framework/server/`、`framework/web/`。D1/D2。

**验证**：`pnpm run typecheck`、`pnpm run lint`。

---

## P1 · 设计系统 + 应用外壳 ✅

**交付物**（均在 `framework/web/`，D3=A：CSS Modules + 自定义属性 + lightningcss）

| 位置 | 内容 |
|---|---|
| `src/styles/` | `tokens.css`（色板/字号/间距/动效曲线）、`reset.css`、`global.css`、`fonts.css` |
| `src/components/ui/` | `Button`(+`IconButton`)、`Tag`、`Avatar`、`Segmented`、`SearchInput`、`Skeleton`、`StatusPanel`、`Icon` |
| `src/components/shell/` | `AppShell`（skip link + 主面板内滚）、`Sidebar`、`NavItem`、`SettingsDialog` |
| `src/app/navigation.ts` | 五个导航项，字面量含逐字照抄的 `Agent开发. 评估`（ASCII 句点 + 单空格） |
| `src/i18n/` | `translate.ts` + `zh-CN` / `en-US` 词表（D28=B 双语） |
| `src/stores/ui.ts` | zustand：`locale`（持久化）/ `sidebarCollapsed` / 设置面板开关与页签 |
| `docs/design-tokens.md` | 逐条对照 UX 稿的 token 提取表（含 §7 文案逐字提取） |

**两处超出 UX 稿的新设计**（稿里没有交互态与按钮变体，属于 P1 引入的决定，需设计侧确认）：hover / focus-visible / active / disabled 的样式，以及 `primary / secondary / ghost` 三个变体。

**验证**：`harness-web` 的 `tests/ui-atoms.test.tsx`、`segmented.test.tsx`、`search-input.test.tsx`、`shell.test.tsx`、`settings-dialog.test.tsx`、`i18n.test.ts`、`lib.test.tsx`。

**补测试时修掉的两个键盘可达性 bug**（都是"测试写下去才显形"的那类）：

- `SettingsDialog.tsx` 的焦点陷阱**实际不生效**。它用 `querySelectorAll` 取可聚焦元素，选择器里的 `button:not([disabled])` 会把 `tabIndex={-1}` 的按钮（未选中的语言单选、未激活的页签）也算进来，于是"末项"落在真实键盘遍历到不了的位置，环绕分支永不成立——用户 Tab 到最后一个真实停靠点再按 Tab，焦点就掉到遮罩背后的侧栏上。同时挂载时焦点在面板容器（`tabIndex=-1`）上，直接 Shift+Tab 会退到触发按钮。现在改为按 `tabIndex >= 0` 且不在 `[hidden]` 子树里筛出真正的 Tab 序列，并把容器算作反向环绕的起点。`e2e/smoke.spec.ts` 里那条"Tab 12 次不出弹窗"的用例此前必然失败（尚未跑过，见 §9.10）。
- `Segmented.tsx` 在 `value` 不匹配任何选项时，每一项都成了 `tabIndex=-1`，整组从 Tab 序列里消失，键盘用户进不去。改为回退到第一项作为停靠点（但不把它标成选中）。当前两个调用点都做了值校验，属于潜伏缺陷。

一并删掉了 `Segmented.module.css` 里永远匹配不到的 `.option:disabled`（组件没有传 `disabled` 的入口）。

**同批修掉的第三个问题：错误文案把 404 说成"服务内部错误"**。`translateApiErrorKey` 的注释承诺逐段降级 `error.not_found.something_new → error.not_found → error`，但 `lookup` 只把**字符串叶子**当命中，而 `error.not_found` 是对象节点——于是服务端新增一种资源、词表没跟上时返回 `null`，调用方退到 `error.internal`。现在把「分组节点的 `default` 子键」接成了兜底路径（这套约定本来就写在词表里：`error.not_implemented.default` 一直存在、且一直没有任何读取方），并给 `not_found` / `conflict` 两组补上 `default`。改的是实现与两处**固化了旧行为**的断言，不是把它们放宽。

---

## P2 · 契约层 + 后端地基 ✅

**交付物**

| 位置 | 内容 |
|---|---|
| `framework/shared/src/contracts/` | `expert` / `workspace` / `model` / `agent-proxy` / `module` / `settings-schema` / `primitives` |
| `framework/shared/src/` | `envelope.ts`（统一信封 + `PageMeta`）、`errors.ts`（`AppError` 与错误码）、`bridge.ts`（桥接令牌契约）、`locale.ts` |
| `framework/server/src/config/` | `env.ts`（环境变量与校验）、`paths.ts`（`$COSIGHT_HOME` 解析与建目录） |
| `framework/server/src/db/` | `schema.ts`、`client.ts`、`migrate.ts` |
| `framework/server/src/repositories/` | workspace / expert / model-config / agent-proxy / app-state |
| `framework/server/src/routes/` | health / workspace / expert / model / agent-proxy / modules / bridge |
| `framework/server/src/` | `plugins/error-handler.ts`、`plugins/services.ts`、`http/reply.ts`、`http/validation.ts`、`bridge/session.ts`、`credentials/store.ts`、`modules/registry.ts`、`seed/*` |
| `framework/server/docs/architecture.md` | P2 的架构说明（D31） |

**已知偏差**：D7 原定 better-sqlite3，实现用的是 `@libsql/client` + drizzle（同样是本机单文件 sqlite）。需确认是否接受。详见 §9.6。

**验证**：`framework/server/tests/`（16 个文件 / 160 用例，含 `api-*.test.ts` 的路由级测试、`error-handler`、`credentials`、`bridge-session`、`module-registry`、`paths`、`seed`），`harness-shared` 的 11 个文件 / 84 用例。

---

## P3 · 工作区设置模块（前端）✅

**交付物**

| 位置 | 内容 |
|---|---|
| `src/features/workspace/WorkspaceDialog.tsx` | 工作区弹窗：列表（名称 / 当前徽标 / 绑定目录）+ 新建表单 + 二次确认删除 |
| `src/features/workspace/WorkspaceForm.tsx` | 新建 / 编辑表单（名称必填、目录可空且必须是绝对路径） |
| `src/api/workspaces.ts` | 列表 / 当前 / 新建 / 改名 / 切换 / 删除 + 缓存失效 |
| `src/components/shell/Sidebar.tsx` | 底部的"当前工作区"行是该弹窗的入口 |

**四个当时待定的问题，落成的答案**（都在 `tests/workspace-dialog.test.tsx` 里，该文件现共 17 例）：

- **界面形态**：弹窗内一个列表，不是卡片机。工作区是个位数到十位数的量级，卡片会浪费面积；每行要显示的信息（名称 / 是否当前 / 目录）一行放得下。
- **"当前工作区"存在哪**：**服务端**（`GET /api/workspaces/active`），不进 store。理由是"当前工作区"会被多个页面与后端共用（专家列表的可见性、使用计次将来都要读它），放前端 store 就会出现"两个标签页各有一个当前工作区"的错位。前端 store 只管纯界面偏好（语言、侧栏宽度、折叠）。
- **新建后是否自动切换**：**是**。用户"新建一个工作区"的意图就是"现在开始用它"，再让他点一次「切换到此工作区」是把实现细节推给用户。
- **删除当前工作区**：允许，但确认语里必须写明后果（"删掉之后会回到未选择工作区"），删完侧栏立刻回到空态。禁止删除会逼用户先切走再删，反而更容易出错。

**两处前后端约定**：目录留空送 `null` 而不是空串（空串在服务端会被当成"绑定到了当前目录"这类误判）；相对路径在前端就拦住，不等服务端 422——但服务端仍然校验（前端校验是体验，不是防线）。

**本轮补充：目录真的会被建出来（D32）**。此前 `directory` 只是一个字符串，**框架从来没建过目录**。
现在：

- `directory` 留空 → 框架在 `$COSIGHT_HOME/workspaces`（可用 `COSIGHT_WORKSPACES_ROOT` 覆盖）下
  按工作区名派生一个目录名并**创建**它，绑定它的 `realpath`；
- 填了绝对路径 → **只绑定、不创建**，也不要求它已存在（D16 那句话仍然成立）；
- `PATCH` 改名**不重命名目录**；`DELETE` **删掉框架自己创建的工作区根直接子目录**（连同内容），
  用户外部绑定目录只解除记录（D43）。

目录名从工作区名派生时会做 slug 化（`lib/slug.ts`），所以名字里的 `../../` 逃不出根目录——
这是**安全项**，不是美化项。规则、保留名与全部取舍见 [`workspace-design.md`](workspace-design.md)；
业务规则被提到 `services/workspaces.ts` 一处，两个面（浏览器 + 模块面）共用，
路由退化成"校验入参 + 调服务 + 包信封"。

前端只补了一句 hint（留空时会自动建一个同名文件夹），因为新增行为必须在界面上可见。
它在 `workspace-dialog.test.tsx` 里有断言钉住——只改行为不改文案，用户会照旧以为
"留空 = 不绑定"，然后奇怪磁盘上怎么多了一个目录。

**验证**：`framework/web/tests/workspace-dialog.test.tsx`（17 例）、`api-hooks.test.tsx`；
后端 `api-workspace.test.ts`（浏览器面；其中一例断言删除后目录确实不在）、
`api-module-workspace.test.ts`（模块面全套 CRUD + 名字带 `../../` 仍落在根内 +
删除后目录消失）、`workspace-directory.test.ts`（slug 纯函数的字符集/长度/保留名/代理对截断 +
分配循环的磁盘行为：碰撞 `-2`、大小写判重、realpath 收敛、根目录被删后自愈 +
删除的四种处置：框架目录连同内容删除、外部目录保留、`_public` 保留、符号链接只删链接）。

---

## P4 · 专家页端到端 ✅（界面已被 D44 取代）

> **2026-10-20**：原生的专家界面已删除，`/experts` 改挂 smart-factory 的 `/agents`
> （D44）。**后端 `/api/experts` 与预置种子保留**——cosight-viewer 的会话页专家选择器
> 还在用它。下面的界面交付物是历史记录，文件已经不在仓库里。

**交付物**

| 位置 | 内容 |
|---|---|
| `framework/server/src/routes/expert.ts` + `repositories/expert.repository.ts` | 列表查询（`filter` / `q` / 分页）、详情、`POST /experts/:id/use` 计次 |
| `framework/server/src/seed/data.ts` | 预置专家种子（D13=A 的"预置"页签依赖它） |
| ~~`framework/web/src/pages/ExpertsPage.tsx`~~ | 已删除（D44）。页头、筛选页签、骨架 / 空态 / 错误态、无限滚动、URL-as-state |
| ~~`framework/web/src/features/experts/ExpertCard.tsx`~~ | 已删除（D44）。166px 定高卡片、头像、名称、上传者、描述、多标签、四个常驻动作 |
| ~~`framework/web/src/api/experts.ts`~~ | 已删除（D44）。界面不再从框架侧取专家 |

**行为要点（历史）**：筛选与搜索词写在 URL 上且用 `replace`；搜索 250ms 防抖；非法 `?filter=` 退到 `全部`；「使用」= 计次 + 跳 `/?expert=<id>`，另三个动作跳 `/agent-dev?expert=<id>&mode=<action>`（D19=A）；翻页失败保留已加载卡片、只在底部报错。这些行为现在由 smart-factory 的 `/agents` 自己承担。

**验证（当前）**：`framework/web/tests/module-host.test.tsx`、`pages-routes.test.tsx` 覆盖
`/experts → experts 能力 → entryPath /agents`；`framework/server/tests/module-manifests-doc.test.ts`
钉住清单挂载；后端 `api-expert.test.ts` 继续覆盖 `/api/experts`。

**未做**：需求 4.2 里的「滑动按钮」——决策、设计、代码三处都没有它，需先澄清它是什么（见 §9.17）。

---

## P5 · 设置模块：模型 / Agent 代理（前端）✅

**交付物**

| 位置 | 内容 |
|---|---|
| `src/features/models/ModelSettingsPanel.tsx` + `ModelConfigForm.tsx` + `modelForm.ts` | 模型列表 / 新增 / 编辑 / 设为当前 / 删除 |
| `src/features/agent-proxies/AgentProxySettingsPanel.tsx` + `AgentProxyConfigForm.tsx` + `agentProxyForm.ts` | Agent 代理列表 / 新增 / 编辑 / 设为默认 / 删除 / `extra` 只读展示 |
| `src/features/config/` | 三个面板共用的部分：`ConfigList` 行、`ConfirmDelete`、`ConfigRowSkeleton`、`SecretInput`、`parse.ts`（数值与 URL 解析）、`issues.ts` |
| `src/api/models.ts` / `agentProxies.ts` | 列表 / 当前或默认 / 增删改 / 激活 + 缓存失效 |
| `src/features/models/ModelDetailView.tsx` | 只读详情（全字段；此前想看全字段必须点「编辑」进表单） |
| `src/features/models/ModuleAccessCard.tsx` + `src/lib/formatDateTime.ts`、`copyText.ts` | 模块接入信息卡：接口基址、令牌文件路径、可复制的 `curl`；折叠时不发请求 |

**三个当时待定的问题，落成的答案**：

- **密钥回显**：读接口**不返回**密钥，只返回"有没有"的状态。表单里密钥栏永远是空的，占位文案说明"留空 = 不改"。这条决定了三种请求体的区别，也都是有测试的：栏留空 → 请求体里**没有** `apiKey` 这个键（不动它）；点过「清除密钥」→ `apiKey: null`（显式抹掉），且再点一次可以撤销。
- **模型探测按钮**：**不进 v1**。词表里 `error.not_implemented.model_probe` 仍在，属于已知占位（§9.18）。
- **`extra`（模块私有配置）**：**只读展示**，一个可改的控件都没有。它是别的模块写进去的东西，框架代改等于替模块改它自己的配置；将来要走"模块声明字段 → 框架渲染表单"那条路（§9.12）。
- **Agent 代理的令牌**与模型的密钥同款策略：留空不带键、清除送 `null`，且**留空时连 `extra` 也不带**——否则一次普通的令牌轮换会把模块私有配置一起抹掉。

**校验分工**：数值范围、整数性、`http(s)` 协议都在前端拦住并挂到具体字段，但服务端仍用同一份契约（zod）再校验一次。前端校验是体验，不是防线。

**本轮补充（模块面对外接口的前端部分）**：后端新增了 `/api/framework/v1/*` 这张"模块面"
（供本机其他模块进程取模型配置与工作区，模型**含明文密钥**，门禁是回环 + `$COSIGHT_HOME/.module-token` 令牌）。
浏览器面 `/api/models/*` 一个字没动。前端跟着补了两块：**只读详情视图**（原来装不下全字段）
与**模块接入卡**（原来"怎么接"只写在服务端代码和文档里，模块作者在界面上看不到，于是就继续手抄密钥进 `.env`）。
接入卡**不新增任何接口**：接口基址取 `window.location.origin`，令牌路径取已有的 `GET /api/health` 的 `cosightHome`。
完整说明见 [`module-facing-api.md`](module-facing-api.md)。

**后续追加**：模块面**已开放写入**（模型增删改 + 工作区整套 CRUD，D33）。接入卡上那句
"这组接口是只读的"因此改掉了口径——现在它说的是"只读的消费方用三条 GET 就够，
不要顺手拿写权限"。写接口的爆炸半径见 `module-facing-api.md` 第 6 节。

**验证**：`framework/web/tests/settings-model-panel.test.tsx`（21 例）、`settings-agent-proxy-panel.test.tsx`（21 例）、`settings-dialog.test.tsx`（16 例）、`api-hooks.test.tsx`；后端 `api-model.test.ts`、`api-agent-proxy.test.ts`。

---

## P6 · 模块接入（宿主侧）🟡

**已就绪**（框架侧，需求 1 的"嵌套展示"）：`ModuleHost`（iframe + 沙箱白名单 + URL 参数下发语言）、`framework/server/src/modules/registry.ts`（扫描 `$COSIGHT_HOME/modules/*/module.json`、D24 跨源校验）、`routes/modules.ts`、`routes/bridge.ts` + `bridge/session.ts`（令牌由模块从**自己的源**铸造与交换，宿主不代持会话）。

**未做**：真实模块（`task-center` / `smart-factory-ui` / `agent-genesis` 等）由其他同事交付；模块侧要按契约提供 `module.json` 与跨源前端。

**一处需要说清的边界**（见 §9.11）：`framework/shared/src/bridge.ts` 定义了一整套 `host:init` / `module:*` 的 postMessage 协议（含类型白名单与构造器），但**目前没有任何消费方**——`ModuleHost` 明确不做 postMessage，模块自己调 `/api/bridge/token` 取令牌。所以"iframe 宿主"是完成的，"桥协议"是**只有契约、没有实现方**。

**已知缺口**：`MODULE_CAPABILITIES` 里有 `agent-eval`，但宿主**没有**对应路由——因为 `EXPERT_ACTION_KIND` 把 `design / evaluate / optimize` 三个动作都指向 `agent-dev`。如果"评估"最终是独立模块，需要补一条宿主路由与深链契约（见 §9.2）。

### 端口分配（2026-10-14 与 `smart-factory` 错开）

D24 要求模块跑在**与宿主不同的源**上，所以"端口怎么分"是模块接入的前置条件，不只是运维细节。当前分配：

| 用途 | 端口 | 出处 |
|---|---|---|
| 框架前端（Vite dev） | **4310** | `framework/web/vite.config.ts` 的 `WEB_PORT` |
| 框架后端 API | 4300 | `framework/server/src/config/env.ts` 的 `DEFAULT_PORT` |
| `smart-factory` 前端 | 4110 | `smart-factory/web/vite.config.ts` 的 `WEB_PORT`（2026-10-20 起由 5173 迁入 41xx 段） |
| `smart-factory` 后端 | 4100 | `smart-factory/server/src/config/index.ts`（同日由 3000 迁入） |
| 打包冒烟 | 4399 | `framework/scripts/smoke-package.mjs`（刻意与上面都错开） |

**为什么按段分**：4xxx 段按模块划分，一眼能认出是谁的服务——框架 43xx（API 4300 / 前端 4310）、smart-factory 41xx（API 4100 / 前端 4110）、cosight-viewer 48xx。5173 是 Vite 默认值，大量 AI 生成的项目也用它，容易撞车，所以不再占用。

**改这个端口要动三处**，漏一处就坏：`framework/web/vite.config.ts` 的 `WEB_PORT`、`framework/server/src/config/env.ts` 的 `readOrigins` 默认值（漏了的话开发态带 `Origin` 的请求会被浏览器按 CORS 拦掉，且**只在浏览器里坏**、curl 测不出来）、`framework/web/playwright.config.ts` 的 `WEB_PORT`。三处都写了相互指向的注释。

---

## P7 · 启动脚本 + 打包 + 文档 ✅

| 事项 | 状态 |
|---|---|
| 文档 | ✅ `docs/framework-decisions.md`、`docs/task-list.md`（本文件）、`framework/web/docs/design-tokens.md`、`framework/server/docs/architecture.md` |
| 启动路径（D27=A） | ✅ `framework/scripts/start.mjs`（294 行） |
| 开发态总启动 | ✅ `framework/scripts/dev-all.mjs`（988 行）+ `lib/module-launch.mjs` / `lib/port-guard.mjs` / `lib/module-build.mjs`（274 行） |
| 打包脚本（D29=A） | ✅ `framework/scripts/package.mjs`（385 行）+ 双归档读写器 `framework/scripts/lib/archive/` |
| 冒烟脚本 | ✅ `framework/scripts/smoke-package.mjs`（379 行，默认端口 4399，且**拒绝**在默认端口上跑） |

**D27=A 的边界怎么落地的**：`pnpm dev` 仍是**唯一**的开发态入口，`framework/scripts/start.mjs` 服务的是另一件事——
把**装配态**拉起来（服务端 + 已构建的前端静态产物）。同一份脚本按目录特征自动分辨两种布局，不靠参数：

```
产物布局（解压后）：<root>/start.mjs + <root>/server + <root>/web
仓库布局（本仓库）：<repo>/framework/scripts/start.mjs + <repo>/framework/server + <repo>/framework/web/dist
```

仓库布局下它等价于"用生产模式跑一遍源码"，用来在打包前暴露"dist 没构建 / 静态托管路径不对"这类只在生产模式才现形的问题。
选项：`--port/--host/--home/--log-level/--app-dir/--web-dir`（均有同名 `COSIGHT_*` 环境变量）。

**它不管"把模块也启动起来"，这是刻意的**：模块**运行时清单**契约（`contracts/module.ts`）里只有 entry / capability / healthcheck，
**没有启动命令字段**；凭空发明一个属于改契约。所以脚本只扫 `$COSIGHT_HOME/modules/<id>/module.json`、按清单里的
healthcheck 探活，如实报告"已注册 / 可达 / 不可达"，探活失败不影响启动、也不影响退出码。

模块的启动方式没有进契约，而是登记在**旁挂的开发编排清单** `docs/modules/<id>.launch.json` 里，
由开发态总启动脚本 `pnpm dev:all`（`scripts/dev-all.mjs`）消费——见 [`dev-all.md`](dev-all.md)。
因此边界是**分开的而不是放宽的**：装配态（`pnpm start`）依旧只探活，拉起模块只发生在开发态。

**清单里那段可选的 `build` 是后补的**（取舍记在 D34）：有的模块开发态入口**就是产物**，
而产物是 gitignore 的，`git pull` 拉到了源码、本机还在跑旧包——页面缺了同事刚合的功能，
现象却是"页面没更新"，很容易被读成"功能没做"。所以把"启动前刷一遍产物"写成清单字段，
由脚本按**源码与产物的时间**判断该不该重建（`--rebuild` 强制、`--no-build` 跳过）。
失败方向是**宁可少起一个**：构建失败或输入清单写错时该模块的服务不启动，不拿旧产物骗人。

**打包为什么是"自包含"的**：服务端的 `build` 只是 `tsc --noEmit`，跑起来的是 TypeScript 源码（靠 tsx 运行时转换），
`harness-shared` 同理。所以 `pnpm package` 必须连同**已解析好的依赖树**一起交付——用
`pnpm deploy --filter harness-server --prod` 产出生产依赖树（workspace 依赖被实体化，不依赖源仓库存在），
再把 tsx 补进去（它是 devDependency，但服务端以源码形态运行、运行时离不开）。代价是产物体积大。
归档自己写（不调 `tar`/`zip` 命令）是为了跨平台与**可校验**：写完在同一个进程里读回来逐条比对，
"产出一个看起来正常的坏包"是这一步最坏的失败模式。

**真实运行结果**（本轮实跑，非推断）：

```text
$ pnpm run smoke:package
步骤 1/6  打包          条目 8312 条（符号链接 230），原始 72.6 MB
                        tar.gz 21.2 MB / zip 26.1 MB
步骤 2/6  确认端口空闲   端口 4399 未被占用
步骤 3/6  系统 tar / unzip 独立读取器交叉验证
                        条目数与打包清单完全一致；入口可执行位与 3 个关键符号链接均还原
步骤 4/6  从 tar.gz 解压的树启动并断言 HTTP   /api/health 就绪 → 首页为 HTML 且引用的脚本可取 → 干净关停
步骤 5/6  从 zip  解压的树启动并断言 HTTP   同上
步骤 6/6  清理临时目录
冒烟通过。
```

> 上面这一版是 **P7 当时的输出**（冒烟 6 步、8312 条目、230 条软链、21.2 MB）。
> 当前流水线的数字是 7 步、7908 条目、**0 条软链**、29.5 MB —— 见 §PKG 的证据一节。

仓库布局下也单独跑过一次（`pnpm start` 这条 npm 别名本身也跑过，不只是 `node framework/scripts/start.mjs`），
确认生产态真的在托管前端产物：

```text
$ pnpm start --port 4403
  布局      仓库布局（服务端 …/framework/server）
  前端产物  …/framework/web/dist
GET /api/health → 200
GET /            → <!doctype html><html lang="zh-CN">…
GET /assets/index-C7uo_LiO.js → 可取
```

**装配与归档的四个约束**（都是实测撞出来的，改这条流水线前先看这里）：

1. **给 staging 补装 tsx 时会被供应链策略挡住**。`pnpm deploy` 出来的 staging 目录**不继承**根
   `pnpm-workspace.yaml` 的 `minimumReleaseAgeExclude` 放行名单，于是 pnpm 11 的"发布满一定天数"校验会以
   **「fastify 发布不满最小天数」**为由拒绝安装——哪怕用的就是仓库自己锁定的版本。脚本用
   `--config.minimumReleaseAge=0` 关掉这项校验：这一步只是把**仓库已锁定的版本**装进一份临时目录，
   不引入新的版本选择，不扩大风险面。理由写在 `package.mjs:169-174` 的注释里。
2. **staging 必须落在仓库内**（现在在 `.package/staging`）。pnpm 装依赖优先走硬链接，而硬链接不能跨文件系统：
   实测本仓库与 `/tmp` 是两个设备（`stat -c %d` → 64529 vs 64768），`ln` 直接报 `EXDEV: 无效的跨设备链接`。
   落到 `/tmp` 时 pnpm 只能退回复制，整棵依赖树重写一遍。`.package/` 已进 `.gitignore`（第 164 行），
   `PACKAGE_DIR` 旁有注释写明这条约束。
3. **`pnpm deploy` 写下的 workspace 依赖是 `harness-shared@file:///home/…` 这种形态**——既不是合法 npm spec，
   又把打包机的目录结构泄漏给使用者。打包时改写成 `file:./node_modules/harness-shared`（`package.mjs:184-191`）。
4. **符号链接（已被 D40 消解，留在这里是因为它解释了一段历史）**。`server/node_modules` 下曾有
   230 个符号链接，系统 `unzip` / `tar` 能还原，但 Windows 资源管理器一类工具一般不还原——
   解压后 `tsx` 落成 0 字节文件、启动即退，而报出来的错和软链看不出关系。当时产物内的 README
   只能写「优先用 tar.gz」，等于**把责任推给用户**。D40 之后产物里一条软链都没有
   （`--config.node-linker=hoisted`，实测 230 → 0），zip 与 tar.gz 等价，README 里那段警告已删。
   这件事改由**打包期断言**守住「整棵树 0 条软链」，不再依赖用户选对解压器。
   见 §PKG 与 [`packaging.md`](packaging.md) §4。

**220 M 里约 23 M 纯粹是为了在运行时转换 TypeScript**（`esbuild` 12 M + `@esbuild/linux-x64` 11 M，tsx 的运行期依赖）。
唯一有效的一刀是打包时用 esbuild 把服务端打成单文件 JS；没做，理由见 §9.21。

**上一版记在这里的那个断点（`COSIGHT_WEB_DIST` 默认指向 `<cwd>/public`，没有脚本把 `dist` 缩进去）已经消掉**：
`start.mjs` 在两种布局下都会把 web 目录显式指到正确位置（仓库布局指 `framework/web/dist`，产物布局指 `<root>/web`），
不再依赖 `readWebDist` 的 `<cwd>/public` 默认值。上面两次实跑的"首页是 HTML"就是这条的证据。

---

## UX · 页面 UX 修复轮 ✅

**这一轮改的是外观与手感，不改数据与路由**。需求逐条口述（见 [framework-decisions.md §2.1](./framework-decisions.md)），下面记每条"改成了什么"以及**它被什么钉住**——纯视觉的条目 jsdom 量不出来（没有布局），所以分成两类证据：能写成断言的进测试，量不出布局的那些用真实浏览器量。

| 需求 | 改动 | 证据 |
|---|---|---|
| UX-1 折叠图标与 dsh 一致 | `Icon.tsx` 删掉 `collapse`/`expand` 两条路径，加 `panelLeft`（照抄 dsh `ui-primitives/src/icons/index.tsx:81` 的 artwork） | `shell.test.tsx`「图标与名字都不随状态变」；浏览器实测：展开 / 折叠两次抓 `innerHTML` 完全相同 |
| UX-2 分割线可拖拽 | 新增 `lib/sidebarWidth.ts`（唯一写入口 `clampSidebarWidth`）、`shell/SidebarResizer.tsx`（指针 + 键盘） | `sidebar-resize.test.tsx`（10 例）、`sidebar-width.test.ts`（5 例）；浏览器实测：280 → 拖到 420 夹住、拖回 264 夹住、松手后不动、折叠再展开仍是 380 |
| UX-3.1 每行四张 | `--grid-cols: 6 → 4`；断点 1399 / 1049 / 749 | 浏览器实测 1440→4、1280→3、1024→2、700→1 列 |
| UX-3.2 上传者与名称左对齐 | `ExpertCard` 头部改成头像 + 一列（名称 / 上传者），`--avatar-md` 作 `min-height` | `experts-page.test.tsx`「上传者与名称同处头像右侧的一列」（断言那一行 `<p>` 的父节点 = `<h3>` 的父节点）；浏览器实测：名称左缘 360 = 上传者左缘 360（头像右缘 352，间距 8） |
| UX-3.3 按钮描边 / 蓝字 / 悬浮背景 / 横线分隔 | `Button` 新增 `outline` 变体；`.actions` 加 `padding-top: 8px` + `border-top` | 浏览器实测：描边 `1px #DCE8EA`、字色 `#0a66c2`、悬浮 `rgb(25 147 255 / 8%)`、按下 `14%`、分隔线 `1px` |
| UX-3.4 悬浮阴影 | 新增 `--shadow-card-hover`（不复用"选中"阴影） | 浏览器实测：`rgba(13,139,211,.25) 0 6px 16px -6px`（向下偏移，读作"浮起来"） |
| UX-3.5 不展示「预置」角标 | 角标与 `experts.presetBadge` 词条一起删除 | `experts-page.test.tsx`「预置与否都不在卡片上挂角标」 |
| UX-3.6 页头重排 + 水印 | 创建按钮与搜索框移到标题下一行（按钮最左 / 搜索最右），筛选页签再下一行；水印改「按专家名称搜索」 | 浏览器实测：标题底 65 → 按钮与搜索框 top 69 → 页签 top 119；`experts.search.placeholder` 的断言本来就读词表 |
| UX-3.6 追加：标签多色 + 位置 | 六色标签底色，按标签文字稳定分配（`tagTone.ts`）；标签行 `margin-top: auto` + `margin-bottom: 8px` | `tag-tone.test.ts`（8 例）、`experts-page.test.tsx`「同一标签同色 / 不同标签不同色」；浏览器实测：标签行底 → 分隔线距离正好 **8px** |

**改测试的三处，都是需求推翻了旧行为**（不是把断言放宽）：

- `shell.test.tsx`「折叠按钮切换状态并换图标」→ 改为**图标与名字都不变**，状态反馈落在侧栏宽度上。dsh 三个状态画的是同一枚图标，UX-1 要的就是"和它一致"。
- `experts-page.test.tsx`「预置专家带角标，非预置的不带」→ 改为**两者都不挂角标**，并保留一条"卡片没被顺手丢掉"的断言。
- 卡片头部的结构变化让"描述为空时整行不渲染"那条的计数（`<p>` 个数）依然成立——上传者那一行仍是唯一另一个 `<p>`。

**一条"看着像有、其实没有"的断言被补上了**：UX-3.2 原先只有 `expect(within(card).getByText('李工'))`——那只证明"上传者在卡片里"，
把上传者挪回卡片左缘（也就是 UX-3.2 明确要改掉的那个旧形态）之后它照样通过。左对齐本身是布局、jsdom 量不出来，但
**"上传者与名称在同一列里"是 DOM 结构、量得出来**，于是补了 `author.closest('p')?.parentElement === h3.parentElement` 这一条。
这是本轮唯一"既有断言其实盖不住需求、而需求本来能盖住"的地方。

**顺手修掉的两个真问题**：

- **根 `lint` 会扫到别人的目录**：`oxlint ... .` 把 `smart-factory/` 等**别的同事**的模块也扫了，其中 `smart-factory/server/src/config/index.ts` 有一条 `import/no-unassigned-import` 错误，于是 `pnpm run verify` 恒红。已把 `lint` / `lint:fix` / `format:check` 收到 `harness-shared harness-server harness-web scripts`，与 `typecheck` / `test` 的 `pnpm -r` 范围一致。
- **外壳测试的桩"一个信封喂所有接口"不再成立**：`GET /models`、`/workspaces`、`/agent-proxies` 的 `data` 是**裸数组**（服务端 `sendOk(reply, await services.models.list())`）。桩返回对象时，`ModelSettingsPanel` 的 `models.map(...)` 直接抛错，整棵设置弹窗被路由错误边界接管——表现成"设置打不开"。已在 `stubAnyApi` 里按路径分派（列举接口给 `[]`，单例接口给 `null`）。这一条同时暴露了一个**值得收的失败模式**：读接口形状不对时，崩的是整棵弹窗而不是那块面板（见 §9.19）。

**代码审查后补的两件事**（都是本轮自己写的东西里的真问题，不是"顺手优化"）：

- **拖拽会在 `pointercancel` 之后卡死**（`SidebarResizer.tsx` 的 `endDrag`）。原来三行的顺序是"先释放捕获、再清状态"，而
  `releasePointerCapture` 对一个**已经不在捕获中**的 pointerId 会抛 `NotFoundError`（规范如此，Chrome 实测确认：
  未捕获过的 id 不抛、已释放过的 id 抛）。`pointercancel` 恰好就是"指针已被浏览器收走"那种情形，于是释放那一行抛出的异常
  让后面两行永远执行不到，后果不是"少清一个标记"：
  - `dragging` 卡在 true → 之后**不按任何键**、鼠标划过那 8px 就触发 pointermove，宽度跟着鼠标乱变（幽灵拖拽）；
  - `onDraggingChange(false)` 发不出去 → 侧栏的 `.resizing` 一直挂着，宽度过渡整场会话被关掉，折叠/展开/拖拽全变瞬移。

  两者都不可自愈。改成**先清状态、把释放包进 try/catch**（失败本就是我们要的结果），并补了 `onLostPointerCapture` 与卸载清理
  （拖到一半被折叠 → 手柄卸载 → 也要把 `resizing` 还回去）。测试侧：`sidebar-resize.test.tsx` 新增"收尾"一组，
  其中一个用例在实例上装了一个**必抛**的 `releasePointerCapture`——jsdom 里所有指针捕捉方法都不存在，不这样做这条分支永远走不到。
  已验证：把修复还原成旧写法，该用例立刻变红（不是恒真断言）。

- **卡片按钮的蓝字不达 WCAG 对比度**（无障碍审查发现）。需求 UX-3.3 要"蓝字表示可点"，我第一版直接用稿里的
  `--color-primary` `#1993ff`——它在白底上只有 **3.15:1**，悬浮 2.89、按下 2.71，而 12px 属于正文尺寸，阈值是 **4.5:1**。
  `--color-primary` 在稿里的三种用法（边框、图标、历史项底色）都是**非文字**，3:1 就够；拿它当文字用的那天阈值悄悄变了。
  新增 `--color-primary-text: #0a66c2`（同色相、压明度）：三态分别 5.69 / 5.21 / 4.89，全部过线；取的是"同时压住按下态"的**最浅一档**
  （再浅一档 `#0b6fd1` 在按下底上掉到 4.29）。加了 `tests/token-contrast.test.ts` 把这一类问题变成断言——
  jsdom 不算层叠后的颜色，"这段字在那个底上读不读得清"只能靠人眼，所以它只以评审口头意见的形式存在过；
  现在它读 `tokens.css` 自己算相对亮度，并且专门有一条断言"旧取值 `#1993ff` 会被判不达标"，防止有人改回去时顺手把期望值调低。

一并按无障碍审查补了：拖拽手柄的 `aria-valuetext`（裸数字没有单位，读屏只会念 "280"）与 `aria-controls`（`<aside>` 补 `id`）。
审查提的其余几条**没有改**，理由都记在 §9.20——包括"描边对比度 1.25:1 要不要压到 3:1"这一条，那是有意不改的。

---

## WF · 会话区右栏：工作区文件预览 ✅

**需求**：会话内容区的右上角加一个"展开右侧边栏"的图标（新建对话态、进入对话态各一个），
点开后在右侧预览工作区里的文件；写法参考 dsh（`http://127.0.0.1:3080/` 会话区右栏的"工作区"）。

**这一轮有一件事比界面重要**：它是框架**第一次去读用户工作区里的文件**。在此之前三份文档
（`workspace-design.md` §7、`workspace-api.md` §11.6、`module-facing-api.md` §8）都写着
「不读工作区目录里的任何内容」——那句话在这一轮之后**只剩后半段成立**，三处口径都改了。
界面反而是最不难的部分。

### 三条先定下来的事（见 [framework-decisions.md](./framework-decisions.md)）

| 决策 | 落成 |
|---|---|
| **D35** 面板画在**宿主侧** | 会话页是同事模块的**跨源 sandbox iframe**，且宿主**刻意不做 postMessage 桥**（D24）——宿主既读不到 iframe 里的状态，也画不进它里面。于是按钮与面板都由宿主画：绝对定位在 `<main>` 之内（`.main` 加 `position: relative`），按钮浮在 iframe 右上角。当年写的"**覆盖而不挤压**"已被 D39 推翻 |
| **D36** 三个端点只开**浏览器面**，并单独加**回环门禁** | 模块面（`/api/framework/v1`）**不开放**——消费方是框架自己的界面，而"读走用户文件内容"比"改配置"更靠近数据本身，不该跟着令牌的爆炸半径一起走。文件浏览**额外**要求 `Host` 与来源 socket 都是回环 |
| **D37** **不跟随软链**，没有例外 | 与 dsh 的又一处刻意分叉（dsh 的 `read` 明确允许读到工作区外）。一条没有例外的规则让"读的是哪个文件"不需要推理；列目录时软链仍然**看得见**（`type: "other"`），只是点不开 |
| **D38** 面板**左右分栏 + 左缘可拖** | 目录树与预览**同时**在屏幕上（树是"在哪个目录"，预览是"文件里是什么"，浏览时这两条要同时在）；宽度可拖。**推翻 D35 顺带写下的"宽度固定、不做拖拽调宽"**——那条是照抄 dsh，而 dsh 不谈宽度是因为它的右栏由 dock 布局管，我们不做 dock（D35） |
| **D39** 面板**挤窄会话区**（而不是遮盖）+ 宽度上限取**页面的三分之一** + **可全屏** | 三条都是需求方在用过之后提的，逐条推翻/修正了本轮早先的取值：①`<main>` 加 `padding-right` = 面板宽度，会话区真的变窄（**推翻 D35 的"宁可盖住"**，代价是那 300ms 过渡里跨源 iframe 逐帧重排）；②上限从写死的 960 改成 `页面宽度 / 3`（下限 320，**默认 = 上限**），于是默认位置上往左拖是空操作——取舍，不是 bug；③标题栏加一个全屏开关，铺满**内容区**（左侧栏留着），全屏期间不渲染手柄、不动留白（退出那一帧不用重排） |

### 后端

| 文件 | 内容 |
|---|---|
| `server/src/services/workspace-files.ts`（新） | 路径解析与包含、读文本、读图片。**包含规则只有这一份** |
| `server/src/routes/workspace-files.ts`（新） | 三个 GET + 回环门禁（`onRequest`）；只做"校验入参、调服务、包信封" |
| `shared/src/contracts/workspace-file.ts`（新） | 三个响应的 zod 契约 + **三个上限常量** |
| `server/src/app.ts` | 与 `workspaceRoutes` 同前缀注册 |

四个上限：条目 **2000**（超出截断 + `truncated`）、文本 **512 KiB**（只读前一段，`size` 仍报真实大小）、
图片 **2 MiB**（`413`）、二进制探针 **8 KiB**（不上契约，客户端看不见）。
二进制判定**两条判据**（前 8 KiB 含 NUL，**或**整段不是合法 UTF-8），图片**按内容认**
（魔数表 + WebP 的 RIFF 判定 + SVG 文本前缀），都不按扩展名——扩展名是用户随手改的。

三处容易写错、专门写了注释的地方：

- **截断时不能用致命解码直接判"是不是文本"**：按字节切可能正好切在一个中文字符中间，
  一个正常的中文文件会被报成 `415`。实现是依次丢掉尾部 1–3 字节再试，而**容忍范围仅限这一次重试**。
- **图片读回来要按实际长度再判一次上限**：`statSync` 与 `readFileSync` 之间文件可能变大，
  信 `stat` 那个数就等于信一个过期的值。
- **`readSync` 只读前 N 字节**，不是 `readFileSync` 再切——一个 10 GB 的日志会先把内存吃满。

### 前端

| 文件 | 内容 |
|---|---|
| `components/shell/WorkspaceFilesToggle.tsx`（新） | 会话区右上角的悬浮按钮，只在 `/` 渲染；面板打开时**它自己不渲染**（任何时刻只有一个切换控件） |
| `features/workspace-files/WorkspaceFilesPanel.tsx`（新） | 标题栏（工作区名 / 刷新 / 全屏开关 / 收起）+ 主体；主体是**左右分栏**：左目录树（基准 `260px`，窄端可与右栏一起收）+ 右预览，多出来的宽度全给右边；`role="complementary"` 见下。宽度是行内样式，全屏时写成 `'100%'` |
| `features/workspace-files/FileTree.tsx`（新） | 披露式目录树（`<button aria-expanded>` + 嵌套 `<ul>`，**不是** `role="tree"`）；被预览的那一行标 `aria-current="true"` + 底色加粗，是左右两栏之间唯一可见的连结点 |
| `features/workspace-files/FilePreview.tsx` / `FileStates.tsx` / `workspaceFiles.ts`（新） | 文本/图片预览、加载与失败态、排序与格式化。头部**只有文件名**——完整路径由左边选中的那一行表达，不在这里重复 |
| `components/ui/ColumnResizer.tsx`（新，从 `SidebarResizer` 抽出）、`features/workspace-files/WorkspaceFilesResizer.tsx`（新）、`lib/filesPanelWidth.ts`（新）、`lib/usePageWidth.ts`（新）、`features/workspace-files/useFilesPanelWidth.ts`（新） | 泛化的拖拽手柄（`edge: 'start' \| 'end'` 决定向左/向右拖是变宽还是变窄），侧栏与文件面板共用；指针捕获的释放顺序（**先清状态再 `releaseCapture`**）是抽出来而不是复制一份的主要理由。宽度换算只有 `lib/filesPanelWidth.ts` 一处、取值只有 `useFilesPanelWidth()` 一处——**面板与 `<main>` 的留白必须拿到同一个数**，各算一遍就会出现一条说不清来源的夹缝 |
| `api/workspaceFiles.ts`（新）、`stores/ui.ts`、`i18n/messages/{zh-CN,en-US}.ts`、`Icon.tsx` | React Query 封装（懒加载是**结构性**的：没展开的节点不渲染，也就没有那个 query）；`filesPanelOpen`、`filesPanelWidth`、`filesPanelResizing`、`filesPanelFullscreen`（**都不进 `partialize`**——宽度放 store 是为了"收起再打开还记着"，不持久化是为了与 `sidebarWidth` 同口径；`filesPanelResizing` 与 `filesPanelFullscreen` 必须离开面板，因为 `<main>` 的留白同时受它们影响，而 `<main>` 在 `AppShell` 里）；一组 `files.*` 词条；`panelRight` 与 `maximize` / `minimize` 图标 |

**只有真实浏览器才测得出来的坑（都已修）**：

1. `<aside>` 在 HTML-AAM 里**只有不是 `main`/`article`/`nav`/`section`/`aside` 的后代时**
   才映射成 `complementary`。本面板正是在 `<main>` 里，所以默认会落成 `generic`，
   `aria-labelledby` 无处附着——面板对读屏软件等于没有名字。显式写了 `role="complementary"`
   （显式 role 优先于 HTML 的默认映射）。
2. 分栏之后**长行把右栏顶出容器**：右栏里是 `white-space: pre` 的代码，而分栏容器 `.columns`
   是 flex 子项，`min-width: auto` 的 flex 子项下限是**内容的 min-content 宽度**——一行
   1200px 的 README 会把它撑到 1200px 以上，超出面板右缘，被 `.main` 的 `overflow: hidden`
   裁掉。表现是"长行不滚动、直接看不见了"，而 jsdom 不做布局，**一条单测都不会红**。
   修法是 `.columns` 的 `min-width: 0`，让宽度回到由 flex 分配决定，长行交给 `.textBody`
   自己横向滚。**这是本轮唯一一个纯靠真浏览器量出来的缺陷。**
3. **挤压之后"这一条挤了多少"也要真量**（D39）：留白与面板等宽不能说，得看**iframe 的实际
   宽度**是不是正好少了那么多——`padding` 加错元素（比如加在 `<main>` 里包一层的 div 上）
   在 jsdom 里同样一条都不会红，在浏览器里就是"会话区没动、面板自己飘在旁边"。
   真浏览器脚本里那两条断言（`iframe 宽 = 原宽 − 面板宽`、`iframe 右缘 == 面板左缘`）
   就是为这一条存在的。
4. **全屏的 `width: 100%` 量的是包含块，而包含块是 `<main>` 的 padding box**——
   也就是"内容区 + 让出的那条留白"，正好等于整个内容区。这一点要是理解成"内容盒"，
   全屏时右边就会留下一条与留白等宽的空洞，而单测里 `style.width === '100%'` 仍然是绿的。
   真实浏览器脚本量的也正是"面板宽度 == `main.clientWidth`"。

**一个测量上的坑（写下来省得下一个人也踩）**：留白有 300ms 过渡，所以面板宽度**瞬间**到位、
而会话区宽度是**过渡出来**的。在过渡途中量 iframe 会拿到一个中间值，
"全屏后 iframe 一像素都没动"这条断言就会以一个**假失败**暴露出来（我第一版脚本正是这样红的）。
脚本里在每一次改宽度之后都等了 450ms 再量。

### 证据

**测试**：后端 `tests/api-workspace-files.test.ts` **31 例**（列目录 6 / 路径逃逸 7 / 读文本 8 /
读图片 4 / 工作区状态 3 / 回环门禁 3），后端全套 **27 文件 322 例全绿**；
前端 `tests/workspace-files-panel.test.tsx` **36 例**（入口 3 / 目录树 5 / 预览 6 / 分栏 3 /
拖拽调宽 7 / **挤压会话区 4** / **全屏展示 4** / 空态与失败 4）、
`tests/files-panel-width.test.ts` **13 例**（全部按页面宽度参数化）、
`tests/sidebar-resize.test.tsx` **12 例**（手柄抽出后原封不动，证明这不是一次改写而是搬运），
三个文件合计 **61 例全绿**；
前端全套 **22 文件 384 例通过 + 1 条既有红灯**（见 §9.23）。`typecheck` 与 `lint`
（`oxlint --deny-warnings`）全绿。

**真实浏览器实测**（Playwright + chromium，1440×900，前端 4310 + 后端 4300 都在跑）——
这一轮的几条关键取舍**都是布局问题，jsdom 量不出来**，所以必须真跑。
本轮的脚本是 `/tmp/wf-panel-check.mjs`（上一轮那个 `wf-split-check.mjs` 的断言全部过期，
已删除而不是留着），**44 条断言全过**：

| 量的是什么 | 结果 |
|---|---|
| 面板默认宽度 | **480**（= 1440 / 3） |
| 留白 vs 面板 | `<main>` 的 `padding-right` = `480`，与面板**同一个数** |
| 会话区（iframe） | **1150 → 670**，正好少了 480：**挤压，不是遮盖** |
| iframe 右缘 vs 面板左缘 | **951 vs 951**（贴合，没有重叠也没有缝） |
| 分栏 | 左栏 `260`，右栏吃满剩余；**合成宽度 = 面板宽度** |
| 面板右缘 vs `<main>` 右缘 | **1431 vs 1432**（钉在内容区右缘，不越出视口） |
| 长行 | 右栏**没有**横向溢出面板（右栏右缘 == 面板右缘），两栏宽度之和 == 面板宽度 |
| 目录层缩进 / 选中标记 | 根层 `8px` → 子层 `22px`；点开后左栏**恰好一条** `[aria-current="true"]` |
| 面板打开后 | 那个悬浮按钮**从 DOM 里消失**（任何时刻只有一个切换控件） |
| 默认位置往左拖 80px | **纹丝不动**（默认已在上限，取舍见 D39） |
| 往右拖 120px | `480 → 360`；留白 `360`；iframe 回来 `120px`（`790 = 1150 − 360`） |
| 窄端的两栏 | 面板 `360` 时左栏 `203` / 右栏 `156`（按比例一起收，不是右栏剩一条缝） |
| `Home` / `End` | **320** / **480** |
| 全屏 | 面板宽 **1150 == `main.clientWidth`**（铺满内容区）；左缘 `281` ≈ 内容区左缘 `280`，**侧栏留着** |
| 全屏时的 `padding-right` | 仍是 **480**（刻意不动） |
| 全屏前后的 iframe | **670 → 670**（一像素都没重排——退出全屏那一帧也就不用重排） |
| 全屏时的手柄 / `aria-pressed` | 手柄**不在 DOM 里**；`aria-pressed` `true` ↔ `false` |
| 窗口变宽到 2400 | 宽度**不会自己变**；`End` 之后 `800`（= 2400 / 3），iframe 右缘 == 面板左缘 |
| 窗口拉窄到 1200 | 越界的宽度被**夹回 400**，留白同步夹回 |
| 收起面板 | 留白 `0`，会话区恢复原宽 |
| 收起再打开 | 宽度还是拖出来的那个值（在 1440 下被夹成 **480**）；**不是全屏** |
| `/experts` | 没有这个按钮，也没有面板 |

**接口实测**（真实进程，非 inject）：

```bash
curl -s "http://127.0.0.1:4300/api/workspaces/<id>/files?path=../../etc"   # 403 FORBIDDEN
curl -s -H 'Host: evil.example' "http://127.0.0.1:4300/api/workspaces/<id>/files"  # 403 loopback_only
curl -s -H 'Host: evil.example' "http://127.0.0.1:4300/api/workspaces"     # 200（这一刀没切到别处）
```

### 与 dsh 的分叉，一条一条记着

| dsh 有 | 我们 | 为什么 |
|---|---|---|
| `read` 允许读到工作区外 | **拒**（不跟随软链 + `realpath` 判包含） | 它的消费方是 cc 的资源地址，我们不是那个场景 |
| change feed watch（文件变了自动推） | **不做**，只有刷新按钮 | 面板的语义是"现在磁盘上是什么样"，推流要一整套订阅与失效模型 |
| 行分页（大文件按行翻） | **不做**，单页 + 截断提示 | 预览的目的不是读完，是"是不是这个文件" |
| tab 停靠系统（dockkit + renderer 注册表） | **不做**，右栏同时只开**一个**文件（没有多 tab） | 那要一整套 dock 系统，收益不成比例。注意这与 D38 的分栏不冲突：分的是"目录树 / 预览"，不是"多个文件各占一格" |
| 拖拽调宽 | **做了**（钉在面板左缘，`320` ～ 页面宽度的三分之一） | 分栏之后要左栏导航 + 右栏代码同时看得下，固定宽度做不到；上限取比例是 D39 改的，见 D38 |
| 每 session 持久化 | **不做**，宽度只活在这次会话里 | 与侧栏宽度同一口径（`sidebarWidth` 也不持久化）；展开集合与预览目标跟着面板的挂载周期走（关掉再打开回到根目录），**但宽度不跟着走** |
| 隐藏点文件 / 尊重 `.gitignore` | **如实显示，不过滤** | 这是用户的目录，替他们藏东西只会让人以为文件丢了 |

---

## PKG · 跨平台打包 + 安装启动脚本 ✅

**需求**：「设计整体的打包脚本，以及安装启动脚本，可以通过打包后的包，让用户在 Linux 或
Windows 上安装并启动」。三个已确认的选择：**一份通用包**（同时含两平台原生件）／
**不自带 Node 运行时**（安装只做预检 + 下载指引）／范围 **linux-x64 + win32-x64**。

**开工前先量出来的两个硬缺口**（决定了这一轮的主体，详见 D40）：

- 产物**事实上只能跑 Linux x64**：依赖树里只有 `@libsql/linux-x64-gnu` 与 `@esbuild/linux-x64`，
  而这两个都是原生包（libsql 用 `@neon-rs/load` 的 `currentTarget()` 拼包名再 `require`）。
- 依赖树是**符号链接编织的**：tar 里 230 条软链、zip 里 8312 条。Windows 自带解压器与
  7-Zip 默认都不建软链，`tsx` 会落成 0 字节文件 → 启动即退。当时 README 里那句
  "请优先用 tar.gz"就是这个坑的自白——把责任推给了用户。

### 交付了什么

| 产物 | 内容 |
|---|---|
| 用户侧脚本（唯一真源 `scripts/artifact/`） | `install.sh` / `install.cmd`（Node 预检 → 数据目录 → 配置模板生成）、`start.sh` / `start.cmd`（薄壳）、`cosight.env.example` |
| `start.mjs` | 新增 `--init`、`--self-check`、`--config <path>` / `--no-config`；启动时硬校验 `engines.node` |
| `package.mjs` | 双平台安装（`--os=linux --os=win32 --cpu=x64`）+ 零软链（`node-linker=hoisted`）+ 归档内断言 |
| `server/package.json` | `engines.node`（产物里唯一读得到的版本要求，根清单不进产物） |
| 文档 | 新增 `docs/packaging.md`；产物内 `README.md` 重写为"Linux 一条路 / Windows 一条路"；D40 |
| 新增测试 | `scripts/tests/`（40 → 49 条：版本区间、产物常量、配置解析、脚本编码行尾、BOM、**import 闭包**）、`server/tests/file-mode.test.ts`、slug 保留设备名与 BOM 清单用例 |

### 证据（都是实跑出来的）

- **`pnpm package`**：7908 条目、**符号链接 0 条**、tar.gz **29.5 MB** / zip **33.7 MB**
  （改造前 22.3 MB），四个平台原生件（`@libsql/{linux-x64-gnu,win32-x64-msvc}`、
  `@esbuild/{linux-x64,win32-x64}`）都在。
- **用系统 `tar` / `unzip` 独立读回**（不是用仓库自己的归档读器）：条目数与清单一致；
  `.cmd` 是 CRLF 且**非 ASCII 字节 0 个**；`.sh` 的 CR 0 个；入口 `0755`、`.cmd` 与模板 `0644`。
- **`pnpm smoke:package`**：系统解压 → `sh install.sh` 真的建出数据目录与 `cosight.env` →
  往里改 `COSIGHT_PORT=4400` 后 `./start.sh` **监听 4400**（证明配置被真的读进去了，
  而不是"文件躺在那儿"）→ `/api/health`、首页 HTML、首页引用的脚本可取 → 干净关停；
  tar 与 zip 两棵解压树各跑了一遍。
- **Node 版本闸门三级优先级实测**：配置文件 4399 / 真实环境变量 4398 / 命令行 4397，
  三级各自赢一次。守卫不是空转——故意把 `engines` 漂成一段测试不认的写法，测试立刻红。
- **import 闭包守卫非空转**：把 `ENTRY_SCRIPT_SOURCES` 里的 `lib/text.mjs` 临时删掉，
  `entry-imports` 测试立刻红（这条测试本身就是因为这个文件差点漏搬才补的）。

### 顺带修的四类"只在 Windows 上发作"的问题

都是**本机复现不了**的，所以一律"判定抽成纯函数 + 喂 `'win32'` / `0o666` / BOM 字节"：

1. **权限自检每次启动都误报**（Windows 上 `statSync().mode` 恒为 `0o666`）→
   `server/src/lib/file-mode.ts` 的 `checkSecretFileMode`，Windows 降级成一条 info。
2. **原子写的 chmod 没有 try/catch** → 抽 `chmodBestEffort`，与 `ensureDirectory` 共用一套策略；
   这条不修，在吞 chmod 的文件系统上表现是"写不进令牌、服务起不来"。
3. **带 BOM 的 `module.json` 被静默判非法**（记事本存"UTF-8"就带 BOM）→
   `stripBom` 用在 registry、module-probe、launch.json 与 `cosight.env` 四处。
4. **Windows 保留设备名** → `lib/slug.ts` 里 `CON` / `NUL` / `COM1` 这类接一个 `-ws` 后缀。

### 与批准方案的两处偏差（都写在这里）

1. **平台信息走 CLI 旗标，没有写进 `pnpm-workspace.yaml`**（方案里写的是后者）。
   两者都能让 deploy 出双平台原生件，但写进配置文件会让**仓库开发态的安装**也多拉两份
   可选依赖（约 +20 MB，每个开发者都变大），而我们只需要打包那一次。代价是"平台清单在命令里"，
   所以它由 `ARTIFACT_TARGETS` + `deployPlatformArgs()` 统一生成，有测试钉住。
2. **`lib/text.mjs` 是这一轮新加的文件**，而它一开始**没被登记**进搬运清单——
   也就是说，差点打出一个"`start.mjs` 在用户机器上 `ERR_MODULE_NOT_FOUND`"的包。
   发现后补上，并新增 `scripts/tests/entry-imports.test.mjs`：它从 `start.mjs` 出发顺着相对
   import 走一遍，要求闭包与清单**双向一致**。这类"本机毫无征兆"的漏搬，从此不再靠记性。

### 明确没做到的事

**没有在 Windows 上跑过**。本机是 Linux，没有环境，所以文档里不写"已验证"，
只写"没验过"和一份人工验收清单（`docs/packaging.md` §10）。替代证据是：打包期断言把
三类最容易中的错打死在打包机上；机制是读 `@neon-rs/load` 与 esbuild 源码得出的、并写成了测试；
Windows 的行为差异用纯函数守卫钉在 Linux 上。

---

## PKG-MOD · 产物里的模块（cosight-viewer 真进包）✅

**触发**：装完包打开 `http://127.0.0.1:4300/` 后两处不对——「新建对话」落在观测页，
smart-factory 的端口没起来。查下来是同一件事：**产物里没有任何模块**（详见 D41）。

**这一轮做的是通用机制，不是给 cosight-viewer 打特例**：

| 产物 | 内容 |
|---|---|
| `docs/modules/<id>.artifact.json` | 装配态清单（schema v1）：进包哪些文件、构建怎么做、装好后用什么命令起。**存在即进包**，没有硬编码名单 |
| `lib/artifact-spec.mjs` | 解析 + 严校验：未知字段报错、`cwd` 不得越出模块目录、`node` 换成当前解释器、只支持 `{{dataDir}}` |
| `lib/artifact-modules.mjs` | 判定 → 构建（旧了才建）→ 依赖完整性断言 → 展开条目（零软链） |
| `start.mjs` | 产物布局下变成**多进程监督**：按 priority 起模块 → 等 readyPath → 起框架；`--no-modules`；`--init` 后同步 `module.json` 进数据目录 |
| 文档 | `packaging.md` §6、`module-artifact-integration.md`（给同事）、D41 |

**证据（都是实跑出来的）**

- `pnpm test:scripts`：**79 条全绿**（49 → 79，新增 30 条：清单校验、运行时/打包两个解析方向、
  扫描与优先级冲突、include/exclude 展开、依赖完整性、符号链接拒绝、必需路径的相对基准、
  模块目录名与 `start.mjs` 常量同源）。
- `pnpm lint`：0 warning。
- `pnpm package`：条目 **19579**（其中符号链接 **0**）、原始大小 **151.8 MB**、
  tar.gz **44.4 MB** / zip **53.6 MB**；输出明确列出「已打进：cosight-viewer」与
  「未打进（缺少 artifact.json）：smart-factory」。`client/dist` 旧了 → 打包时真的重建了。
- `pnpm smoke:package --skip-package` 七步全过：解压后 `modules/cosight-viewer/`
  的两份清单与启动入口都在、`module.json` 的 entry 端口 4830 与清单一致；启动后
  `4830/health` 2xx、首页 HTML、bundle 里有 `"/chat"`（capability → 路由的映射）、
  `/api/modules` 已注册；关停后 4300 与 4830 **两个端口都释放**。
- 模拟安装段（`install.sh --home` → 写配置 → `start.sh`）同样拉起并关停了模块。

**明确没做**：没改 `smart-factory/` 与 `cosight-viewer/` 的任何源文件；smart-factory 进包
等模块方补生产链路（缺口逐条写在 `module-artifact-integration.md` §3）。
Windows 仍然没跑过——这一轮新增的只有 JSON 清单与 Node 端逻辑，没有新的平台相关代码。

---

## PKG-SF · smart-factory 进产物（linux-x64 真跑通）✅

**触发**：用户要求"智慧工厂打包后可以用"。上一轮（PKG-MOD）只做到通用机制，
smart-factory 因为缺生产链路没有进包；这一轮**不改 `smart-factory/` 任何文件**，
在宿主侧把链路补齐。

**做了什么**

| 产物 | 内容 |
|---|---|
| `docs/modules/smart-factory.artifact.json` | 多服务清单：`server` + `web`、构建两条、数据库模板、附加件、必需路径、可执行件、`platforms: [linux-x64]`、`startAfter: framework` |
| `scripts/artifact/module-web-server.mjs` | 一个端口同时做静态托管、SPA 回退、`/api` HTTP 反代与 WebSocket 升级代理 |
| `scripts/artifact/module-db-init.mjs` | 启动前幂等复制数据库模板到 `$COSIGHT_HOME` |
| `lib/artifact-spec.mjs` | schema v1 扩展：多构建、assets、database、dependencyRoots、required、executable、顶层 env、`prepare`、`startAfter`、`platforms`、`{{frameworkUrl}}` |
| `lib/artifact-modules.mjs` | 打包期生成模板库、搬运附加件、校验依赖与可执行位 |
| `start.mjs` | 准备步骤 → 立即模块 → 框架 → 延迟模块；按平台闸门跳过 |
| `smoke-package.mjs` | 多服务探活 + smart-factory 的四条链路（代理 / SPA / WS / 建库） |

**证据（实跑）**

- `pnpm test:scripts`：**115 条全绿**（本轮新增的覆盖：清单扩展、多构建、assets、
  database、dependencyRoots、可执行件，以及静态托管 / 代理 / WS / 建库两个辅助脚本）。
- `pnpm lint`：0 warning；`pnpm run typecheck`：3 个工作区全过。
- `pnpm package`：条目 **33003**（符号链接 0）、原始 **573.5 MB**、
  tar.gz **208.2 MB** / zip **224.1 MB**；输出列出「已打进：cosight-viewer, smart-factory」，
  smart-factory 标注「仅支持 linux-x64」；`server/dist` 与 `web/dist` 均为最新，未重复构建。
- `pnpm smoke:package --skip-package` 七步全过：两棵解压树的必需路径 10 条、
  可执行件（当时含 SDK 的 `claude`，后已移出产物）均完整；启动后 3 个服务就绪并注册进 `/api/modules`；
  smart-factory 的同源健康检查返回后端 JSON、SPA 深链接回 HTML、WebSocket 返回 101、
  `$COSIGHT_HOME/smart-factory.db` 非空；关停后 4399/4400 与 3000/4830/5173 全部释放。

**遗留**：Windows 上 smart-factory 会被跳过。需要模块方补 Prisma `binaryTargets`
（SDK 后续已移出产物），见 `module-artifact-integration.md` §5。这一轮没有改他们的代码。

---

## PKG-INSTALL · 安装闸门：预检 → 装插件 → 启模块，异常即失败 ✅

**触发**：用户要求「在启动前检测本机是否装了 Claude Code、Node 版本是否满足、
各依赖组件是否就绪；之后把 drive / agent-genesis / agent-evaluator / skill-optimizer
装进 Claude Code；之后再启动各模块；中间任何缺失或异常都让启动失败并打印异常」。
方案与落地偏差见 [`install-preflight-and-plugins.md`](./install-preflight-and-plugins.md)，
决策见 D45–D47，用户视角的说明见 [`plugin-install.md`](./plugin-install.md)。

**做了什么**

| 产物 | 内容 |
|---|---|
| `lib/preflight.mjs` + `lib/checks/*.mjs` | 检查项登记表：平台、Node、Claude Code、Claude 目录可写、Python 3、插件载荷、数据目录、配置文件、前端产物、模块载荷、磁盘空间。只读；固定四段报告 |
| `lib/claude-cli.mjs` | 解析 `claude`（`--claude` → PATH → 已知位置）、版本解析、带超时执行、Windows `.cmd` quoting |
| `lib/plugin-hash.mjs` / `plugin-index.mjs` | 内容哈希（打包期、复制期、运行期同一套排除规则）、`plugins/index.json` 读写与交叉校验 |
| `lib/plugin-install.mjs` | `decidePluginAction` / `decideMarketplaceAction` 纯函数 + `ensurePlugins()`；`.install.lock`；装后复核 |
| `scripts/artifact/plugins.json` | 四个插件的坐标与 `requires.bins`（宿主侧声明，不改插件仓库） |
| `package.mjs` | 四个插件进产物、生成 index、复制前后哈希一致、归档读回断言 |
| `start.mjs` | `--install` / `--skip-plugins` / `--claude` / `--keep-going` / `--skip-module`；预检接入 `--self-check`；产物布局下先装插件再启模块；失败即停（10 预检 / 12 插件 / 13 启动） |
| `install.sh` / `install.cmd` | 改走 `start.mjs --install`（预检 → 初始化 → 装插件） |
| `lib/runtime.mjs` | `checkTcpBind`：框架端口在 spawn 之前试绑 |
| 文档 | `install-preflight-and-plugins.md`、`plugin-install.md`、`packaging.md` §1.1/§7/§9、`operations-manual.md`、`artifact-readme.mjs`、D45–D47 |

**证据（实跑）**

- `pnpm verify`：全绿（脚本 222、shared 91、server 346、web 343）。
- `node --test "framework/scripts/tests/**/*.test.mjs"`：**222 条全绿**
  （115 → 222，新增 121 条：`plugin-install` 29、`claude-cli` 28、`claude-check` 17、
  `preflight` 15、`package-plugin` 15、`plugin-payload` 14、`runtime` 3）。
- `pnpm lint`：0 warning（含 `--deny-warnings`）。
- 真实 `claude 2.1.304` + 隔离 `CLAUDE_CONFIG_DIR`：首次安装四个插件（
  `drive@zte-ai-lab`、`agent-genesis@agent-genesis`、`goldeval@goldeval`、
  `skill-optimizer@skillx`）成功，第二次运行全部判定为"无变化"、零写命令；
  用户真实 `~/.claude` 未被触碰。第二次用的是**最终产物**里解压出来的 `install.sh`。
- `--install --skip-plugins` 在隔离配置目录下**零写入**。这个组合原先是个 bug：
  `--install` 分支绕过了跳过判定，仍然把四个 marketplace 写进了 Claude 配置。
  判定已收敛到 `shouldInstallPlugins()` 并补了四条单测（仓库/产物 × install/skip）。
- 冒烟里的 `install.sh` / `start.sh` 都带 `--skip-plugins`：冒烟只验产物形态，
  不拿开发机真实的 `~/.claude` 当靶子。
- 手工占住框架端口后启动：打印四段（阶段 / 原因 / 处理 / 影响）并退出 **13**，
  已起的模块进程被回收；正常启动到达「已就绪」，SIGTERM 后端口立即可复用。
- `pnpm package`：产物含 `plugins/` 四目录 + `index.json`，index 版本/哈希与
  目录重算结果一致；`smoke:package` 解包后逐项断言通过。

**明确没做**

- 没有 `claude plugin validate` 预检项（静态校验已覆盖坐标与文件缺失）；
- 没有独立的假 `claude` 可执行文件；端到端用进程内假状态机 + 一次真实 CLI 手工跑；
- init 失败仍退出 **1**，没有单独做成 11；
- Windows 全链路未真机验证（`claude.cmd`、GBK 控制台、中文路径只有单测）；
- 没有改 `drive/`、`agent-genesis/`、`agent-evaluator/`、`skill-optimizer/`
  的任何文件——它们的 hooks 写死 `python3` 这一项作为对接项留给插件作者。

---

## 9. 未决事项与偏差（需要人拍板）

### 9.1 D23 字体文件缺失 🔴
`framework/web/src/styles/fonts.css` 已声明 Alibaba PuHuiTi 的 `@font-face`，但**仓库里与本机都没有字体文件**，因此当前实际渲染走 `--font-medium` 里的思源黑体 CN 回退链（`font-weight: 500` 在只有 400/700 两档字重的系统上会静默落回 400，所以链里刻意写的是"Medium"字重的字体名）。需要有人提供 woff2 文件与授权确认；否则首屏会有两个 404，且视觉与设计稿不一致。

### 9.2 `agent-eval` 能力没有宿主路由 🟡
见 P6 的"已知缺口"。需求 4.5 的「评估」按钮当前跳到 `agent-dev?mode=evaluate`。

### 9.3 卡片四个按钮在 v1 全是"占位目标" 🟡
D20=D21=C（待定）的后果：「使用」指向会话模块、"设计/评估/优化"指向 Agent 开发模块，而这两个模块都还没接入，所以四个按钮在 v1 都会落到"模块尚未接入"。这是**如实反映现状**，不是 bug，但演示时需要说明。

### 9.4 D14 的"行为"子项未勾选 🟡
页头按钮位置按 D14=A（右上、搜索框左侧）；被勾掉的"行为"子项暂定为跳 `?mode=create`。

### 9.5 D26 目录名 🟡
按 `~/.cosight-harness/` 实现（`config/paths.ts`）。若团队约定用别的名字，改一处即可。

### 9.6 D7 的存储实现偏差 🟡
决策写的是 SQLite + Drizzle，实现为 `@libsql/client` + Drizzle，原因是 better-sqlite3 是原生模块，
在本项目的 Node 24（ABI 137）上加载直接 `ERR_DLOPEN_FAILED`，且没有可用预编译产物（见 `framework/server/src/db/client.ts` 文件头）。
D7 的实质（SQLite 文件 + Drizzle + 可管迁移）没有变，变的只是驱动；代价是仓储方法全部是异步的。
如果一定要回到 better-sqlite3，那要连带把 Node 降到有预编译产物的版本。

### 9.7 卡片的"选中态"没有使用场景 🟡
token 里备了 `--shadow-card-selected` / `--gradient-card-selected`，但**没有任何决策定义"选中一张卡片"是什么交互**（单选？多选？仅 hover？）。当前未使用；等交互定义清楚再接线，避免凭空发明一种选择行为。

### 9.8 两处图标替换 🟡
UX 稿的图标与 `Icon.tsx` 的实现有两处不一致：知识库用 `book`（稿里是日历）、观测用折线图（稿里是 Dashboard）。已在 `Icon.tsx` 头部注明理由，需设计确认。

### 9.9 en-US 文案是新增翻译 🟡
D28=B 要求 v1 双语，但 UX 稿只有中文。`en-US.ts` 里的英文是本次新增的翻译，需要产品/文档侧校对。

### 9.10 e2e 的运行前提 🟡
`framework/web/e2e/` 与 `playwright.config.ts` 已就绪，但需要 `pnpm exec playwright install chromium`，且后端能起来（Playwright 会自动拉起两个 dev server）。jsdom 测不到的都以 e2e 为准：真实布局不塌、真实 Tab 焦点陷阱。原「搜索防抖次数 / 滚动预取」两条随原生专家页删除（D44）一并去掉——宿主侧已经没有带输入的地方。

### 9.11 桥协议的实现方缺失 🟡
`framework/shared/src/bridge.ts` 完整定义了宿主 ↔ 模块的 postMessage 协议：`host:init`（带一次性 `bridgeToken`、locale、theme、context）、`host:locale` / `host:theme` / `host:context` / `host:teardown`、模块侧的 `module:ready` / `module:resize` / `module:navigate` / `module:open-expert` / `module:notify` / `module:error`，外加两个类型白名单与 `bridgeMessage()` 构造器——**但全仓库只有它自己的测试引用它**。`ModuleHost.tsx` 文件头明确写着"不做 postMessage 协议"，语言是靠 URL 参数下发的。
服务端的 `/api/bridge/token|exchange|session|logout` 四个接口本身是完整且已测的，缺的是**调用方**：契约描述的"宿主 postMessage 发令牌"这条路径没有任何实现。
两条路可选，需要拍板：(a) 按现契约在 `ModuleHost` 里实现握手（令牌走消息通道，不进 URL）；(b) 承认模块自行取令牌是最终形态，把 `bridge.ts` 里 `host:init` 带令牌那段删掉，避免留下一份没人实现的协议让人照着写。

### 9.12 `settings-schema.ts` 定义了但没有接线 🟡
`framework/shared/src/contracts/settings-schema.ts` 的 `settingsFieldSchemaSchema` 目前只被它自己的测试引用，服务端与前端都没有消费点；而 `contracts/agent-proxy.ts` 的注释写着"模块自己在 manifest 里声明它需要的设置字段（见 settings-schema.ts）"——`moduleManifestSchema` 里**并没有** settings 字段。这条"模块声明配置项 → 框架渲染表单"的路径尚未打通，需确认是留给后续批次还是已经改主意。

### 9.13 模块清单的 `healthcheck` 字段未被消费 🟡
`contracts/module.ts` 定义了 `healthcheck`（可为 null 的 URL），但服务端与前端都不读它：`/api/modules` 原样返回，`ModuleHost` 也不做探活。字段留着无害，但"定义了却没人用"和"实现了探活"是两回事，需确认是否进后续批次。

### 9.14 两个错误码已定义但无调用点 🟡 → 已收口一半

`FORBIDDEN`（403）与 `UPSTREAM_UNAVAILABLE`（503）在 `framework/shared/src/errors.ts` 的枚举与状态码映射表里，
但全仓库没有调用点（`AppError.forbidden` 有工厂方法但无人使用）。需确认是预留给模块调用还是遗漏。

**2026-10-15 更新**：`FORBIDDEN` **有了第一个调用点**——模块面门禁在 `Host` 头不是回环名、
来源 socket 不是回环地址、或请求带 `Origin` 时抛 `AppError.forbidden`（`routes/module-face.ts`）。
所以它不是"预留字段"，是"等到了它的场景"。`UPSTREAM_UNAVAILABLE`（503）**仍然没有调用点**：
它要的场景是"框架作为客户端去调上游、上游不可用"，而 v1 唯一的出网接口 `POST /api/models/:id/probe`
是 `notImplemented`（§9.18）。这条子项保持 🟡。

### 9.15 接口请求没有超时 🟡
`framework/web/src/api/client.ts` 的 `request` 只透传调用方的 `signal`，不设任何超时。服务端半途死掉（进程被杀、连接被丢弃）时这次 `fetch` 会一直挂着，界面停在加载态且不会自己结束——`queryClient.ts` 里的 `networkMode: 'always'` 管的是"离线时不暂停"，**不是**超时，之前那行注释把它写成超时是错的（已改）。
本机 workbench 上概率不高（服务在同一台机器），所以没进首期；要补的话是在 `client.ts` 里把调用方 signal 与 `AbortSignal.timeout(ms)` 用 `AbortSignal.any()` 合起来，并把 `TimeoutError` 从 `AbortError` 里分出来，否则"用户切页签取消"和"服务端没响应"会共用同一条错误路径。

### 9.16 空响应体会被报成"无法连接服务端" 🟡
`client.ts` 的 `readJson` 对空响应体返回 `null`，`looksLikeEnvelope(null)` 为假，于是抛 `ApiNetworkError`——而前端的错误文案把它译成「无法连接服务端，请确认后端已启动」，排查方向完全被带偏。
当前所有接口都经 `sendOk`/`sendPaged` 返回信封，所以这条路径**今天走不到**；将来任何 204 或空体的接口都会撞上。根因是 `ApiNetworkError` 同时承载了"根本没连上"与"连上了但响应不可用"两件事，要修得先把这两类分开（增加一个错误类型或标志），属契约层改动，故不在本轮动。

### 9.17 需求 4.2 的「滑动按钮」完全没有着落 🔴
需求 4.2 的卡片元素列表是"头像 / 名称 / 上传者 / 描述 / 多标签 / **滑动按钮**"。其中前五项都实现了，**最后一项既没有决策、也没有实现、UX 稿里也不存在**：

- `docs/framework-decisions.md` 里 D13–D19 逐条覆盖了 4.2–4.5 的其它细节（`预置` 页签、创建按钮位置、热度指标、卡片操作栏、无限滚动），**没有任何一条提到滑动按钮**；
- 全仓库 `grep -riE "switch|toggle|slider|滑动"` 只命中 `toggleSidebar`（侧栏折叠，与卡片无关），组件库里也没有开关类控件；
- UX 稿经全量检索确认**没有任何** toggle / switch / checkbox / radio 控件（见 `framework/web/docs/design-tokens.md` 的缺失清单）。

所以它不是"做了但没接上"，而是**从需求到设计到代码三处都缺**。需要先定清楚它到底是什么，再决定做不做：

- 是**卡片级开关**（如"启用/停用这个专家"）？那它要落到专家表的一个布尔字段上，且"停用"在列表 / 使用 / 计次里各是什么语义都要定义；
- 还是**收藏/点赞开关**？那与 D15 的「最热」指标直接相关（D15 已选定 B：纯使用次数，不含收藏）；
- 或者它其实是路由/参数层面的东西（如"滑动"指横向滚动的按钮行），需求措辞需要澄清。

在澄清之前按"未实现"记，不猜着做——凭空发明一种选择行为比留空更糟（同 §9.7）。

### 9.18 模型探测按钮仍是占位 🟡
P5 落成时把"模型探测"排除在 v1 之外（要真探测就得让服务端拿密钥去调第三方接口，涉及出网、超时、以及把失败原因回给用户的文案），因此词表里的 `error.not_implemented.model_probe` 目前**没有任何调用点**。留着是给后续版本占位，但要清楚：它现在既不是"实现了"，也不是"忘了"。

### 9.19 读接口返回了非预期形状时，崩的是整棵设置弹窗 🟡
`ModelSettingsPanel.tsx` 的 `const models = list.data ?? []` 之后紧跟 `models.map(...)`：`requestData<T>` 只做 JSON 解析、**不做运行时校验**，所以当 `data` 是对象/字符串而不是数组时（代理配错、中间件返回 HTML、服务端契约变更），抛出的 `TypeError` 会被路由的错误边界接住，用户看到的是"设置打不开"，真实原因在控制台里。
`GET /models` 的契约确实是裸数组、服务端也是这么回的，所以**今天走不到**；和 §9.16 是同一类问题的两副面孔——错误类型没有区分"没连上 / 连上了但响应不可用 / 响应能用但形状不对"。要修得在契约层把这三类分开（或给列表接口加一层 zod 校验并降级到空列表 + 错误态），属契约层改动，不在本轮。

### 9.20 无障碍审查的其余几条：已修的、有意不修的 🟡

2026-10-14 对 UX 轮做了一次无障碍审查（WCAG 2.2，对比度按 sRGB 相对亮度实算）。**已修的两条**（按钮蓝字、手柄 `aria-valuetext`/`aria-controls`）见 §UX。以下是**没有改**的，逐条写清是不改还是待定：

| 事项 | 位置 | 结论 |
|---|---|---|
| 标签六色底的对比度 | `tokens.css` 的 `--color-tag-*` | ✅ **实测通过，无需改**：六色配 `--text-body` 是 **7.15–7.57:1**（最低的紫色 7.15），远高于 4.5:1。已有 `token-contrast.test.ts` 钉住 |
| `role="separator"` 的用法 | `SidebarResizer.tsx` | ✅ **正确**：可聚焦的 `separator` + `aria-valuenow/min/max` + `aria-orientation` 就是 WAI-ARIA 的 Window Splitter 写法；Tab 不被吞已有用例 |
| 手柄命中区只有 8px（SC 2.5.8 要求 24px） | `SidebarResizer.module.css` | 🟡 **走间距豁免，有意不加宽**：以命中区中心画 24px 的圆，够不到任何别的可点目标。加宽到 24px 反而会横跨过去压住主面板靠左的卡片——拿一个真实的误点风险换形式达标。理由已写进 CSS 注释 |
| 卡片按钮描边只有 1.25:1（白底） | `Button.module.css` 的 `.outline` | 🟡 **有意不改**：SC 1.4.11 管的是"识别控件所必需"的视觉信息，而这四个按钮各有可见文字，边界不是识别它们的必要条件。压到 3:1 需要约 `#949494`，会比卡片自身的描边重得多，看起来像贴在卡片上的外来控件——与"看起来是卡片的一部分"的设计意图冲突。理由已写进 CSS 注释 |
| 焦点环在画布色上 2.99:1（SC 2.4.11 要求 3:1） | `global.css` | 🟡 差 0.01。属**既有**缺口（P1 引入，非本轮），最小改法是把焦点环改用更深一档的色或加一圈白描边。待定 |
| 卡片标题跳级 h1 → h3（中间没有 h2） | ~~`ExpertCard.tsx` / `ExpertsPage.tsx`~~ | ⬜ **随 D44 作废**：原生专家卡片已删除，页面改由 smart-factory 的 `/agents` 提供。无障碍由该模块自己负责 |
| `+N` 折叠起来的标签只有 `title`，键盘/读屏拿不到 | ~~`ExpertCard.tsx`~~ | ⬜ **随 D44 作废**：同上，原生卡片已删除 |
| 卡片 `<article>` 没有可访问名 | `ExpertCard.tsx` | 🟡 读屏会念成无名的「文章」。改法是给 `<h3>` 一个 id、`article` 加 `aria-labelledby`。待定 |
| 移除「预置」角标后，卡片上不再有程序化的"是否预置"信息 | `ExpertCard.tsx` | 🟡 需求 UX-3.5 的直接后果。对读屏用户，"预置"只能去筛选页签拿。若要补，得给卡片加一段 `visually-hidden` 文字，属可用性取舍，待定 |

**说明**：这张表里"待定"的几条都不影响本轮验收（没有一条是阻断性的 AA 失败，除了焦点环差 0.01 那条——它是既有问题且只差千分之一量级）。列出来是为了不让审查结论停留在会话里。

### 9.21 打包产物能给服务端省 23 M，但没做 🟡

产物 220 M 里，`esbuild`（12 M）与 `@esbuild/linux-x64`（11 M）纯属"为了在运行时把 `.ts` 转成 `.js`"——
这是 `tsx` 的运行期依赖。线上跑的既然是**已构建**的产物，这部分理论上可以整块拿掉。

改法只有一条：打包时用 esbuild 把 `harness-server` 打成**单个 JS 文件**，产物里只留 `node_modules` 中的运行期依赖，
不留 TypeScript、不留 tsx。收益是 ~23 M（约体积的 10%），代价是：

- 打包流水线多一道 bundling 步骤，且要处理 Drizzle 的迁移文件读取、`import.meta.url` 基准目录变化等
  "打包后路径不再等于源码路径"的问题；
- 出问题时排查对象从"源码 + node_modules"变成"一个几百 KB 的 bundle"，本地复现变难；
- 与 D27=A 的边界有张力——`start.mjs` 现在明确不代管生命周期，bundle 之后"跑的是哪份代码"需要另立约定。

对一个**本地优先、内网分发**的产物，220 M 与 197 M 没有体感差别；而上面三条都是稳定的长期成本。
所以判定为**不做**，留给"产物要上公网分发"或"要压进镜像层"的那天再说。此条记录是为了下次有人重新量出这 23 M 时，
能直接看到结论和理由，不必从头评估一遍。

### 9.22 模块面的写接口 —— 曾判"不做"，本轮反转为做 ✅

**这一条记录的是结论反转，所以两段都留着。**

**当时的结论（v1 第一轮）**：`/api/framework/v1/models/*` 三个端点全是 `GET`，
新增 / 修改 / 删除 / 设为当前只在框架界面上做。理由两条，第二条被当成硬理由：

1. 消费方（`smart-factory` 这类模块）是**读**消费者，没有"帮用户配一个模型"的场景；
2. `.credentials.yaml` **没有跨进程文件锁**，模块面一旦可写，
   "两个进程同时 read-modify-write 丢更新"就从理论风险变成随时可触发。

**本轮的反转（D33）**：模型补了 `POST` / `PATCH` / `DELETE`，工作区补了整套 CRUD。
第 2 条理由**不成立**——模块面的写**全部经 HTTP 打到那一个框架进程**，
写入串行化的那个 `CredentialStore` 实例始终只有一个；跨进程风险只存在于
"绕过 HTTP 直接改那个文件"，那与浏览器面今天的情况没有任何区别。

第 3 条被否掉的方案（另发一枚作用域独立的"写令牌"）也一并记下：本机单用户下，
真正的边界是"能读到 0600 文件"，不是令牌的作用域，多一枚令牌只是多一份要管的东西。

**代价如实记着**：令牌的爆炸半径从"能读密钥"变成"能重配平台 + 能在磁盘上建目录"。
三条缓解都在实现里（写操作 warn 日志、只在框架自己的工作区根下建目录、
文档口径改为"不该要写权限的模块就别要"），完整说明见
[`module-facing-api.md`](module-facing-api.md) 第 6 节、[`framework-decisions.md`](framework-decisions.md) 的 D33。

顺带修掉一处**结构性的隐患**：门禁原来挂在单个路由文件上，加第二条子树时"忘挂"
**不会报错**——只是静默多出一个不需要认证的读写接口。现在上提到唯一的
`routes/module-face.ts` 插件上（`onRequest`），子树注册在它内部，门禁自动继承。

### 9.23 工作区文件浏览遗留的四条 🟡

**一条既有红灯，2026-10-19 已修**：`web/tests/module-host.test.tsx` 曾期望沙箱是
`allow-scripts allow-same-origin allow-forms allow-popups`，而 `ModuleHost.tsx` 已经是
`… allow-popups allow-downloads`（从 `e17ca46` 起就红）。代码里的注释写明了
`allow-downloads` 是有意的（模块要能导出会话 / 结果），所以更新的是期望值而不是属性。
它此前会中断 `pnpm -r`、让 server 那一段静默跳过；现在整套 web 用例可以一起跑。

**一条既有的文案键瑕疵，本轮没修**：`AppError.notFound(resource, id)` 会把 `resource`
拼进 messageKey，而几个调用点传的是中文（`AppError.notFound('工作区', id)` →
键 `error.not_found.工作区`）。词表里没有这个键，靠 `translateApiErrorKey` 逐段回退到
`error.not_found.default` 才显示出一句人话——**现象是对的，机制是错的**：下一句中文 resource
会掉进同一条回退链，而谁都不知道自己踩上了。本轮新写的代码全部直接构造 `AppError` 传完整键
（`error.not_found.workspace_directory` / `error.not_found.workspace_file`），没有扩大这个面。
真正的修法是让 `notFound` 只接受键或者要求传 `messageKey`，那是另一轮的事。

**四条写进文档、不打算"修"的**：

- **悬浮按钮压在模块页面上。** 它占着会话区右上角一小块（`x=1391 y=17 w=32`），
  同事以后在自己页面右上角加东西会被压住，而他们看不见我们的组件。这是 D35 的直接代价。
- **面板打开时同事的 iframe 真的会变窄，而且那 300ms 里它在逐帧重排。** 这是 D39
  选"挤压"的直接代价，也是**唯一一条需要我们主动去找同事确认的事**：他们的页面在
  约 2/3 宽度下布局成不成立、有没有对 resize 敏感的图表/canvas 会在过渡期间疯狂重绘。
  已经写进 [`module-integration-smart-factory.md`](module-integration-smart-factory.md) §7，
  这一条不是"能不能商量"，只能请他们适配。
- **回环门禁挡不住同机同进程/浏览器扩展**，且**把 UI 部署到非回环地址时这三个 GET 会 403**
  （文件面板打不开）。见 D36 与 [`workspace-design.md`](workspace-design.md) §7.3。
- **上限拦的是体积，不是敏感性。** 面板会把工作区里任何 UTF-8 文本原样显示出来，
  包括用户自己放进去的凭据文件。这是"预览用户自己的工作区"这个需求的直接后果。


### 9.24 打包这件事的边界与遗留 🟡

**Windows 没有实测过。** 本机是 Linux，没有环境，所以这一轮的完成度里不含"在 Windows 上装过、跑过"。
替代证据见 §PKG（打包期断言 + 读源码得出的机制 + 纯函数守卫），人工验收清单在
[`packaging.md`](packaging.md) §10。**谁拿到 Windows 机器，照着那七步走一遍就能把这条转成 ✅。**

**范围不含 macOS 与 ARM**（用户已确认）。加平台的路子写在 [`packaging.md`](packaging.md) §3：
`ARTIFACT_TARGETS` 加目标 + `nativePackagesFor()` 补原生包名（**去 `@neon-rs/load` 的
`currentTarget()` 与 esbuild 的 `install.js` 里对名字，不要照 `linux` → `darwin` 类推**，
Windows 那一列就带 `-msvc` 后缀）。漏一个包时测试会红——这是刻意的，否则错会发生在用户机器上。

**产物从 22.3 MB 涨到 29.5 MB**，涨的基本是第二套原生件（libsql 8.5 MB + esbuild 12 MB）
与用户侧的五个脚本，零软链也让它略大（软链在 tar 里几乎不占字节）。这是"一份通用包"的直接代价，
取舍见 [`packaging.md`](packaging.md) §2 与 D40。

**不带 Node 运行时**：安装脚本只做预检与下载指引。带运行时要跟着选版本、打进 40+ MB、
还要处理两个平台的解压差异与许可证，换来的只是"少装一个 Node"。用户已确认。

**强杀留下的 `-wal` / `-shm` 只在文档里交代，本机验证不了。** Windows 上 `child.kill()`
是直接终止而非投递信号，服务端的优雅关闭钩子不执行，SQLite 可能留下这两个文件（不影响下次启动）。
控制台里按 Ctrl-C 不受影响。没有改架构——在 Linux 上做不出这个路径。

### 9.25 smart-factory 已进产物（linux-x64），Windows 待实测 ✅ → 🟡

Linux x64 上已经跑通（§PKG-SF）：`server/dist` 打包期构建、`web/dist` 由随包搬运的
`web-server.mjs` 静态托管并同源代理 API/WS、数据库模板打包期生成、运行时幂等复制，
`startAfter: framework` 保证框架令牌就绪后再起。冒烟对代理、SPA、WS 101、首次建库
都做了端到端断言。

**剩余**：清单已声明 `platforms: ["linux-x64", "win32-x64"]`，`schema.prisma` 的
`binaryTargets` 已覆盖 Windows；SDK 已移出产物，执行引擎改为用户自行安装的
Claude Code CLI。前置条件已齐，但 Windows 上的实际打包与冒烟尚未记录，仍需实测确认。

### 9.26 切模型 / 切工作区后刷新 Agent 开发与评估页 ✅

`ModuleHost` 新增 `reloadOnContextChange`，只有 `AgentDevPage` 打开：订阅
`/models/active` 与 `/workspaces/active`，把「工作区 id + 工作区默认模型 + 全局当前模型」
拼成 iframe 的 `key`。任一变化 → iframe 重建 → 模块入口按新上下文重拉数据。
评估 / 优化与开发共用这条路由，因此一并生效；会话、知识库、观测等宿主不订阅、不刷新。

- 首次进入时等两个上下文查询就绪再挂 iframe，避免"先按无上下文加载一次、数据回来再重建"；
- 不做 postMessage 桥：模块入口本来就会重新请求，重建 iframe 比新增一套消息协议更小；
- 工作区的 `defaultModelId` 进 key：改它和切换全局模型对模块是同一件事。

同时移除侧栏的「历史会话」分组（`HistoryList` 组件与两条文案键一并删除）——
历史会话已经在「观测」界面里，宿主侧那份永远只有空态，留着反而误导。
`/history` 路由保留（仍是 `history` 能力的模块宿主），只是侧栏不再展示入口。

### 9.27 知识库路由设置（设置页签 + 侧栏跳转 + 模块面只读接口）✅

用户维护若干条「名称 + 跳转地址」，**至多一条生效**；各模块取那一条把用户导过去。

- **界面**：设置里新增「知识库路由设置」页签，位置在「模型设置」与「Agent 代理配置」之间。
  列表支持 新增 / 设为可用 / 编辑 / 删除，空态与错误态与其余面板一致。
- **打开入口在侧栏**：左侧「知识库」菜单配好后在**新的浏览器标签页**打开生效项的地址
  （2026-10-28 调整；此前是宿主内 `/knowledge` 的嵌套 iframe）。`/knowledge` 路由仍保留给
  直接访问 / 旧书签，由 `KnowledgePage` 把地址嵌进主面板（iframe，沙箱与模块宿主同一份）。
  **列表行上不放「打开」**，同一个动作只留一个入口。未配置时点击它**直接**打开本页签的
  新增表单（菜单进入时默认勾「设为可用」）；保存后整组查询失效，
  **菜单立即变成可跳转的链接，不用重启**。读取失败与"没配置"分开说，确认按钮是「重试」。
- **「设为可用」是行上的独立动作**（`POST /:id/activate`），不在编辑表单里：编辑走 `PATCH`，
  请求体**不带** `isActive`——否则"只改个名字"会顺手换掉正在用的那条，而界面上看不出异常。
  新建表单才有开关（默认关）。删掉可用项后**不自动补位**，确认语里明说后果。
- **至多一条生效**在三层同时兜住：契约层、仓储写入（事务里先清后置）、DB 局部唯一索引
  `WHERE is_active = 1`。
- **模块面只读**：`/api/framework/v1/rag-knowledge` 与 `/…/active`，没配置时是 `200 + null`
  而不是 404。没有写接口——写入者只有设置里的用户，少一个写入口就少一分令牌泄漏的杀伤面。
- **不探测可达性**：服务端主动去连用户填的任意地址就是 SSRF 跳板，且"现在连不上"不等于配错。
- **地址校验两侧都做**：必须 `http(s)` 绝对地址、不得内嵌账号密码（前端单独一条提示，
  不混进"格式不对"）；长度上限在契约里定义一次。
- 消费方文档见 [`rag-knowledge-api.md`](rag-knowledge-api.md)，决策见 D51。

**验证**：契约层 `contracts/rag-knowledge.test.ts`（25 例）、后端
`rag-knowledge.repository.test.ts` / `api-rag-knowledge.test.ts` / `api-module-rag-knowledge.test.ts`、
前端 `settings-rag-knowledge-panel.test.tsx`（18 例）、`shell.test.tsx` 的
`KnowledgeNavItem` 四条，以及 `settings-dialog.test.tsx` 的页签遍历。
顺带清掉 `ObservationSettingsPanel.tsx` 里三处历史 lint 告警（`7fbedb6` 引入），
否则 `--deny-warnings` 门禁过不去。

### 9.28 模型「设为当前使用」的默认值；Agent 代理取消新增入口 ✅

**模型设置**：新增表单里「设为当前使用」的初值改为**按当前有没有生效模型**决定——
一条都没有（首次配置，或全被停用）时默认**打开**，保存即生效，省掉"保存完再点一次"；
已有生效模型时默认**关闭**，不悄悄顶掉正在用的那条。判断依据是**已加载的列表**
（`list.data`）：列表还没回来或读取失败时按"有"处理——宁可让用户手动拨一下，
也不让新建的一条顶掉正在用的模型。开关本身依旧可手动切换。

**Agent 代理配置**：取消「新增代理」按钮，界面只做查看 / 编辑 / 删除 / 设为默认；
代理配置由接口 `POST /api/agent-proxies` 写入（**后端接口保留不动**，只删前端入口）。
随之删掉只有新增才用的 `emptyAgentProxyDraft` / `agentProxyCreatePayload` 与
`settings.agentProxy.create` / `createTitle` 两个词条，表单只剩编辑形态（`proxy` 不再可空），
空态文案改成"新增走接口"。

**验证**：`settings-model-panel.test.tsx` 新增三条默认值用例（空列表 / 有生效 / 全停用）；
`settings-agent-proxy-panel.test.tsx` 的新建用例改写为编辑态校验（名称必填、地址协议、
额度上限、开关翻转），空态用例改为断言"没有任何带『新增』的按钮"；
`settings-dialog.test.tsx` 的页签遍历表把 agentProxy 那一行的「新增」位改成 `null`。
