# 模块进产物：对接说明

> 读者：负责 `smart-factory/`（以及后续其他模块）的开发同事。
> 目的：说清"一个模块要能被装进 `Co-Sight Harness` 的产物并在用户机器上跑起来，
> 必须提供什么"，并记录 smart-factory 这一轮接入时做了什么、还差什么。
>
> 这一轮 smart-factory 已经**真的进包并在 Linux x64 上跑通**（装配态清单与
> 两个辅助脚本都在框架侧）。`smart-factory/` 的源码**一行没改**；Windows 上的
> 那部分仍然需要模块方补，见 §5。

---

## 1. 产物里的模块长什么样

`pnpm package` 打出的是一个自包含压缩包。装上之后用户只跑 `start.sh` / `start.cmd`，
它做三件事：

1. 按 `priority` 升序拉起立即可起的模块，等每个服务的 `readyPath` 返回 2xx；
2. 拉起框架服务端（4300），等 `/api/health` 就绪；
3. 再拉起声明了 `startAfter: "framework"` 的模块，最后打印所有模块的探活结果。

```
cosight-harness-<版本>-<时间戳>/
├── start.mjs / lib/          启动入口（多进程监督）
├── server/ web/              框架自身
└── modules/
    ├── cosight-viewer/       一个模块一个目录
    │   ├── module.json       运行时契约：宿主拿它拼 iframe 地址
    │   ├── artifact.json     装配态启动清单：start.mjs 拿它拉起进程
    │   ├── server/
    │   ├── client/dist/
    │   └── node_modules/
    └── smart-factory/
        ├── module.json
        ├── artifact.json
        ├── db-init.mjs       启动前复制数据库模板（随包搬运）
        ├── web-server.mjs    静态托管 + 同源 API/WS 代理（随包搬运）
        ├── db-template.sqlite
        ├── server/{dist,node_modules,prisma}/
        └── web/dist/
```

`cosight-viewer` 与 `smart-factory` 的
[`modules/cosight-viewer.artifact.json`](./modules/cosight-viewer.artifact.json) /
[`modules/smart-factory.artifact.json`](./modules/smart-factory.artifact.json)
都可以当作完整示例读。

## 2. 一个模块要进包，必须提供什么

| # | 要求 | 为什么 |
| --- | --- | --- |
| 1 | **一条生产启动命令**：`node <入口>` 这种，不依赖 npm script / 监听器 / 构建工具链 | 产物里没有仓库结构，也不替你跑 `npm install`（D34）。`npm run dev`、`tsx watch` 在用户机器上不成立 |
| 2 | **前端静态产物**（如果模块有自己的页面） | 宿主只拿到一个 `entry` URL，用 iframe 嵌。页面必须能从某个 HTTP 端口直接取到 |
| 3 | **前端接口与页面同源**（写死根相对 `/api/...` 时） | 页面与接口分两个端口时，`/api/...` 会解析到页面端口，接口全 404；WebSocket 同样。要么后端自己托管静态页，要么声明框架随包发的 `web-server.mjs`（`bundle.assets`） |
| 4 | **跨平台原生件已按平台声明** | 一份包同时覆盖 linux-x64 与 win32-x64 是框架的承诺；模块可以在 `platforms` 里只声明一部分，但没声明的平台不会被拉起 |
| 5 | **启动没有全局副作用，或副作用可用环境变量关掉** | 模块进程和用户的其他工具跑在同一台机器上。典型副作用是写用户全局配置 |
| 6 | **`node_modules` 与源码树完整**（依赖已装好、零软链） | 打包时只做构建，不装依赖；软链在 Windows 自带解压器下会变成 0 字节文件 |
| 7 | **`module.json` + `artifact.json`**（见 §4） | 前者说"怎么嵌"，后者说"怎么打包、怎么启动" |

`module.json` 是已有的运行时契约（`/api/modules` 直接发它）；`artifact.json` 是装配态
清单。两份分开的理由见 `framework-decisions.md` D41。

## 3. smart-factory 这一轮是怎么接上的

（核对与实跑时间 2026-10-19，Linux x64。）

| 要求 | 处理方式 | 结果 |
| --- | --- | --- |
| 生产启动命令 | `bundle.builds` 在打包期先跑 `npm run prisma:generate`（`prisma/schema.prisma` 比生成物新时），再跑 `npm run build`（`tsc`），产物 `server/dist` 进包；服务命令是 `node server/dist/index.js` | ✅ 打包与冒烟都真的执行了 |
| 前端静态产物 | 不改模块源码。框架随包搬两个辅助件：`web-server.mjs` 在 4110 托管 `web/dist`（含 SPA 回退），并把 `/api/*` 的 HTTP 与 WebSocket 升级代理到 4100；`db-init.mjs` 负责首次建库 | ✅ 页面、深链接、API、WS 四条链路都在冒烟里断言 |
| 接口同源 | 前端写死 `/api/smart-factory/v1/...`，因此静态页与接口必须在同一端口。`web-server.mjs` 合成一个端口 | ✅ 冒烟直接打了代理后的健康检查与 WS 101 |
| 数据库 | 打包期用临时 `COSIGHT_HOME` 跑一次 `node scripts/db.mjs sync`，生成 `db-template.sqlite`；运行时 `prepare` 只在 `$COSIGHT_HOME/smart-factory.db` 不存在时复制模板 | ✅ 首次启动建库、再次启动不覆盖 |
| 框架集成 | `startAfter: "framework"`：等框架就绪、`.module-token` 已写出后再起；`FRAMEWORK_BASE_URL` 由 `{{frameworkUrl}}` 注入 | ✅ `/api/modules` 注册、模型配置读取链路可用 |
| 依赖树 | `bundle.dependencyRoots: ["server"]`；只核对服务端 `package.json`，前端只进 `web/dist` | ✅ 打包期逐项核对 |
| 原生件 | Claude Code CLI 不在产物里（用户侧安装）；Prisma 带两个平台的查询引擎 | ✅ 两个平台都覆盖，见 §5 |
| 体积 | 排除构建期依赖：`prisma` CLI、`@prisma/engines`、`typescript`、`tsx`、`esbuild`、`@types`、`@anthropic-ai` | 去掉 SDK 后 101.8 MB（tar.gz，2026-11-03 实测） |

**`artifact.json` 没有要求扩展 `module.json`**：`entry` 仍指向 `http://localhost:4110/`，
`healthcheck` 仍是 `http://localhost:4110/`，多服务模块的端口一致性由 `artifact.json`
自己保证。运行期契约这边只有一处后来的增补（D44，与本文件无关）：`mounts` 多了
`experts → /experts`（`entryPath: "/agents"`），让宿主直接打开模块的专家列表。

## 4. 接入是加两份 JSON，不是改框架代码

真源在框架仓库 `framework/docs/modules/`：

- `smart-factory.module.json` —— 运行时契约；
- `smart-factory.artifact.json` —— 装配态清单（当前实际内容）。

打包脚本按"`<id>.artifact.json` 存在 ⇒ 进包"判定，没有硬编码名单。清单里这一轮用到的
字段：

| 字段 | smart-factory 的用法 |
| --- | --- |
| `env` | `NODE_ENV=production`、`COSIGHT_HOME={{dataDir}}`、`FRAMEWORK_BASE_URL={{frameworkUrl}}` |
| `prepare` | `node db-init.mjs --template db-template.sqlite --file smart-factory.db` |
| `startAfter` | `"framework"`（要读框架令牌） |
| `platforms` | `["linux-x64", "win32-x64"]` |
| `bundle.include` | `server/dist`、`server/package.json`、`server/prisma`、`server/node_modules`、`server/builtin-agents`（随包的内置专家定义）、`web/dist`、`LICENSE` |
| `bundle.exclude` | `.bin`、Prisma CLI/engines、TypeScript、tsx、esbuild、`@anthropic-ai`（CLI 由用户侧安装）、`.env` |
| `bundle.builds` | 共三条，顺序即执行顺序：服务端 `npm run prisma:generate`（输入 `prisma/schema.prisma`，产物 `node_modules/.prisma/client/index.d.ts`）、服务端 `npm run build`、前端 `npm run build`；输入/产物/超时齐全 |
| `bundle.assets` | 从框架搬 `module-web-server.mjs` → `web-server.mjs`、`module-db-init.mjs` → `db-init.mjs` |
| `bundle.database` | `node scripts/db.mjs sync` → `db-template.sqlite` |
| `bundle.dependencyRoots` | `["server"]` |
| `bundle.required` | `dist/index.js`、Prisma Client 与引擎、前端 `index.html`、两个辅助件、模板库、内置专家 `agent.json`、`LICENSE` |
| `bundle.executable` | 空：Claude Code CLI 由用户在运行机自行安装，不进发行物 |
| `services` | `server`（4100，`/api/smart-factory/v1/health`）与 `web`（4110，`/`） |

写清单时的硬规则（写错一律在打包时**报错**，不会静默失效）：

- `bundle.include` 里的每一条都必须存在；目录会逐层展开。
- `bundle.build` / `bundle.builds` 只在产物比输入旧时执行；命令返回 0 之后还会再判一次新旧。
  多条按数组顺序执行，所以**生成步骤要写在构建之前**。
- **构建依赖从 schema / 接口描述生成出来的代码时，生成命令必须自己声明成一条构建**
  （smart-factory 的 `prisma:generate` 就是这样）。生成物在 `node_modules/` 里、是
  gitignore 的：改了 `schema.prisma` 之后它不会自己更新，编译期只会得到
  「某个字段不存在」这种看不出根因的报错。`bundle.install` 不承担这件事——它只在
  断言发现缺件时跑。
  出处：2026-10-29 的 `pnpm package` 就栽在这里（`schema.prisma` 新增了
  `knowledgeWorkflowId`，生成物还停在两天前，`tsc` 报 `TS2339`）。
- `services[].cwd` 与 `prepare[].cwd` 相对**模块目录**，且必须落在模块目录内
  （`../..` 会被拒绝）。
- `command[0] === "node"` 会被换成当前解释器，不依赖 PATH。
- 只支持两个占位符：`{{dataDir}}`（用户数据目录）与 `{{frameworkUrl}}`（框架实际地址，
  端口可能来自 `cosight.env`）。写死 `~` 或相对路径会往产物目录里写数据。
- 一个模块可以有多个服务；每个服务单独探活，任一失败只跳过该模块。
- `bundle.assets` 的 `from` 相对**仓库根**，`to` 相对模块目录；同一位置不能写两份。
  `from` 是**文件**时原样单文件收进；是**目录**时整棵展开，可选 `exclude`（路径段名数组）
  命中任何层级的同名段即整树剔除（如 `data`、`.venv`）。

## 5. Windows / 其他平台

当前清单声明 `"platforms": ["linux-x64", "win32-x64"]`。`schema.prisma` 的
`binaryTargets` 已包含 `"windows"`，打包脚本会补齐两个平台的 Prisma 查询引擎
（见 `packaging.md`）。

Claude Code CLI 不在产物里，由用户在运行机自行安装；打包侧只保证
`bundle.exclude` 排除 `@anthropic-ai`，并由打包期黑名单断言兜底。

体积提醒：SDK 不再进产物，2026-11-03 实测 tar.gz 101.8 MB（此前带两套 SDK 可执行件的版本为 208.2 MB）。

## 6. 之后会发生什么 / 怎么验证

框架侧不需要改任何代码：

1. `pnpm package` 自动发现清单，打印「已打进：smart-factory」；
2. 构建（若声明）、搬运、依赖核对、读回校验全部走同一套断言；
3. `start.mjs` 在产物布局下按 `priority` 拉起它，并把它同步进
   `$COSIGHT_HOME/modules/`，让首页能发现这个模块。

在框架仓库根目录：

```bash
pnpm package                         # 打包期断言；模块清单写错会在这里失败
pnpm smoke:package --skip-package # 解压 → 安装 → 启动 → 断言模块链路
```

冒烟对 smart-factory 的断言是端到端的：同源健康检查、SPA 深链接、WebSocket 101、
首次建库、可执行件与必需路径、关停后 4100 / 4110 都释放。

手工验证：解压 → `./install.sh` → `./start.sh` → 打开 `http://127.0.0.1:4300/`，
进入 Agent 开发页确认模块页面能打开、接口有数据。

如果只想先确认清单写对了，可以跑 `node start.mjs --self-check`：
它会打印产物里认到了哪些模块、清单有没有问题（不阻塞框架启动，但对应的模块不会拉起）。

## 7. 框架不替模块做的事

- **不装依赖**：`node_modules` 必须随源码树就位。打包可以跑构建，但绝不跑 `npm install`
  （它会联网、改 lockfile，还可能触发模块自己的 `prepare` 钩子）。
- **不做进程守护 / 自动重启**：起不来就打印一行 `✗`，由人决定；这与框架自身一致。
- **不改模块的运行时行为**：包括写不写全局配置、数据库落在哪。这些由模块用环境变量
  自己控制；框架只负责把 `{{dataDir}}` / `{{frameworkUrl}}` 这类值传进去。
- **不为某个模块写特判**：没有硬编码名单。加模块 = 加一份 `artifact.json`。
