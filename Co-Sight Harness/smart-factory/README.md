<div align="center">

# Smart Factory · 智慧工厂

**对话式构建、预览与评估 AI 智能体 —— 把「造智能体」从命令行能力变成有界面的产品能力。**

[简体中文](README.md) · [English](README.en.md)

<br/>

![Version](https://img.shields.io/badge/version-0.1.0-46d4e8?style=flat-square)
![Node](https://img.shields.io/badge/Node-%3E%3D20-4ade80?style=flat-square&logo=nodedotjs&logoColor=4ade80)
![React](https://img.shields.io/badge/React-19-46d4e8?style=flat-square&logo=react&logoColor=46d4e8)
![Express](https://img.shields.io/badge/Express-5-1f2937?style=flat-square)
![Platform](https://img.shields.io/badge/platform-linux%20%7C%20windows-f0a63a?style=flat-square)
![Local-first](https://img.shields.io/badge/local--first-%E2%9C%94-4ade80?style=flat-square)

</div>

---

## 目录

- [这是什么](#这是什么)
- [功能特性](#功能特性)
- [架构总览](#架构总览)
- [快速开始](#快速开始)
- [配置](#配置)
- [模型与密钥](#模型与密钥)
- [数据与目录](#数据与目录)
- [界面导览](#界面导览)
- [HTTP 与 WebSocket 接口](#http-与-websocket-接口)
- [项目结构](#项目结构)
- [开发与测试](#开发与测试)
- [文档](#文档)
- [生态](#生态)
- [贡献](#贡献)
- [许可证](#许可证)

## 这是什么

Smart Factory 是 [Co-Sight Harness](../README.md) 的端侧模块：在本机同时运行一个 API 服务和一个 Web 界面，为「智能体（Agent）」提供从创建、生成、预览到评估的完整闭环。

它不替模型写智能体，而是给模型一套可控的执行结构：需求在会话里澄清，产物落在工作区目录，每一步都有门禁、有记录、可回看。

一次交互里有三个核心对象：

| 对象 | 含义 |
|---|---|
| **session（会话）** | 一场持续的对话，绑定一个智能体（或一个目录）与一个阶段 |
| **run（运行）** | 会话里的一次执行；子智能体派生产生同表同状态机的子 run |
| **message（消息）** | 过程中的每条产出、每次挂起与结算 |

设计取向：

- **端侧本地**：前后端与 Claude Code 同机，文件以本地路径引用，产物直接落盘，不经上传下载。
- **真实引擎**：默认用 `claude-cli` 驱动本机 Claude Code CLI；`fake` 适配器只用于测试与 e2e。
- **界面是薄壳**：业务规则集中在服务端 service，前端只负责取参、渲染与交互。
- **明确的减法边界**：不做模型管理、版本管理、技能市场、发布安装与鉴权；智能体运行页也交给框架会话页，本模块只提供「使用」跳转。

## 功能特性

| 能力 | 说明 |
|---|---|
| **智能体管理** | 元数据 CRUD、标签、搜索、来源筛选、按产物状态筛选；状态由产物目录现算，不落库 |
| **对话式创建** | 首页选能力、写一句需求，即可在开发会话里生成完整智能体工程；支持首轮附件与知识检索工作流 |
| **三阶段工作流** | 生成（Build）/ 预览（Preview）/ 评估（Evaluate）各自有独立会话与目录，预览与评估在隔离沙箱中运行 |
| **实时会话** | WebSocket 流式输出正文、思考与工具事件；支持中止运行、按消息游标回补历史 |
| **审批与交互** | 工具审批与交互式提问挂起为消息，无超时；支持「允许一次 / 本会话全部允许 / 拒绝」 |
| **技能开发** | 技能库扫描、把技能装配进智能体产物；`/workshop` 提供技能创建与优化的目录会话 |
| **评估报告** | 读取 `agent-eval` 产物并归一化为报告 / 用例 DTO；结果质量与轨迹合规两套分不合并 |
| **知识检索** | 只读代理 RAG Studio 已发布工作流清单，创建智能体时选择知识检索链路 |
| **内置专家** | 随包分发、只读，启动时按定义目录幂等登记；能力由对应插件提供 |
| **双语与嵌入** | 界面中英双语；可被框架以 iframe 嵌入，嵌入时自动收起本模块侧边栏 |
| **本机文件** | 智能体封面图上传、产物浏览下载，以及整机文件树浏览与文本预览 |

### 三阶段与四目录

后端有四个阶段目录；创建流程只走其中三个（`runtime` 没有创建面板，运行由框架会话页发起）：

| 阶段 | stage / 目录 | cwd | 目录怎么来 |
|---|---|---|---|
| 生成 Build | `development` | `<agentRoot>/development/` | 创建智能体时建出；开发会话在此生成智能体工程 |
| 预览 Preview | `preview` | `<agentRoot>/preview/` | 每次 run 前从 development 最新 `vN` 整体物化；源未变则跳过 |
| 评估 Evaluate | `evaluation` | `<agentRoot>/evaluation/` | 先确保 preview，再从 preview 整体物化；源未变则跳过 |
| 运行 Runtime | `runtime` | `<agentRoot>/development/output/agents/{name}/{latest vN}/` | 原地运行开发产物，不拷贝 |

- **预览与评估是隔离副本**：沙箱里改文件、删文件、跑飞都不影响开发产物。
- **进入预览 / 评估有门禁**：`GET /agents/{id}/production` 的 `ready` 为真才放行；门禁看交付文件与质量门禁结果，产物缺失、版本缺失、流程未收尾一律明确报错。
- **评估结果属于源版本**：开发产物变化导致沙箱重拷时，旧评估报告随之清空。

## 架构总览

```text
浏览器  React 19 + Vite（:4110）
├── /                     首页：一句话创建 · 五类能力
├── /agents               专家列表 / 技能库
├── /agents/:id/design    设计页：生成 · 预览 · 评估
└── /workshop             技能开发
        │
        │  REST + WebSocket   /api/smart-factory/v1
        ▼
Smart Factory Server  Express 5 + TypeScript（:4100）
├── 能力域  agent · session · run · artifact · evaluation · skill ·
│          knowledge · files · fs · model · workspace · health
├── 数据    $COSIGHT_HOME/smart-factory.db（SQLite）
└── 引擎    claude-cli | fake
        │                                    │
        │ 只读模块面（module token）           │ 起 run / 流式事件 / 审批
        ▼                                    ▼
Cosight Framework                     Claude Code CLI（用户自行安装）
工作区 · 模型 · 知识库路由              cwd = 阶段沙箱或产物目录
```

服务端按能力域分模块，每个域内部固定四件套，依赖方向单向 `routes → controller → service → store`：

| 层 | 位置 | 职责 |
|---|---|---|
| 路由 | `modules/<域>/<域>.routes.ts` | 路径与 HTTP 方法到 controller 的映射 |
| 控制器 | `modules/<域>/<域>.controller.ts` | 取参、调 service、组装响应 |
| 服务 | `modules/<域>/<域>.service.ts` | 唯一业务承载：编排、事务、校验、状态机 |
| 仓储 | `shared/store/*.repo.ts` | ORM 调用、行到领域对象的映射 |
| 实时 | `shared/live/` | 连接、信封编解码、扇出、心跳、背压 |
| 引擎 | `shared/engine/` | CLI 协议的收敛与翻译；不依赖任何 Anthropic 包，只 spawn 用户自装的 `claude` |
| 工作区 | `shared/workspace/` | 目录推导、沙箱物化、产物门禁 |

## 快速开始

### 前置条件

- **Node.js >= 20**（含 npm）。
- **[Co-Sight Harness 框架](../framework/) 正在运行**（缺省 `http://127.0.0.1:4300`）：工作区、模型与知识库路由优先从这里读取。
- **Claude Code CLI 已安装并配置可用模型**：真实引擎 spawn 本机 `claude`，通过 stream-json / control 协议交互。
- **Windows**：先安装 Git for Windows，引擎的 Bash 工具依赖 Git Bash；探测失败时用 `CLAUDE_CODE_GIT_BASH_PATH` 指向 `bash.exe`。
- **发行物不包含 Claude Code / Agent SDK**：CLI 是用户侧外部前置，由用户自行安装并接受 Anthropic 条款；本服务只负责调用。

### 启动

```bash
cd smart-factory

node scripts/dev.mjs setup   # 首次：装依赖 + 生成 server/.env + prisma generate + 建库
node scripts/dev.mjs start   # 后台启动前后端
```

打开 <http://localhost:4110>。

`setup` 会依次完成：安装 `server/` 与 `web/` 依赖、从 `server/.env.example` 生成 `server/.env`、生成 Prisma Client、创建数据目录并建库（`prisma db push` + `bootstrap.sql`）。建库不走迁移文件。

### 验证

```bash
curl -s http://127.0.0.1:4100/api/smart-factory/v1/health
# {"status":"ok","service":"smart-factory-server","version":"0.1.0","time":"..."}
```

框架未启动时健康检查仍可用，但工作区、模型、智能体目录相关能力会明确返回 `502`，不猜路径、不静默降级。

跑一遍完整会话链路（临时后端 + 独立数据目录 + 框架桩，默认 `fake` 引擎）：

```bash
node scripts/dev.mjs e2e
```

用真实引擎跑同一条链路：

```bash
ENGINE=claude-cli SF_PROMPT="用 Write 工具创建文件 a.txt" node scripts/dev.mjs e2e
```

Windows 下用 `set ENGINE=...`（cmd）或 `$env:ENGINE="..."`（PowerShell）设置环境变量。

### 停止、状态与日志

```bash
node scripts/dev.mjs status
node scripts/dev.mjs stop
node scripts/dev.mjs restart
```

运行日志在 `.run/logs/`（`server.log` / `web.log`），需要实时跟随时直接查看该目录下的文件。

## 配置

后端配置集中在 `server/src/config/index.ts`，`.env` 由 `setup` 从 `server/.env.example` 生成。常用项：

| 变量 | 缺省 | 说明 |
|---|---|---|
| `COSIGHT_HOME` | `~/.cosight-harness` | 数据根目录，与框架共用同一套解析口径（`path.resolve`，不展开 `~`）。后端与框架必须指向同一个目录 |
| `FRAMEWORK_BASE_URL` | `http://127.0.0.1:4300` | 框架模块面地址；只读 GET，令牌从 `{COSIGHT_HOME}/.module-token` 每请求现读 |
| `HOST` / `PORT` | `0.0.0.0` / `4100` | 后端监听地址。缺省监听全部地址（同网段可达）；服务无鉴权且 `/fs/*` 可浏览整机，只应部署在可信网络，只需本机访问时设 `127.0.0.1` |
| `CORS_ORIGIN` | `*` | 允许跨域的前端来源 |
| `ENGINE` | `claude-cli` | 引擎适配器：`claude-cli` 或 `fake`；未知取值拒绝启动 |
| `CLAUDE_CODE_PATH` | 空 | 显式指定 `claude` 可执行件；留空按 PATH 解析 |
| `SKILLS_ROOT` | `{COSIGHT_HOME}/smart-factory/skill-workshop` | 技能开发会话的 cwd；技能库在其 `output/skills/` 下 |
| `CHAT_ROOT` | `{COSIGHT_HOME}/smart-factory/chat` | 没有生效工作区时自由对话的兜底 cwd |
| `WS_HEARTBEAT_MS` | `30000` | WebSocket 心跳间隔；超时为间隔的 2 倍 |
| `WS_MAX_BUFFERED_BYTES` | `4194304` | 单连接发送缓冲上限，超出判定为慢消费者并断开 |
| `ARTIFACT_MAX_FILE_BYTES` | `2097152` | 产物文本读取上限，超限 `413`；下载不受限 |
| `FILES_MAX_FILE_BYTES` | `10485760` | 单个上传文件上限，超限 `413` |
| `EVALUATION_MAX_JSON_BYTES` | `5242880` | 评估报告 JSON / JSONL 读取上限 |
| `AUTO_META` | 开启 | 创建后自动生成名称、描述与标签；`0` 关闭 |
| `CO_KNOWLEDGE_BASE_URL` | 空 | RAG Studio **兜底根地址**（如 `http://rag-studio.example.com`）；框架有生效路由时以框架为准 |
| `CO_KNOWLEDGE_API_KEY` | 空 | **兜底** Agent API Key（`ragk_...`），走 `X-API-Key`；框架返回的生效值优先 |
| `CO_KNOWLEDGE_LIST_TIMEOUT_MS` | `8000` | 知识库列表请求超时 |
| `SMART_FACTORY_SERVER_PORT` / `SMART_FACTORY_WEB_PORT` | `4100` / `4110` | 只给 `scripts/dev.mjs` 与 vite 使用 |

前端一般无需配置：开发态由 vite 把 `/api` 代理到后端，前端代码只写相对路径。确需绕过代理时，复制 `web/.env.example` 为 `web/.env.local`，按注释设置 `VITE_API_BASE_URL`、`VITE_WS_BASE_URL`、`VITE_FRAMEWORK_HOME_URL` 等。

## 模型与密钥

- 模型由框架统一管理，本服务**没有模型表、模型 CRUD 与凭据配置项**。
- `sessions.modelId` 存框架模型 uuid，**恒非空**：`sessions/create` 与 `send { agentId }` 必填；切换只能换成另一个非空模型，不支持清空。服务端没有「工作区默认模型 / 框架生效模型 / 本机 Claude Code 配置」回退。
- Web 端会在预览 / 评估首次建会话前自行解析默认模型（工作区 `defaultModelId` → 框架 `activeId` → 列表第一项），解析后仍显式传给接口。
- 起 run 时服务端向框架读取 `modelName` / `baseUrl` / `apiKey` 并注入引擎子进程；**密钥不落库、不下发浏览器、不进日志与错误消息**。

## 数据与目录

模块库与智能体产物分两处落盘：

```text
{COSIGHT_HOME}/
├── smart-factory.db            # 模块库（SQLite：agents / instances / sessions / runs / messages）
├── .module-token               # 框架模块面令牌，每请求现读
└── smart-factory/
    ├── builtin-agents/         # 随包内置专家定义，只读
    ├── skill-workshop/         # 技能开发会话 cwd
    │   └── output/skills/      # 技能库：<name>/vN/{SKILL.md,references/,scripts/,templates/}
    └── chat/                   # 无生效工作区时的自由对话 cwd

{workspace.directory}/.smart-factory/
└── agents/{agentId}/
    ├── development/            # 生成阶段 cwd，智能体工程本体
    │   └── output/agents/{agentName}/{latest vN}/
    ├── preview/                # 预览沙箱（从 development 最新 vN 物化）
    ├── evaluation/             # 评估沙箱（从 preview 物化）与评估报告
    └── .state/                 # 物化标记（非阶段目录，产物浏览不可见）
```

- **智能体 = 一行元数据 + 一个产物目录**，`id` 是两者唯一的纽带，目录名就是 `id`。
- **智能体归属框架工作区**，`workspaceId` 建后不可改；内置智能体不属于任何工作区。
- **`status` 是派生字段**：由服务端读开发目录的过程状态、交付门禁与产物现算，取值 `not_started` / `building` / `blocked` / `failed` / `completed`，不落库。
- **先盘后库**：启动时收养磁盘上已有、表里没有的智能体目录，并幂等登记内置专家。

## 界面导览

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | 首页 | 一句话描述需求；五种能力：创建智能体、创建技能、优化智能体、优化技能、评估智能体 |
| `/agents` | 专家 · 技能 | 智能体列表（搜索、标签、来源与状态筛选）与技能库两个 tab |
| `/agents/:agentId/design` | 设计页 | 生成 / 预览 / 评估三阶段；`?stage=preview\|evaluation` 可直接落到某阶段 |
| `/workshop` | 技能开发 | 技能创建与优化的目录会话，右侧是技能文件树 |

- 卡片的「使用」不落在本模块：它整页跳去框架会话页。
- 内置专家只读：不设计、不评估，只提供「使用」。
- 被框架嵌入时（`window.self !== window.top`）自动收起侧边栏；`?embed=1/0` 可强制切换，便于调试。

## HTTP 与 WebSocket 接口

- 基址：`/api/smart-factory/v1`，REST 与 WebSocket 同端口、同前缀。
- 开发态前端经 vite 代理 `/api`，前端代码只写相对路径。
- 成功响应一律 `200`；错误响应格式与通用规范见 [4.02-通用规范](server/docs/04-api/4.02-通用规范.md)。

### REST

| 分组 | 端点 | 用途 |
|---|---|---|
| 探活 | `GET /health` | 进程存活即 200 |
| 智能体 | `GET/POST /agents`、`GET /agents/{id}`、`POST /agents/{id}/update`、`POST /agents/{id}/delete`、`GET /agents/tags`、`GET /agents/{id}/production`、`GET/POST /agents/{id}/skills`、`POST /agents/{id}/skills/remove` | 元数据、标签、产物状态、产物技能 |
| 工作区 | `GET /workspaces/list`、`GET /workspaces/directories/list` | 框架工作区只读代理（观测端清单） |
| 会话 | `GET /sessions/list`、`POST /sessions/create`、`GET /sessions/detail`、`POST /sessions/{id}/update`、`POST /sessions/delete`、`POST /sessions/abort` | 会话生命周期 |
| 消息 | `GET /messages/list`、`POST /messages/send`、`POST /messages/respond` | 消息流、发消息起 run、结算审批 / 交互 |
| 运行 | `GET /runs/list`、`GET /runs/detail`、`GET /runs/children`、`POST /runs/abort` | 顶层与子 run |
| 产物 | `GET /artifacts/list`、`GET /artifacts/file`、`GET /artifacts/download` | 四阶段目录只读浏览 |
| 评估 | `GET /evaluations/list`、`GET /evaluations/detail`、`GET /evaluations/cases/list`、`GET /evaluations/cases/detail` | 归一化评估报告 |
| 技能 | `GET /skills` | 技能库 + 当前工作区智能体产出的技能 |
| 模型 | `GET /models/list` | 框架模型只读代理，不含密钥 |
| 知识 | `GET /knowledge/workflows/list` | RAG Studio 已发布工作流只读代理 |
| 文件 | `POST /files`、`GET /files/{fileId}` | 上传与读取（封面图等） |
| 本机文件 | `GET /fs/roots`、`GET /fs/list`、`GET /fs/read`、`GET /fs/raw/*` | 整机文件树浏览与预览 |

完整端点表见 [4.01-接口总览](server/docs/04-api/4.01-接口总览.md)；智能体与文件两个域以 OpenAPI 契约为准（[5.01](server/docs/05-openapi/5.01-agent-openapi.yaml)、[5.02](server/docs/05-openapi/5.02-file-openapi.yaml)、[5.03](server/docs/05-openapi/5.03-agent-production-openapi.yaml)）。

### WebSocket

入口：`ws://localhost:4100/api/smart-factory/v1/ws`。

| 方向 | 方法 |
|---|---|
| 上行 | `send`、`subscribe` / `unsubscribe`、`message.respond`、`run.abort`、`ping`，以及兼容方法 `history`、`approval.respond`、`tool.respond`、`model.switch`、`mode.switch`、`effort.switch` |
| 下行 | `connection.ready`、`session.status`、`run.started` / `run.status`、`task.started` / `task.notified`、`message`、`chat.delta` / `chat.thinking` / `chat.final` / `chat.error` / `chat.aborted`、`approval.request`、`tool.interactive` / `tool.executing` / `tool.executed`、`error` |

- 实时事件**不回放**：断线重连或刷新页面时用 REST 补齐历史。
- `chat.delta` 与 `chat.thinking` 是瞬态增量，不落库，只用于边收边渲染。
- 审批与交互没有超时，服务端不会发出 `interactive.timeout`。

信封、载荷、心跳与背压细节见 [4.06-实时通道](server/docs/04-api/4.06-实时通道.md)。

## 项目结构

```text
smart-factory/
├── server/                       后端服务
│   ├── src/
│   │   ├── index.ts              进程入口：启动序、优雅退出、WS 网关
│   │   ├── app.ts                应用装配：中间件 + 路由挂载
│   │   ├── config/               环境配置集中读取
│   │   ├── modules/              能力域：agent / session / run / artifact / evaluation /
│   │   │                         skill / knowledge / files / fs / model / workspace / health
│   │   └── shared/               引擎、实时通道、仓储、工作区、技能、类型、错误
│   ├── prisma/                   schema 与 bootstrap.sql
│   ├── builtin-agents/           随包内置专家定义
│   ├── tests/                    单元、接口契约与 e2e 测试
│   └── docs/                     设计文档与 OpenAPI 契约
├── web/                          前端
│   ├── src/
│   │   ├── features/             能力域页面：home / agent-list / agent-create /
│   │   │                         skill-library / skill-workshop
│   │   ├── shared/               请求、实时客户端、通用组件、命令拼装
│   │   ├── i18n/                 zh-CN / en-US 词条
│   │   └── styles/
│   └── docs/                     前端交接与契约说明
├── scripts/                      dev.mjs 单入口：setup / start / stop / restart / status / e2e
└── .run/                         运行时产物：PID 与日志（已 gitignore）
```

约定：**前端一个 `features/<domain>` 对应后端一个 `modules/<domain>`**；跨域复用的东西才上升到 `web/src/shared/` 或 `server/src/shared/`。

## 开发与测试

```bash
# 后端
cd server
npm run typecheck          # tsc --noEmit
npm test                   # node --test（集成测试不监听端口）

# 前端
cd web
npm run typecheck
npm run build              # tsc -b && vite build
npm run check:i18n         # 词条完整性检查

# 端到端（fake 引擎 + 框架桩 + 独立数据目录）
node scripts/dev.mjs e2e
```

开发约定：

- **契约先行**：改接口先改 `server/docs/04-api/` 或 `05-openapi/`，再改实现；同一事实只允许出现在一处。
- **分层纪律**：路由不写逻辑，控制器不碰 store，服务层不出现 HTTP 概念。
- **前端词条**：`zh-CN.ts` 是形状的唯一真相，`en-US.ts` 受类型约束，漏翻译是编译错误。
- **目录即现场**：排查问题先看 `development/`、`preview/`、`evaluation/` 与 `.agent-genesis/` 下的实际文件，再对照数据库行。

## 文档

| 文档 | 内容 |
|---|---|
| [文档索引](server/docs/README.md) | 全部设计文档的唯一入口与命名约定 |
| [架构](server/docs/03-architecture/01-architecture.md) | 定位与边界、分层与目录、接口风格、配置、运行环境 |
| [数据模型](server/docs/03-architecture/02-data-model.md) | 五张表、状态机、seq 分配、级联与不变量 |
| [会话与运行](server/docs/03-architecture/03-session-run.md) | 四阶段目录、沙箱物化、生命周期编排 |
| [引擎接缝](server/docs/03-architecture/04-engine.md) | 引擎端口、注册表与适配器 |
| [实时通道](server/docs/03-architecture/05-realtime.md) | WS 信封、扇出、心跳与背压 |
| [审批与交互](server/docs/03-architecture/06-approval.md) | 审批即消息、结算协议、会话级 `approved_all` |
| [产物浏览](server/docs/03-architecture/07-artifact.md) | 四阶段目录的只读浏览与路径安全 |
| [智能体](server/docs/03-architecture/08-agent.md) | 元数据行与产物目录、状态、启动收养、标签 |
| [技能库与目录会话](server/docs/03-architecture/10-skill-library.md) | 目录实例、技能库扫描与工坊 cwd |
| [接口总览](server/docs/04-api/4.01-接口总览.md) | 基址、文档地图、REST / WS 端点总表 |
| [前端交接](web/docs/) | 能力路由、契约、环境变量与已知偏差 |

## 生态

Smart Factory 复用的技能由同仓库的插件提供：

| 插件 | 用到的能力 | 场景 |
|---|---|---|
| [agent-genesis](../agent-genesis/) | `harness-create`、`skill-foundry` | 创建 / 优化智能体，创建技能 |
| [goldeval](../agent-evaluator/) | `agent-eval`、`goldeval`、`traceaudit` | 生成测试集、执行、评分、轨迹审计 |
| [skill-optimizer](../skill-optimizer/) | `skill_optimize` | 评分驱动的技能迭代优化 |
| [drive](../drive/) | `drive` | 内置专家「软件研发团队」的多阶段交付流程 |
| [cosight-bot](../cosight-bot/) | `pkm`、`soc` | 内置专家「企业知识助手」的知识管理与标书应答 |

插件需在本机 Claude Code 中安装，技能才能被会话调用；缺失时内置专家会在 `CLAUDE.md` 中声明降级或如实说明不可用。

## 贡献

- 提交信息使用 `feat / fix / refactor / docs / test / chore / perf / ci` 前缀。
- 改接口先改契约文档，合入前跑对应「验收测试」映射的用例。
- 合入前至少通过：`server` 的 `typecheck` + `test`，`web` 的 `typecheck` + `build`；接口形状变更另跑 `node scripts/dev.mjs e2e`。
- 设计取舍写进 `99-adr/`（一决策一文件），过程记录不进正文文档。

## 许可证

本项目以 [Apache License 2.0](LICENSE) 许可发布。

本发行物**不包含、不分发** Anthropic 的 Claude Agent SDK 或 Claude Code CLI。真实执行引擎是可选集成：需要用户在自己的运行机上安装 Claude Code CLI，并接受 Anthropic 的条款。未安装时，创建、管理与浏览等核心功能照常可用，运行入口会给出安装指引。
