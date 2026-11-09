# Framework · 框架宿主外壳

[简体中文](README.md) · [English](README.en.md)

框架本身不是一个能独立打开的应用，而是**把各模块串成一个入口的宿主外壳**：
左侧导航栏 + 工作区设置 + 底部设置。会话、专家、Agent 开发、观测这些页面
框架自己不做，只负责把对应模块的页面嵌进来（`<ModuleHost capability="…" />` 的 iframe 宿主）。
专家页由 smart-factory 的 `/agents` 提供（D44），框架侧原来的原生页已删除。

**有一处例外**：会话区右上角那个「展开工作区文件」的悬浮按钮与它打开的面板是**宿主自己画的**。
因为宿主与模块之间没有桥（D24），宿主既读不到也画不进 iframe 里面，
而需求要的图标恰好落在模块的地盘上。面板内部是**左右分栏**（左目录树 / 右文件预览），
左缘可拖，宽度介于 320 与**页面宽度的三分之一**之间；打开时它**把会话区挤窄**（不是盖住），
还可以**全屏展示**（铺满内容区，左侧栏留着）。
理由、代价（同事的 iframe 在面板开合时会逐帧重排）、
以及"同事以后在那块地方加东西会被压住"这条提醒，见
[`docs/framework-decisions.md`](docs/framework-decisions.md) 的 D35、D38 与 D39，以及
[`docs/module-integration-smart-factory.md`](docs/module-integration-smart-factory.md) §7。

这与仓库的组件约定一致（见根 [`README.md`](../README.md#仓库结构) 的「组件约定」）：**服务类组件内部布局按服务特性定**，
模块根不放 `package.json`。因此 `framework/` 下的命令**一律在仓库根执行**，不在本目录执行。

## 目录

```
framework/
├── server/       后端：Fastify 5 + TypeScript（HTTP API、SQLite + Drizzle）
├── shared/       共享契约层：zod schema、API 信封、错误码、模块清单、iframe 桥协议
├── web/          前端：React 18 + Vite + React Router + TanStack Query + Zustand
├── scripts/      仓库级脚本：总启动（dev-all）、装配态启动（start）、打包（package）、产物冒烟（smoke-package）
│                 artifact/ 是**产物里那五个用户侧文件的真源**（安装/启动脚本 + 配置模板）
├── docs/         框架文档：架构、决策、模块接入说明、打包、任务清单、模块清单注册表
└── tsconfig.base.json   三个包共同 extends 的编译基座
```

**`shared/` 不产出构建物**：`exports` 直接指向 `src/*.ts`，改动即刻对前后端两端可见。
契约只在这里定义一次，服务端不另立一套 —— 见 `docs/architecture.md` 的契约约定。

## 安装指南

前提两样：**Node.js `^22.19.0 || >=24.0.0`**（与服务端 `engines` 一致，根 `package.json` 是唯一声明处）
和 pnpm。包管理器版本写在根 `package.json` 的 `packageManager` 字段（`pnpm@11.28.5`），
用 corepack 对齐可以避免"本机 pnpm 版本不同导致 lockfile 抖动"：

```bash
cd <仓库根>            # 仓库根 = cosight-harness/，不是 framework/
corepack enable       # 只需一次
pnpm install          # 一次装齐 shared / server / web 三个包
```

`framework/` 目录下**没有** `package.json`：三个包各有一份，由根 `pnpm-workspace.yaml` 串起来。
所以命令一律在仓库根执行，进到 `framework/` 里跑会找不到脚本。

装完先确认环境是好的（不启动服务）：

```bash
pnpm typecheck        # 三个包各跑一次 tsc --noEmit
pnpm run verify       # typecheck + oxlint + 全部测试（覆盖率阈值 80%）
```

数据目录 `$COSIGHT_HOME`（默认 `~/.cosight-harness`）在**第一次启动**时自动创建并执行迁移，
安装阶段不需要手工建库。

拿到的是**分发包**而不是源码时，别走上面这条路：解压后跑 `./install.sh`（Windows 双击
`install.cmd`），见 [`docs/user-guide.md`](docs/user-guide.md)。两者的分工是源码仓库自己
`pnpm dev`，分发包里是已构建的前端 + `start.mjs`。

## 配置说明

服务端配置**只有一个入口**：`server/src/config/env.ts` 的 `loadConfig()`。它在启动的第一秒
把环境变量解析并校验成 `ServerConfig`，非法值直接抛 `ConfigError` 并退出——不会留到某次请求里
才变成 `undefined`。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `COSIGHT_PORT` | `4300` | 监听端口；不是 1..65535 的整数则启动失败 |
| `COSIGHT_HOST` | `0.0.0.0` | 监听地址。默认所有网卡（D25：v1 本地单用户、无登录，暴露范围请自行评估）；只绑本机写 `127.0.0.1` |
| `COSIGHT_HOME` | `~/.cosight-harness` | 数据根目录：库、`.credentials.yaml`、`.module-token`、模块清单、工作区都在它下面 |
| `COSIGHT_WORKSPACES_ROOT` | `$COSIGHT_HOME/workspaces` | 工作区根，可与框架私有数据分开放。解析口径与 `COSIGHT_HOME` 一致：`path.resolve`、不展开 `~` |
| `COSIGHT_DATABASE_URL` | `file:$COSIGHT_HOME/sqlite.db` | libsql 连接串 |
| `COSIGHT_WEB_DIST` | 开发态空 / 生产态由 `start.mjs` 指向实际产物目录 | 前端静态产物目录；为空时只跑 API，前端交给 Vite |
| `COSIGHT_CORS_ORIGINS` | `localhost` 与 `127.0.0.1` 的 `:4310`、`:4830` | 允许跨源的源，逗号分隔。两种写法都列是因为浏览器眼里它们是不同源 |
| `COSIGHT_HOST_ORIGIN` | `http://<host>:<port>` | 宿主**前端**的源，用于模块清单的跨源校验；开发态是 `:4310`，不是 API 的 `:4300` |
| `COSIGHT_LOG_LEVEL` | `info` | `fatal\|error\|warn\|info\|debug\|trace\|silent` |
| `COSIGHT_KNOWLEDGE_API_KEY` / `CO_KNOWLEDGE_API_KEY` | 空 | 知识库 Agent API Key 的服务端默认；先读前者，取第一个非空白值。不落库，浏览器面只被告知"有没有" |
| `NODE_ENV` | 未设 | 决定静态托管与前端产物目录的默认值；`production` 时前端由服务端托管 |

两份配置来源，按运行方式选：

- **开发态**：`COSIGHT_PORT=4400 pnpm dev`，或写进 shell profile。**没有**配置文件这一层——
  少一个"改了却没生效，因为看错文件"的坑。
- **产物态**：与 `start.mjs` 同目录的 `cosight.env`（`KEY=VALUE`，模板是
  [`scripts/artifact/cosight.env.example`](scripts/artifact/cosight.env.example)）。
  解析器只有一份（`scripts/lib/env-file.mjs`），不让 `start.sh` / `start.cmd` 各解析一遍。
  优先级：**命令行 > 真实环境变量 > `cosight.env` > 内置默认值**。

模块自己的配置不在这张表里：地址与允许的源写在 `$COSIGHT_HOME/modules/<id>/module.json`，
启动编排写在 `docs/modules/<id>.launch.json`（开发态）或 `<id>.artifact.json`（产物）。

## 快速启动

```bash
cd <仓库根>            # 工作区根在仓库根，不在 framework/
pnpm install
pnpm dev              # 并行起后端 4300 + 前端 4310
```

打开 <http://localhost:4310> 。前端开发态通过 Vite proxy 把 `/api` 转发到 4300，因此前端代码里只写
相对路径。**不要**把前端改成直连 `http://127.0.0.1:4300`：代理顺带让两端同源，`SameSite=Lax` 的桥接
cookie 才会被带上（`server/src/routes/bridge.ts`）；直连会让开发态与生产态的 cookie 行为分叉。

想让各模块（smart-factory、cosight-viewer…）一起起来，用总启动：

```bash
pnpm dev:all          # 先框架、再按优先级拉模块，每步等就绪；Ctrl-C 按逆序全停
```

### 前后端分开启动

两边都是 watch 模式，改哪边重启哪边：

```bash
pnpm dev:server       # 只起后端：tsx watch src/index.ts → 127.0.0.1:4300
pnpm dev:web          # 只起前端：vite → 127.0.0.1:4310（/api 代理到 4300）
```

单独起前端时后端必须先起来，否则页面上所有请求都会代理失败。表现是控制台一串
`502` / `ECONNREFUSED`，而不是白屏——Vite 本身是好的。

### 生产形态（本机验证用）

```bash
pnpm build            # 前端出 dist；server 的 build 只做类型检查，不产 JS
pnpm start            # node framework/scripts/start.mjs：托管 web/dist + API，同源 :4300
```

`pnpm start` 在仓库布局下只**探活**已注册模块，不拉起它们（开发态编排是 `pnpm dev:all` 的事，D27）；
在产物布局下它会先按 `modules/<id>/artifact.json` 把模块拉起来，再起框架。

回归门禁（typecheck + oxlint + 测试，覆盖率阈值 80%）：

```bash
pnpm run verify
```

## 脚本

`scripts/` 属于**整个仓库**而不是某个包 —— 它要跨包取 `server/`、`web/`、`docs/`，所以放在模块根。

| 命令 | 作用 |
|---|---|
| `pnpm dev` | 开发态并行起后端（4300）与前端（4310） |
| `pnpm dev:all` | 开发态**总启动**：框架前后端 + 按优先级依次拉起各模块的前后端，每步等就绪；Ctrl-C 按逆序全停。见 [`docs/dev-all.md`](docs/dev-all.md) |
| `pnpm start` | 起**产物**或仓库布局的服务端。产物布局下会先按 `modules/<id>/artifact.json` 拉起模块、等各自就绪，再起框架；仓库布局下仍只探活（开发态由 `pnpm dev:all` 负责，D27）。加 `--self-check` 只做检查（Node 版本 / 布局 / 数据目录 / 配置文件 / 模块），加 `--init` 还会建数据目录并从模板生成配置——产物里的 `install.sh` / `install.cmd` 调的就是它；`--no-modules` 只起框架。加 `--uninstall` 是反向操作：把五个插件与市场从 Claude Code 里摘掉（`--dry-run` 先预览，`--purge-data --yes` 连数据目录一起删）——产物里的 `uninstall.sh` / `uninstall.cmd` 调的就是它 |
| `pnpm test:scripts` | 打包与启动脚本的快速测试（纯函数 + 真实脚本文件的编码/行尾规则，毫秒级） |
| `pnpm package` | 打出交付归档（`tar.gz` + `zip`，一份包同时含 linux-x64 与 win32-x64 原生件），顶层为 `install.*` + `start.*` + `server/` + `web/` + `modules/` + `start.mjs`。哪些模块进包由 `docs/modules/*.artifact.json` 决定，模块前端产物旧了会先重建 |
| `pnpm smoke:package` | 用系统 `tar`/`unzip` 独立解压、模拟安装（`install.sh` → 改配置 → `start.sh`）、起服务并断言 HTTP，**含模块**：每个服务端口 2xx、页面可取、`/api/modules` 已注册、smart-factory 的静态/SPA/API/WS/建库链路、关停后所有端口都释放 |
| `pnpm package:plugin` | 把 Claude Code 插件目录打成安装包（`tar.gz` + `zip`），默认 `agent-genesis`；归档根目录带 `install.sh` / `install.cmd` / `INSTALL.md`，排除 `work/`、`output/`、`.agent-genesis/`、`.claude/`、`.env`。`--plugin <目录>` / `--out <目录>` 换目标；`--compat-manifest` 在**包内**按当前 CLI 的发现规则修正清单字段（源码不动，改动会写进输出与 `INSTALL.md`） |

`start` / `package` / `smoke-package` 的布局常量集中在 `scripts/lib/project.mjs` ——
`REPO_ROOT`（仓库根：`.package/` 与根 `package.json`）与 `MODULE_ROOT`（`framework/`：`server/`、`web/`）
是两个不同的根，不要混用。产物里该有哪些文件、要带哪些平台的原生件，也都只在这一个文件里
（`ARTIFACT_TARGETS`、`nativePackagesFor()`、`ENTRY_SCRIPT_SOURCES`），并有测试钉住。

## 模块怎么挂进来

框架不开发业务页面，只提供挂载点。一个模块要出现在左侧栏某个一级导航的内容区，需要两件事：

1. 它的页面跑在**与宿主不同的源**上（D24：同源的话 iframe `sandbox` 就没有意义）；
2. 在 `docs/modules/<id>.module.json` 登记一份清单（`id` / `entry` / `allowedOrigins` / `mounts`），
   再拷到运行时目录 `$COSIGHT_HOME/modules/<id>/module.json`（`pnpm dev:all` 会自动做这一步）。

要让 `pnpm dev:all` 在本机把它**跑起来**，再加第三件事：同目录放一份 `<id>.launch.json`
（服务列表 + 端口 + 就绪路径 + 优先级）。这份是**开发编排**，不进运行时契约——
`module.json` 里没有、也不会有启动命令字段，见 [`docs/dev-all.md`](docs/dev-all.md)。

开发态**入口是产物**（静态托管某个 `dist/`）的模块，还要在同一份清单里加一段 `build`
（命令 + 输入 + 产物）：产物通常不进版本控制，`git pull` 拉不到，不刷就会一直拿着旧包跑——
页面缺了同事刚合的功能，而你只会以为"功能没做"。这段同样是**可选**的，走 `npm run dev`
的模块不需要它。

左侧栏各导航对应的能力位定义在 `shared/src/contracts/module.ts` 的 `MODULE_CAPABILITIES`；
挂载点各在 `web/src/app/routes.tsx`。同一个模块前端有多个页面时，`mounts[].entryPath`
声明该能力落在模块内的哪一页（smart-factory 的专家页就是 `experts → /agents`）；
不声明则直接用 `entry`。`docs/modules/*.module.json` 里的清单由
`server/tests/module-manifests-doc.test.ts` 做回归——清单写错的表现是「静默退回未接入」，
和"没接"长得一样，所以必须有测试钉住。

### 让模块跟着产物一起发出去

开发态的三件事之外，还有一件只管**产物**的：同目录再放一份
`docs/modules/<id>.artifact.json`（装配态清单：进包哪些文件、构建怎么做、
装到用户机器上用哪条命令起）。**这份文件存在 ⇒ 这个模块进包**，没有硬编码名单；
有 `module.json` 却没有它的模块会在打包输出里列为「未打进」。

两份清单的分工是刻意的：`launch.json` 描述"在这台开发机上怎么跑"（`npm run dev`、
相对仓库根），`artifact.json` 描述"打包与安装后怎么跑"（`node server/index.js`、
相对模块目录）。产物里没有仓库、没有 npm 工具链，前一种描述整个不成立（D41）。

已接入模块的对接说明与"进包要满足什么"：
[`docs/module-integration-smart-factory.md`](docs/module-integration-smart-factory.md)、
[`docs/module-artifact-integration.md`](docs/module-artifact-integration.md)。

当前进包的模块是 `cosight-viewer`（通用）与 `smart-factory`（仅 linux-x64）。
后者是多服务模块的例子：随包搬运的 `web-server.mjs` 把静态页、`/api` 反代与
WebSocket 升级合到同一个端口，`db-init.mjs` 首次启动把数据库模板复制到数据目录。
两个辅助脚本都来自框架侧（`scripts/artifact/`），`smart-factory/` 源码没有改动（D42）。

## 文档

| 文档 | 内容 |
|---|---|
| [`server/docs/architecture.md`](server/docs/architecture.md) | 后端的架构与设计取舍（分层、契约、错误模型、模块注册表、iframe 桥） |
| [`docs/framework-decisions.md`](docs/framework-decisions.md) | 框架级决策记录（D1… 逐条，含每条的取舍与代价） |
| [`docs/module-integration-smart-factory.md`](docs/module-integration-smart-factory.md) | 模块接入的样例与对接说明 |
| [`docs/module-artifact-integration.md`](docs/module-artifact-integration.md) | 给模块开发同事：进产物要满足什么、清单怎么写、smart-factory 的缺口逐条对照 |
| [`docs/module-facing-api.md`](docs/module-facing-api.md) | 模块面接口：本机其他模块怎么和框架打交道（模型含明文密钥；三个子树：模型/工作区可读写、知识库路由只读；需令牌） |
| [`docs/rag-knowledge-api.md`](docs/rag-knowledge-api.md) | 知识库跳转路由接口：**可直接转发给消费方同事**（两个只读端点 + 鉴权 + 字段 + 五条使用口径）；侧栏「知识库」就是它的第一个消费方 |
| [`docs/model-config-api.md`](docs/model-config-api.md) | 模型配置对外接口：**可直接转发给消费方同事**的自足说明（三个读接口 + 三个写接口 + 鉴权 + 示例） |
| [`docs/workspace-design.md`](docs/workspace-design.md) | 工作区方案：目录布局、目录名的 slug 规则与保留名、哪一步动磁盘、**只读浏览（§7：包含规则 / 四个上限 / 回环门禁）**、与 dsh 的刻意分叉 |
| [`docs/workspace-api.md`](docs/workspace-api.md) | 工作区接口对外说明：**可直接转发给消费方同事**（基址 + 鉴权 + 七个端点 + 真实请求/响应 + 接入写法），另含磁盘边界与两个面的差异 |
| [`docs/dev-all.md`](docs/dev-all.md) | 总启动脚本：启动顺序、端口冲突的归因与解法、加新模块的步骤 |
| [`docs/packaging.md`](docs/packaging.md) | 产物打包与跨平台安装：一份通用包的取舍、原生件机制、零软链、**产物里的模块（§6）**、打包期断言清单、体积对照、**怎么加平台**、Windows 人工验收清单（本机没在 Windows 上跑过，文档里如实交代） |
| [`docs/user-guide.md`](docs/user-guide.md) | **易读手册（先看这份）**：打包 → 安装 → 启动一条线；给测试同学的验收清单（正向/异常/退出码 0/10/12/13）与给普通用户的常见问题、卸载步骤 |
| [`docs/operations-manual.md`](docs/operations-manual.md) | **操作手册**：从源码出包（`pnpm build` → `pnpm package`）→ 解压安装 → 本地启动 → 配置 → 自检 → 常见问题 → 卸载；另含开发态 `pnpm dev` / `pnpm dev:all` 与命令速查 |
| [`docs/uninstall-manual.md`](docs/uninstall-manual.md) | **卸载手册（单篇成文）**：为什么删目录不够（插件与载荷副本在 `~/.claude` 下）、三步卸载、`--dry-run` / `--purge-data --yes`、脚本按什么顺序动哪三处、退出码 0/12/13、被别人共用市场的处理、手工兜底十条命令、卸载后自检与 FAQ |
| [`docs/task-list.md`](docs/task-list.md) | 任务清单与完成状态 |
| [`docs/modules/`](docs/modules/) | 模块清单注册表（版本控制里的真源） |
| [`web/docs/design-tokens.md`](web/docs/design-tokens.md) | 前端设计令牌 |
