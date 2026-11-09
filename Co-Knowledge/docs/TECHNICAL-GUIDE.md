# Knowledge Studio 技术文档

> 本文是 Knowledge Studio 的完整技术说明，面向两类读者：
> **部署与使用者**（第 1、4、5、6、8 章）与**二次开发者**（第 2、3、7、9、10 章）。
> 全文自包含，不依赖仓库外的任何文档。
> 开头的[为什么做 Knowledge Studio](#为什么做-knowledge-studio)说明产品取向与主要技术选择；
> 第 1~10 章是具体的技术细节与操作指引。

---

## 目录

- [为什么做 Knowledge Studio](#为什么做-knowledge-studio)（[问题](#一我们要解决的问题) / [方案](#二技术方案) / [价值](#三交付价值)）
- [1. 系统概览与核心能力](#1-系统概览与核心能力)
- [2. 架构与数据流](#2-架构与数据流)
- [3. 组件详解](#3-组件详解)
- [4. 部署](#4-部署)
- [5. 功能指南](#5-功能指南)
- [6. 配置参考](#6-配置参考)
- [7. 接口契约](#7-接口契约)
- [8. 排错与 FAQ](#8-排错与-faq)
- [9. 运行前提与容量建议](#9-运行前提与容量建议)
- [10. 二次开发](#10-二次开发)

---

## 为什么做 Knowledge Studio

### 一、我们要解决的问题

Knowledge Studio 面向的是一类很普遍的处境：**自己手里有大量私有知识（规范、图纸说明、工单、
行业资料、产品文档），想让大模型真正用上它们**。这件事对使用者有五个具体的坎：

**1. 通用大模型「不知道你的知识」，答出来还不能信。**
模型只有公开语料训练出的通用知识：问它企业内部的规范、参数、流程，它要么答不上，
要么**一本正经地编**（幻觉）。直接拿它做业务问答是不可用的——答案必须**建立在用户自己的
文档上**，而且要能追溯引用了哪些片段。检索增强生成（RAG）正是为此而生，
但绝大多数用户手上没有这套系统，也不具备从零搭一套的条件。

**2. 知识散、格式杂，而且不只有「文本」。**
同一批知识散在 md / docx / xlsx / csv / pdf / pptx / html / txt 里，用户不想先做一次浩大的
格式归一工程。更要命的是，很多真问题是**关系型**的（某台设备属于哪个站点、某个参数被哪些
规程引用），关键词检索和向量检索都答不了——需要把文本抽取成实体与关系的知识图谱，
并支持图谱查询与图谱检索。

**3. 自己搭一套 RAG：组件门槛高，效果不好时无从下手。**
一套可用的 RAG 要同时具备解析、切片、向量检索、全文检索、图数据库、检索编排、模型接入……
每一环都要选型、调参、排错。而检索效果不理想时，使用者最常见的困境是**没有抓手**：
看不到召回了哪些片段，也改不了流程——要不要先改写问题？要不要重排？多个知识库谁优先？
业务人员不会写代码，更不可能去改检索链路。

**4. 数据不能出域，模型要用自己的。**
企业知识多为敏感资产：使用者不接受把文档交给外部 SaaS。要求是**全栈私有化部署**、
模型端点由自己指定（内网推理服务 / 自建 / 本地小模型），而且**不绑死任何一家模型**——
今天用远端 1024 维 embedding，之后要换本地模型，不能推倒重建。

**5. 交付环境不友好。**
目标环境常见：无外网、内核老（如 4.19，缺 `clone3`，Docker 默认策略下连线程都创建不出来）、
机器规格有限。使用者要的是**能离线部署、一条命令起得来、坏了查得到原因**的产品，
而不是一个需要专职团队伺候的「平台」。

> 这五条是产品要解决的**用户问题**；对应解法（组件选型、召回与编排技术）见第二节。

### 二、技术方案

**交付形态**：一套可自部署的完整平台——Docker Compose 一条命令起栈（前端 1 + 后端 1 +
存储 2，另有 1 个可选的本地 embedding 容器），对外一个 API 前缀。模型通过
OpenAI 兼容端点接入：embedding / 生成 / 重排都可指向使用者自己的服务（详见 §4.4）。

**组件选型**：

| 层 | 组件 | 在系统里做什么 |
|---|---|---|
| 前端 | Vue 3 + Element Plus + **@antv/x6**（画布） | 知识库管理、检索、**可视化编排画布**、对话测试页 |
| 后端 | Python 3.11 + FastAPI + uvicorn | 全部 API、异步导入任务、SSE 流式输出 |
| 向量存储 | **PostgreSQL 16 + pgvector** | 每个知识库一张向量表（`embedding vector(N)`，N 由该库 embedding 模型决定，并建 HNSW 索引），存切片向量；切片元数据（`content_expand`/`source`/`chunk_id`/`chunk_index`/`type`）**全部是同一行的物理列**，无 JSON 列、无嵌套 |
| 全文检索 | **OpenSearch 2.19 + analysis-ik** | 关键词 / 全文索引，每库一个索引 `doc_<kbId>`；文档为扁平 7 字段（`node_id`/`file_id`/`text`/`source`/`chunk_index`/`chunk_id`/`type`），`_id=node_id` |
| 图存储 | **PostgreSQL 16（JSONB）** | 每个图谱库两张表 `graph_<kbId>_vertex/_edge`，存实体与关系 |
| 文档处理 | 自研解析 / 切片管线（pdfplumber、pypdfium2 等） | md / docx / xlsx / csv / pdf / pptx / html / txt 的解析与切分 |
| 模型接入 | OpenAI 兼容端点（embedding / chat / rerank） | 路径、模型名、维度全部可配；两代维度（1024 / 768）可按库共存 |
| 部署 | Docker Compose + nginx | 单机全套；无外网环境可用 `--no-build` 复用镜像离线部署 |

**三条主链路**（细节见 §2.3、§5）：

- **入库**：建库（自动建向量表 / 全文索引 / 根目录）→ 上传文档（单文件上限按格式：
  md·docx 100MB / xlsx·csv·html 10MB / pdf 150MB / pptx 20MB / txt 5MB …，见 §4.8）→ 解析 → 切分 →
  向量化 → 双索引落位；
- **检索**：向量检索（`type=0`）或关键词检索（`type=1`），支持**多库分组与优先级**；
- **编排问答**：画布编排 → 发布 → 运行时按 DAG 执行「改写 → 检索 → 重排 → 合成」，
  支持 SSE 流式与多轮会话。

**召回与编排技术**

**1. 双路召回，按场景选。**
向量检索（`type=0`）把问题向量化后在 pgvector 里做相似度检索，问法不同、语义相近也能命中；
关键词检索（`type=1`）走 OpenSearch 全文，对编号、专有名词这类精确查询更稳。
两条路既可单独使用，也可在编排里并用。中文环境下关键词路采用**逐字匹配**口径
（`minimumShouldMatch("100%")`）压掉「查什么都能命中」的误报（代价与取舍见 §9.1）。

**2. 多库分组与优先级。** 一次检索可带多个知识库，按 `priority` 分组：高优先级库先查、
**命中即返回**——对应「权威库优先、通用库兜底」的组织方式（§5.2）。

**3. 查询改写。** 编排链路先用生成模型把用户原问题改写成更适合检索的问句；
多轮会话会把**上一轮问句**一并交给改写模型，追问（「那它的上限呢？」）能接上上下文。

**4. 重排（Rerank）。** 召回结果先重排、再进合成：默认 `LLMReranker`（复用生成模型，
零额外组件），也可接外部 rerank 端点（BGE 等）；按模型返回的相关性分数取前 N 条（§5.4）。

**5. 答案合成与流式输出。** 选中的片段拼进提示词交给生成模型；`stream=true` 时以 SSE
逐字下发（推理模型的 `<think>` 段先铺开、答完收起）；**没有命中时走显式兜底**，
不会假装检索过（§8.1）。

**6. 可视化编排：不写代码改流程。** 画布上拖节点连线即可组织检索链路。内置三种模板：
**顺序检索**（改写 → 检索 → 重排 → 合成）、**混合检索**（多路检索并行 → 融合 → 重排 → 合成）、
**条件检索**（按条件走不同分支）。草稿与**已发布快照**分离——改完点「发布」才生效，
运行时只读已发布版本（§5.4）。

**知识图谱：回答「关系型」问题**

Schema 定义 → 生成模型按 Schema 从文档抽取实体与关系 → 导入 PostgreSQL 图谱表；对外提供图谱查询
与图谱向量检索，可在编排里与文档检索并用（§5.5）。

**文档解析与切片**

- 支持 md / docx / xlsx / csv / pdf / pptx / html / txt；
- 默认切分「最大词数 512 / 重叠 128」（可配），另有「文件内容摘要切分」
  内置策略（系统算子 -1 / -2，见 §4.5）；
- **扩展点**：解析或切分策略不合用时，上传**自定义切分算子**（zip 包）即可，在沙箱内执行——
  行业私有格式不必等产品支持（§5.3）；
- 切分结果**双写**：正文与向量分别落 pgvector 和 OpenSearch，可用
  「向量数 == 切片数 == 全文文档数」核对索引一致性（§5.1.5）。

**安全与模型接入**

- **算子隔离**：自定义算子独立子进程执行，内存 500MB / 结果 10MB / 网络隔离尽力而为
  （无 `CAP_SYS_ADMIN` 时退化为环境白名单与 AST 检查）；算子按可信代码对待，
  导入仅管理员（§5.3.3）；
- **模型接入**：embedding / 生成 / 重排三类端点都可配（OpenAI 兼容，路径可改）；
  向量维度**写入前校验**（不符即显式失败，不静默截断），两代维度（1024 / 768）可按库共存（§4.4）；
- **鉴权**：默认 `local`（本地账号 + HttpOnly 会话），也可切 `none` / `gateway`；
  本产品有意不内置多租户（§6.2）。

### 三、交付价值

**1. 对使用者：一套开箱可用的私有知识问答底座。**
拿到仓库即可自部署（4 容器起栈，`.env` 一处配置）：建库 → 上传文档 → 切片 → 索引 →
检索/问答全流程可跑；业务人员**不写代码**就能用画布编排检索流程（改写 / 多库优先级 /
重排 / 合成），改完点「发布」即生效；问答支持 SSE 流式与多轮会话，检索页直接列出命中的
片段及其**来源文件**，答案依据可核对。
数据、模型、算力全在自己的环境里：embedding 与生成端点自选（远端 1024 维与本地 768 维
可按库共存），文档有解析不了的自定义格式时，可以上传自定义算子（沙箱内执行）。
关系型问题走知识图谱：Schema 定义 → 实体/关系抽取 → 图谱查询与检索全链路可用。

**2. 交付成效（当前版本实测）**：

| 维度 | 数值 |
|---|---|
| 起栈规模 | **4 个容器**（前端 1 + 后端 1 + PostgreSQL / OpenSearch 各 1）；可选 `model-gateway`（本地 embedding） |
| 对外接口 | **单一前缀 `/api/co-knowledge/v1`**，HTTP + SSE；集成方只需对接一个入口 |
| 问答链路（编排，经 nginx） | 流式**首字节 2.21s**、全程 5.04s |
| 图谱抽取端到端（小规模文档） | **≈6s**（自带分阶段耗时账单，可定位到解析 / LLM / 图库导入各占多少） |
| 文档格式支持 | md / docx / xlsx / csv / pdf / pptx / html / txt；单文件上限按格式 5–150MB |
| 模型自由度 | embedding / 生成 / 重排端点均可替换；1024 维与 768 维模型按库共存 |
| 自动化测试 | 前端 **936 条 / 91 个文件** + 后端 **2,417 条**（另有 7 条需基线库在场的差分用例默认 deselect），每次提交由 CI 全量运行 |

**3. 对运维与集成方：组件全是通用件。**
存储只用了 PostgreSQL（+pgvector）、OpenSearch 两个常见组件，运维体系可直接复用；
后端是一个进程，日志与状态集中，无服务发现、无消息中间件；模型端点、库口令、内存限额
都是 `.env` 一处配置；无外网环境可用 `--no-build` 复用镜像离线部署（§4.7、§6.2）。

**4. 对二次开发者：三个扩展点，不用改内核。**
① 文档格式或切分策略不合用 → 上传**自定义算子**（沙箱内执行）；
② 模型换代 → 改 `.env` 里的端点/模型名/维度，代码零改动（不同维度的库各自解析）；
③ 检索策略要变 → 在**画布**上改流程（增删节点、调优先级、换重排），发布即生效。
接口有契约可查（`contracts/`，OpenAPI + JSON Schema），改完可用 `tools/verify/` 的验收脚本自证。

---

## 1. 系统概览与核心能力

### 1.1 它是什么

Knowledge Studio 是一个可自部署的**知识工程平台**，围绕「把文档变成可检索的知识」这条主线组织，
对外提供**一个后端服务**（`rag-knowledge-base`）与一个统一前端，以及一套可选的本地模型容器。

核心能力：

| 能力 | 说明 |
|---|---|
| **知识库管理** | 建库、目录树、文件上传、导入编排、切片、索引 |
| **知识检索** | 向量检索（`type=0`）与关键词检索（`type=1`），支持多库分组与优先级 |
| **自定义算子** | 上传算子包 → 注册 → 在导入时指定 → 沙箱执行 |
| **检索编排** | 画布编排 → 保存 → 发布 → 运行时执行（改写→检索→重排→合成） |
| **对话测试** | 编排运行时的产品内入口（`/#/chat`）：流式（SSE）问答、多轮会话、Markdown 渲染 |
| **知识图谱** | 图谱库、Schema 管理、实体/关系抽取、图谱查询与检索（生成端点由使用方配置） |

### 1.2 运行前提与配套

部署前需要准备或确认的配套：

- **模型端点**：知识库检索需要 OpenAI 兼容的 embedding 端点，问答与抽图需要生成端点。
  可以接入外部模型服务，也可以启用可选的本地 embedding 容器（`model-gateway`）。
  详见 [`contracts/model-gateway.md`](../contracts/model-gateway.md)。
- **模型注册表**：在「模型管理」页注册 / 启停模型，保存即生效；`deploy/.env`
  负责首次播种与注册表不可用时的回落（见 §9.4）。
- **认证方式**：支持 `AUTH_MODE=none|local|gateway`。`local` 使用本地账号与会话
  （见 [`auth-login.md`](auth-login.md)）；私有化部署建议按实例划分租户边界。
- **异步任务**：使用进程内队列 + 数据库持久化，部署只需 PostgreSQL 与 OpenSearch，
  不需要额外的消息中间件。
- **工作流发布**：画布保存后发布，运行时读取发布快照；发布与验证都在控制台内完成。
- **CI 覆盖**：前端 vitest、后端 pytest（含 skip==0 断言）与 `ruff check src`；
  本地一键入口 `tools/run-tests.sh`（见 §10.4）。

### 1.3 技术栈一览

| 层 | 技术 |
|---|---|
| 前端 | Vue 3.5 + Element Plus 2.14.7 + Vue Router 4（**hash 路由**）+ Vuex 4 + @antv/x6（画布） |
| Python 服务 | Python 3.11；FastAPI 0.111（全部后端能力都在这一个服务里） |
| 检索编排 | **自研编排原语层**（`engine/primitives/`）：检索/查询/重排/合成/LLM 抽象与数据模型；含 vendor 的 tiktoken 词表（离线可用） |
| 存储 | PostgreSQL 16 + pgvector（业务表 + 向量 + 图谱实体/边）、OpenSearch 2.19（关键词索引） |
| 部署 | Docker Compose（服务定义含可选 `model-gateway`；默认启动 4 个） |
| 测试 / CI | 前端 vitest 5（Requires **Node ≥ 22**）· 后端 pytest 3.11 · ruff 0.17（只 check、不 `--fix`）· GitHub Actions（`.github/workflows/ci.yml`）；一键入口 `tools/run-tests.sh`（见 §10.4） |

---

## 2. 架构与数据流

### 2.1 组件全景

```
                        ┌─────────────────────────────┐
   浏览器 ──── :8080 ────▶ │  web (nginx)  唯一对外入口   │
                        │  静态资源 + 反向代理 + SPA   │
                        └──────────────┬──────────────┘
                                       │  /api/...
                        ┌─────────────────────────────┐
                        ▼
            ┌───────────────────────────────────────────┐
            │ rag-knowledge-base   （唯一后端）           │
            │  Python/FastAPI :8091                     │
            │                                           │
            │ 知识库/图谱资产管理                        │
            │ 知识库域接口 kb_api                        │
            │ 画布编排接口 flow_api                      │
            │ ingestion（进程内）解析/切分/算子沙箱      │
            │ engine（进程内）检索编排运行时              │
            │   改写→检索→重排→合成                      │
            └──────────────────┬────────────────────────┘
                               │
                               │ HTTP
                               ▼
 ┌─────────────────────────────────────────────┐  ┌───────────┐  ┌──────────────┐
 │ PostgreSQL 16 + pgvector                    │  │图谱实体/边 │  │ 外部模型端点   │
 │  rag_studio 库（唯一业务库）← RKB 写入       │  │  PG 表     │  │  embedding   │
 │  public + kb_index                          │  │graph_*_v/e │  │  (可自备)     │
 ├─────────────────────────────────────────────┤  └───────────┘  └──────────────┘
 │ OpenSearch 2.19     ← 关键词索引（共用实例）  │        ▲
 ├─────────────────────────────────────────────┤        │ 生成端点（必须自备）
 │ 共享卷 kb-storage   ← 上传文件（RKB 读写）   │  ┌───────────┐
 └─────────────────────────────────────────────┘  │model-gateway │（可选，本地 embedding）
                                                  │  Infinity    │
                                                  └───────────────┘
```

> **部署形态**：整栈 = **一个前端 + 一个后端**（`rag-knowledge-base`，内含 `ingestion`
> 与 `engine` 两个进程内模块）+ 两个存储组件。对外只有**一个路由前缀** `/api/co-knowledge/v1`
> （单点定义 `backend/src/shared/prefixes.py`）；`kb-storage` 由后端单进程读写。

### 2.2 对外路由（唯一入口 = `frontend/` 的 nginx，compose 服务名 `web`）

| URL 前缀 | 上游 | 说明 |
|---|---|---|
| `/api/co-knowledge/v1/` | `rag-knowledge-base:8091` | **后端全部接口**：知识库/内容/检索/图谱/算子/工作流/模型/Agent Key，REST 契约 65 条路径 / 93 个操作，全部挂在这一条前缀下 |
| `/api/co-knowledge/v1/query` | `rag-knowledge-base:8091` | 检索编排的提问（SSE）。nginx 里**单独一段 location**（最长前缀匹配优先），带三条流式配置（见 §3.4） |
| `/api/co-knowledge/v1/agent/` | `rag-knowledge-base:8091` | **Agent REST facade**：只读检索/问答 + OpenAPI；独立 location，`proxy_read_timeout 300s`。见 [`agent-integration.md`](agent-integration.md) |
| `/api/co-knowledge/v1/mcp` | `rag-knowledge-base:8091` | **Agent MCP**（Streamable HTTP）：独立 location，`proxy_buffering off` + HTTP/1.1 + 300s |
| 其余（`/`） | SPA `index.html` | hash 路由回退 |

> ⚠️ **前端是 hash 路由**，页面地址形如 `/#/knowledge`、`/#/flow`，**不是** `/knowledge`、`/flow`。
> 直接访问不带 `#` 的路径会命中 SPA 回退拿到 `index.html`，然后因为匹配不到路由而表现为「点不动 / 白屏」。
>
> ⚠️ 后端**只有一个前缀** `/api/co-knowledge/v1`（编排的 `/query` 也在其下）。
> RKB 默认不向宿主发布 8091。
>
> ⚠️ **打错前缀不会报 404**：任何没被 nginx 反代的 `/api/...` 都会落到 SPA 回退，
> 拿到 **HTTP 200 的 `index.html`**——前端只报「网络错误」，没有线索指向路由。
> 判别方法：看响应的 `Content-Type` 是不是 `text/html`。

### 2.3 三条主链路

#### 链路 A：文档入库（建库 → 上传 → 切片 → 索引）

```
① 建知识库  POST /api/co-knowledge/v1/knowledge-bases
   ├─ 写 kb_kbase（PostgreSQL）
   ├─ 建向量表 kb_index.doc_<kbId>_vector（+ _chunk）
   ├─ 建 ES 索引 doc_<kbId>
   └─ 建根目录 Default|folder

② 上传文件  POST /api/co-knowledge/v1/knowledge-bases/<kbId>/documents
   └─ 文件落盘到共享卷 kb-storage（路径形如 /data/kb/core/<fileId前4位>/<fileId>）
      或 MinIO（RKB_STORAGE_BACKEND=minio，对象键相同；见 §4.6）

③ 导入编排（异步；解析 / 切分为 `ingestion` 模块的**进程内调用**）
   ├─ RKB（进程内）: ingestion.runtime.file_parse(...)
   ├─ RKB（进程内）: ingestion.runtime.text_split(...)
   │     （用系统算子 -1 或你指定的自定义算子完成切分）
   ├─ 切分结果写回 chunk 表 kb_index.doc_<kbId>_chunk
   └─ 向量化：RKB ──HTTP──▶ embedding 端点 ──▶ 写向量列 vector(N)

④ 索引状态
   └─ 向量表行数 == chunk 行数；ES 文档数 == chunk 数（一致性口径见 §5.1.5）
```

> `kbId` 新库为 **16 位十六进制（64 bit）**，既有库可能为 32 位 uuid；所有路径把它当不透明字符串处理，不假设固定长度。

#### 链路 B：知识检索

```
POST /api/co-knowledge/v1/retrieval
  body: { question, type: 0|1, bases:[{baseList:["doc_<kbId>"], priority:0}] }

  type=0 向量路 ──▶ 问题向量化 ──▶ PostgreSQL pgvector 相似度检索
  type=1 关键词路 ─▶ OpenSearch 全文检索

  多库：按 bases[].priority 分组，高优先级先查；命中即返回（不会继续查低优先级库）
```

#### 链路 C：检索编排（画布 → 发布 → 执行）

```
前端 /#/flow 列表 → 新建/编辑 → 画布 /#/flow/detail/<appId>
  └─ 拖节点连线 → 保存（写草稿）→ 点「发布」（写已发布快照）

发布快照落 rag_studio 库的 flow_published 表

执行： POST http://<rag-knowledge-base>:8091/api/co-knowledge/v1/query
       { question, conversation_id, workflow_id, stream }
  └─ 编排运行时（同进程内）读已发布快照，按 DAG 执行：
       查询改写 → 检索（**进程内**调用知识库域服务）→ 重排 → 答案合成
       stream=true 时以 text/event-stream 返回 SSE
```

> ⚠️ **编排只读「已发布」快照**。改了画布必须重新点「发布」才生效；
> 未发布就调 `/query` 会明确报「没有已发布的版本」，而不是拿草稿跑。

### 2.4 数据归属（每张表只有一个写入方）

| 库 / Schema | 写入方 | 内容 |
|---|---|---|
| **`rag_studio` 库 · schema `public`** | `rag-knowledge-base` | 业务表：`kb_kbase`、`kb_directory`、`kb_node_relation`、任务表、算子三表、图谱四表、`flow_*` 三表、`model_registry` |
| `rag_studio` 库 · schema `kb_index` | `rag-knowledge-base` | 每库一对向量/chunk 表（运行时按 `kbId` 建）；图谱库导入后另有 `_vector` 检索索引 |
| OpenSearch | `rag-knowledge-base` 独用**同一实例** | 知识库域建 `doc_<kbId>`；图谱/资产域索引无前缀 |
| `rag_studio` 库 · `graph_<kbId>_vertex/_edge` | `rag-knowledge-base` | 图谱实体/边 |
| 共享卷 `kb-storage` | `rag-knowledge-base` | 上传文件落盘与读取（容器内挂载点 `/data/kb`）。**挂载路径不可改**，见下；也可选 MinIO 后端（持久文件进桶，本地卷仍保留给算子包/锁/scratch） |

> **单库**：全栈只有一个 PostgreSQL 业务数据库 `rag_studio`。
>
> **逐表结构与列语义**见 [`docs/database-schema.md`](database-schema.md)
> （含动态表 DDL、状态码、已知不一致与常用诊断 SQL）。

### 2.5 契约体系

`contracts/` 是接口契约的**唯一来源**，任何模块不得私造第二份定义：

| 文件 | 类型 | 内容 |
|---|---|---|
| `contracts/VERSION` | 版本号 | 当前 **2.3.0**，与 `contracts/openapi/rkb-api.yaml` 的 `info.version` 一致 |
| `contracts/openapi/rkb-api.yaml` | OpenAPI 3.0.3 | 全量 REST 契约：**65 条路径 / 93 个操作**，由 `tools/verify/generate-rkb-openapi.py` 从运行期路由生成 |
| `contracts/openapi/agent-api.yaml` | OpenAPI 3.0.2 | Agent REST 子应用契约（6 条路径），版本独立演进（当前 1.4.0） |
| `contracts/schemas/*.json` | JSON Schema 2020-12 | 9 个跨模块共享对象（知识库 / 文档 / 切片 / 算子 / 任务 / 检索 / problem / 分页） |
| `contracts/model-gateway.md` | 契约文档（**非 OpenAPI**） | embedding / 生成 / rerank 的接入边界与配置 |

共享 Schema 一览：

| Schema | 顶层 required | 用途 |
|---|---|---|
| `knowledge-base.json` | `id`, `name` | 知识库对象；`tableName` / `esIndexName` 为派生字段 |
| `document.json` | `id`, `kbId`, `type` | 文档/目录；`status` 用整数编码（0 初始 / -1..-5 各中间态 / 1 成功 / 2 失败） |
| `chunk.json` | — | `$defs`：`ChunkNode` 与 `ChunkRecord` |
| `operator.json` | `name`, `displayName`, `module`, `version` | 算子元数据；`id` 为负数是系统算子（-1 默认切分 / -2 摘要切分） |
| `operator-exec.json` | — | `$defs`：`ExecutionContext` 与 `SandboxLimits`（内存 500MB、结果 10MB、网络隔离尽力而为） |
| `search.json` | — | `$defs`：`SearchRequest` 与 `SearchResult` |
| `task.json` | `taskId`, `status` | 任务对象；`taskType` / `status` / `ErrorCode` 枚举 |
| `problem.json` | `type`, `title`, `status` | RFC 9457 错误对象 |
| `page.json` | `items`, `total`, `page`, `pageSize` | 分页响应 |

> `rkb-api.yaml` 与运行期路由的一致性由 `backend/tests/test_rkb_openapi_snapshot.py` 锁定；
> 改接口后跑 `python3 tools/verify/generate-rkb-openapi.py` 重新生成。

---

## 3. 组件详解

### 3.1 `ingestion` — 文档处理模块（解析 / 切分 / 算子沙箱）

- **代码位置**：`backend/src/ingestion/`（`config/`、`utility/`、`service/`、
  `split/`、`runtime.py`、`tests/`、`sql/`）；解析/切分库在 `src/parsing/`，
  系统算子入口在 `src/operators/`，算子模型客户端在 `src/model/operator_client.py`。
- **入口**：`ingestion/runtime.py`（`file_parse` / `file_parse_preview` / `text_split` /
  `graph_extract` / 三个 `code_check_*` / `system_operators`）；
  后端经 `src/knowledge_base/task/operator_runtime.py` 适配调用，语种固定 `zh_CN`。
- **能力**：多格式文档解析（md / docx / xlsx / csv / pdf / pptx / html / txt）、文本切分、
  图谱抽取、**自定义算子的沙箱执行**、算子代码安全检查（`code-check`）。
- **系统算子注册表**：唯一真源是 `ingestion/split/operator_all.json`（**只读静态数据**，2 个内置算子：
  `-1` 默认切分方法 / `-2` 文件内容摘要切分，**不落库**）。
  `-1` 与 `-2` 共用 `operators/text_split` 入口，用 `operator_function` 区分。
- **沙箱**：两条执行路径（自定义算子 `utility/self_operator.py`、系统算子 `utility/operator_zip_action.py`）
  共用 `utility/sandbox_runtime.py` 做子进程装配（multiprocessing 上下文、预载、环境白名单）；
  用 **forkserver** 上下文（子进程基线更小更确定，内存配额判定才有意义），
  预载列表**显式排除 `'__main__'`**（否则后端入口的常驻线程会在每个沙箱子进程里各起一份）。

### 3.2 `backend` — 统一后端（Python / FastAPI）

- **技术**：Python 3.11 + FastAPI 0.111 + uvicorn 0.27（依赖含 `pdfplumber`、`pypdfium2` 等；
  编排层的检索/查询/LLM 抽象为**自研原语层**，见 §3.3 与 §1.3）
- **入口**：`src/main.py` → `src/app.py`（唯一 import 根为 `src/`）
- **端口**：8091；对外前缀 **`/api/co-knowledge/v1`**（单点定义 `src/shared/prefixes.py`，见 §2.2）
- **镜像**：`python:3.11.18-slim`（钉死 patch，见 `backend/Dockerfile`）

**职责**：知识库与图谱资产管理、画布编排接口、检索编排运行时（见 §3.2），
以及文档解析 / 切分 / 算子沙箱（`ingestion/` 模块，见 §3.1）。
对外实际暴露的只有 `/api/co-knowledge/v1` 这一条。

**代码结构**：

```
src/
├── app.py / main.py / startup.py   ← 装配点与进程入口
├── infrastructure/                 ← auth/config/crypto/db/http/i18n/logging/search/storage/transport
├── shared/                         ← prefixes/problem/errors/chunk_schema/i18n
├── knowledge_base/                 ← 知识库/目录/文档/切片（api/service/repository/tasks）
├── graph/                          ← 图谱 schema/抽取/导入/查询/导出
├── operators/                      ← 算子注册/导入/模板/沙箱/系统算子
├── workflow/                       ← 画布/校验/发布/templates
├── engine/                         ← RAG 运行时（改写 / 检索 / 重排 / 合成）
├── chat/                           ← POST /query + SSE、翻译层、RKB 适配器
├── model/                          ← 模型注册表/网关/端点解析
├── agent/                          ← Agent REST/MCP/Key
├── ingestion/                      ← 解析→清洗→切分→抽图管线 + 算子沙箱
├── system/                         ← /system、/health、系统端点
└── parsing/                        ← 纯格式解析库
```

**`src/` 还包含**（见 §3.1）：`ingestion/`（含 `config/`、`utility/`、`service/`、
`split/`、`tests/`、`sql/`）与解析库 `parsing/`。

**编排快照存储**：`src/workflow/repository_pg.py` 的三个表
`flow_workflow` / `flow_config` / `flow_published`，落在 `rag_studio.public`；
首次请求时由 `_ensure_schema` 幂等建表（`FLOW_SCHEMA_STATEMENTS` 是唯一 DDL 来源）。

> `flow_api` 只注册一次（`/api/co-knowledge/v1`），成功体是纯 JSON
> （分页 `{items,total,page,pageSize}`），错误是 problem+json（见 §7.2）。

### 3.3 检索编排运行时（`engine/`）

- **代码位置**：`backend/src/engine/`；四段领域代码在 `pre_retriever/`、`retriever/`、`post_retriever/`、`response_synthesizer/`，
  画布 → 运行时的翻译在 `translator.py`（边按画布 DAG 生成，条件分支靠它分路）。
- **编排原语层**（`backend/src/engine/primitives/`）：检索器/查询引擎/后处理器/合成器/
  改写器/选择器/LLM 的**抽象与数据模型**为自研实现（Node/NodeWithScore/QueryBundle/Response、
  选择器与重排的解析链、四种融合、PromptHelper 截断、Router/Transform/Retriever 引擎、
  提示词模板族）；组件行为由单测与 E2E 覆盖，关键解析链有逐字断言。
  默认 prompt 文本与少数保留的格式来自 llama-index-core 0.10.31
  （MIT，见各文件头的归属注释）。
- **对外端点**（挂在 `/api/co-knowledge/v1` 下）：`POST <prefix>/query`（`stream=true` 时 SSE）。
  健康检查统一由 kb_api 的 `GET <prefix>/health` 提供。
- **对知识库域的调用是进程内调用**：检索 / 库列表 / 画布配置 / 图谱检索四条
  （见 `chat/gateways/rkb_transport.py`），不跨进程、不走 HTTP。
- **配置**：`GENERATION_GATEWAY_URL` / `GENERATION_MODEL` / `GENERATION_MAX_TOKENS` /
  `GENERATION_TEMPERATURE` / `GENERATION_TIMEOUT` / `RERANK_URL` / `RERANK_MODEL`。
  ⚠️ `LOG_DIR` **不要**指到创建不出来的路径：目录创建失败会让整个后端在 import 期起不来。
- **敏感词屏蔽**：词表目录由 `BLACK_LIST_DIR` 指定（默认 `/app/black_list`），
  加载器 `engine/config_loader/black_list_loader.py`；目录不存在 = 没有黑名单
  （只记一条日志）。⚠️ **要真生效还差三步**（缺任何一环都是静默的）：① 把词表目录挂进容器
  （**镜像里没有 `/app/black_list`**）；② 目录里放 `<词表名>.txt`，词之间 `|#|` 分隔；
  ③ 画布里用黑名单的合成算子填 `black_vocabulary: <词表名>`。**没有热更新**——
  换词表要重启容器或显式调 `reload_black_list()`。
- 运维影响两条：**编排异常会表现为 RKB 容器 unhealthy**（随之重启整个容器）；
  **RKB 只能单副本**（多轮缓存是进程内的）。

#### 3.3.1 `POST <prefix>/query` 契约

```json
{ "question": "...", "conversation_id": "...", "workflow_id": "RAG_Workflow_xxxx", "stream": false }
```

执行流程：**查询改写 → 检索（进程内）→ 重排 → 答案合成**；`stream=true` 用 SSE。
错误响应的 HTTP 状态**恒为 200**，业务码放在 body 的 `code` 字段。

> ⚠️ 日志写在容器内 `LOG_DIR`，**不输出到 `docker logs`**。查看方式见 §8.4。

### 3.4 `frontend`（compose 服务名 `web`）— 统一前端（Vue 3 → nginx）

- **技术**：Vue 3.5 + Element Plus 2.14.7 + Vue Router（hash）+ Vuex + @antv/x6
- **构建**：`node:22.23.3-alpine` 构建 → `nginx:1.27.5-alpine` 运行；**宿主默认 8080 → 容器 80**。
  根路径部署：`frontend/.env` 与 `.env.production` 均为 `BASE_URL=/`，直接
  `npm run build` 即可，产物资源路径为 `/js/...`、`/css/...`。
- **接口寻址**：`VUE_APP_KBASE_BASE` / `VUE_APP_WORKFLOW_BASE` / `VUE_APP_QUERY_BASE`
  都指向 `/api/co-knowledge/v1`。
  本地 `npm run serve` 需要 `frontend/.env.local` 里有 `VUE_APP_API`（缺它会让 devServer 的 proxy
  出现 `target: undefined` 条目，webpack-dev-server 直接崩在 node_modules 里、报错完全指不到配置上）。
- **配置**：`frontend/nginx.conf`（路由 + `client_max_body_size 650m` + `resolver 127.0.0.11`）。
  ⚠️ `/api/co-knowledge/v1/query` 有**单独一段 location**（SSE 专项，靠最长前缀匹配优先于通用段）：
  `proxy_read_timeout 300s`——编排侧生成超时默认 120s，nginx 默认只有 60s，
  不给足会被先掐成 504（症状：后端日志显示生成成功、前端显示失败）；外加三条**缺一不可**的
  SSE 指令（`proxy_buffering off` / `proxy_http_version 1.1` / `Connection ""`），
  少任何一条都表现为「卡住不动、然后一次性全出来」。

**页面路由**（hash）：

| 路由 | 页面 |
|---|---|
| `/#/login` | 登录页（**默认页**：`/` 重定向到此，与 UX 原型一致） |
| `/#/knowledge` | **文档知识库**列表 |
| `/#/knowledge/detail/:id` | 知识库详情（数据集/分块 + 基本信息） |
| `/#/knowledge/detail/:id/documents` | 文档管理（目录 + 文件表格） |
| `/#/graph` | **图谱知识库**列表（页内「知识图谱 / 知识图谱模版」子页签，`?subTab=` 直达） |
| `/#/graph/detail/:id`、`/#/graph/edit/:id`、`/#/graph/create` | 图谱详情 / 编辑 / 新建 |
| `/#/graph/createTemplate/:templateId` | 图谱模板设计器 |
| `/#/flow`、`/#/flow/detail/:id` | 知识检索列表 / 画布 |
| `/#/chat` | **对话测试页**：SSE 流式问答、多段历史、多轮会话、Markdown 渲染 |
| `/#/operators` | 自定义算子 |
| `/#/models` | 模型管理 |
| `/#/access`、`/#/keys` | 接入方法 / 密钥管理 |
| `/#/change-password` | 强制改密 |

> 未注册的地址没有重定向也没有别名，由全局兜底落到 `/#/knowledge`。

**左栏导航**：知识库（分组）、知识检索、对话测试、自定义算子、模型管理、远程接入（分组），
唯一真值是 `frontend/src/app/layout/nav/menu.config.js`（不从 router 的 `meta` 生成：
菜单顺序、分组、图标不是路由属性，且知识库组还有「子页归哪一项高亮」这层映射）。
`/knowledge/detail/*`、`/graph/detail/*` 等子页由页内导航进入，不进菜单。

**调用约定**：axios 拦截器直接返回 `res.data`（没有 `bo` 信封），
业务代码拿到的是资源对象 / 分页体本身；失败统一 reject `ApiError`
（`status/code/detail`，见 §7.2）。**不要再读 `res.bo` 或 `code.code`**。

### 3.5 基础设施

| 容器 | 镜像 | 作用 | 备注 |
|---|---|---|---|
| `postgresql` | `pgvector/pgvector:0.8.7-pg16` | 业务表 + 向量表 | **唯一**业务库 `rag_studio`（由 `POSTGRES_DB` 自动创建） |
| `opensearch` | `ragstudio/opensearch:2.19.6-ik`（官方 2.19.6 + analysis-ik，插件包离线安装） | 关键词索引 | 中文 `ik_smart` 分词；Apache-2.0；需宿主 `vm.max_map_count ≥ 262144` |
| `model-gateway`（**可选**） | `michaelf34/infinity:0.0.77-cpu` | 本地 embedding 推理 | 由 `profiles: ["local-embedding"]` 门控，**默认不启动** |

### 3.6 凭据与数据库权限

- **非 superuser 应用角色**：RKB 默认用 `rag_app` 连接（`RKB_DB_USER`），
  只具备业务库的 CONNECT/CREATE、`kb_index` 动态表 DDL、静态表 DML；
  不能建扩展/库/角色。空卷由 `deploy/init/pg/05-app-role.sh` 自动创建。
- **`model_registry.api_key` 静态加密**：AES-256-GCM，落库 `enc:v1:<base64>`，
  读侧透明解密；密钥来自 `RKB_SECRET_KEY` 或 `RKB_SECRET_KEY_FILE`
  （默认在 `rkb-storage` 卷内自动生成）。
- 详见 `docs/security-hardening.md`。

---

## 4. 部署

### 4.1 前置条件

- Docker ≥ 24 + `docker compose`（v2）；构建本地镜像需要 buildx ≥ 0.17
- 磁盘 ≥ 20 GB（镜像 + OpenSearch/PG 数据）；内存建议 ≥ 6 GiB 可用；
  启用 `local-embedding` 时另需约 2 GiB 内存与约 2 GB 镜像 + 391 MB 权重
- OpenSearch 需要宿主内核参数：

  ```bash
  sudo sysctl -w vm.max_map_count=262144
  # 持久化：echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf
  ```

- 能拉取 Docker Hub 镜像
- **一个可达的 OpenAI 兼容 embedding 端点**（见 §4.4）

> ⚠️ **内核 < 5.3 的环境**：本项目 compose 已为各容器写入 `security_opt: [seccomp:unconfined]`。
> 原因是老内核无 `clone3` 系统调用，Docker 默认 seccomp 会让 JDK 21 / glibc 2.36 创建线程失败
> （`pthread_create failed (EPERM)`）。
> **这是安全降级**——现代内核（≥ 5.3）应当删除该项。

### 4.2 快速开始（4 容器）

```bash
cd <仓库根目录>
cp deploy/.env.example deploy/.env
# 至少改 POSTGRES_PASSWORD
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps     # 默认启动的容器应全为 (healthy)
```

> ⚠️ `.env` 要放在 **`deploy/` 目录下**（与 compose 文件同目录），compose 才会自动读取。

默认启动的 4 个容器：

| 容器 | 作用 | 宿主端口 |
|---|---|---|
| `web` | nginx 静态资源 + 反向代理（**唯一对外入口**） | **8080**（`WEB_PORT` 可改） |
| `rag-knowledge-base` | 知识库域 + 图谱资产管理 + 画布编排 + 文档解析 / 切分 / 算子沙箱 + 检索编排运行时 | 不暴露 |
| `postgresql` | 业务表 + 向量表 | 127.0.0.1:5432 |
| `opensearch` | 关键词全文索引 | 127.0.0.1:9200 |

容器名由 compose 生成，形如 `rag-studio-<service>-1`（顶层 `name: rag-studio`）。

> compose 另有可选服务定义 `model-gateway`（本地 embedding，`profiles: ["local-embedding"]`）
> 与 `minio`（对象存储后端，`profiles: ["minio"]`），默认都不启动。

**开发态**：叠加 `deploy/docker-compose.dev.yml`（**不新增服务**）：

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d
```

它把业务服务（`web`、`rag-knowledge-base`，编排的源码在后者内）改成挂源码 + 热重载
（`web` 换成 `node:20-alpine` 跑 `vue-cli-service serve`）；基础设施（`postgresql` / `opensearch`）
的 `127.0.0.1` 调试端口由主文件直接绑定，override 不再重复声明。

### 4.3 健康检查

```bash
# 经 web 反代（localhost:8080）
curl -fs http://localhost:8080/                              # → 200（前端首页）
curl -s  http://localhost:8080/api/co-knowledge/v1/health             # → ok（全栈唯一健康端点，纯文本）
# ⚠️ 只有 /api/co-knowledge/v1 这一条前缀经 nginx 反代；其他 /api/... 路径会落到 SPA 回退，
# 拿到 200 的 index.html 而不是 404（见 §2.2）。
```

`rag-knowledge-base` 的健康端点也只有这一条（镜像里没有 curl），需要进容器验证：

```bash
C="docker compose -f deploy/docker-compose.yml"
$C exec rag-knowledge-base python3 -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8091/api/co-knowledge/v1/health',timeout=3).read().decode())"
```

### 4.4 模型接入（必读）

模型通过 OpenAI 兼容端点接入。两类端点分别配置：

#### embedding（首条链路的硬前置）

| 模式 | 端点 | 模型 | 维度 |
|---|---|---|---|
| **远端**（默认） | `MODEL_GATEWAY_URL` + `MODEL_GATEWAY_EMBEDDINGS_PATH`（默认 `/v1/embeddings`） | `Qwen3-Embedding-0.6B` | 1024 |
| **本地**（可选容器） | `http://model-gateway:8000` + `/embeddings` | `BAAI/bge-base-zh-v1.5` | 768 |

验证端点：

```bash
set -a; . deploy/.env; set +a
curl -s "$MODEL_GATEWAY_URL$MODEL_GATEWAY_EMBEDDINGS_PATH" \
  -H 'Content-Type: application/json' \
  -d '{"input":["你好"],"model":"Qwen3-Embedding-0.6B"}' \
  | python3 -c 'import sys,json; print("dim =", len(json.load(sys.stdin)["data"][0]["embedding"]))'
# 期望：dim = 1024
```

> ⚠️ **容器里也要能通**——宿主能通不代表容器能通：
> ```bash
> docker compose -f deploy/docker-compose.yml exec rag-knowledge-base env | grep -i no_proxy
> ```
> `NO_PROXY` / `no_proxy` 里必须能看到该端点的主机。容器会继承宿主 `http_proxy`，
> 域名没被排除时请求会被代理接走，报 `Tunnel connection failed: 302 Moved`，
> **症状长得像 embedding 服务自身故障**。
>
> ⚠️ 路径必须可配：远端是 `/v1/embeddings`，本地 Infinity 是 `/embeddings`（它不提供 `/v1` 前缀）。
>
> ⚠️ **维度必须与实际输出一致**（`EMBEDDING_DIMENSION`）。维度不符时**建索引会显式失败**，
> 不会静默截断或补零。

**切到本地 embedding**：

```bash
docker compose -f deploy/docker-compose.yml --profile local-embedding up -d model-gateway
# 并把 deploy/.env 改为：
#   MODEL_GATEWAY_URL=http://model-gateway:8000
#   MODEL_GATEWAY_EMBEDDINGS_PATH=/embeddings
#   EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5
#   EMBEDDING_MODEL_NAME=bge-base-zh-v1.5
#   EMBEDDING_DIMENSION=768
```

两层模型可共存（按每个知识库的 `embedding_model` 字段分别解析）。

#### 生成模型（检索编排 / 图谱抽取的硬前置）

平台**不自带生成模型**。要让编排跑通，必须指向一个真实的 OpenAI 兼容端点：

```bash
GENERATION_GATEWAY_URL=http://<你的端点>/v1   # OpenAI 兼容
GENERATION_MODEL=your-chat-model
GENERATION_API_KEY=<只放 deploy/.env，不要提交>
GENERATION_MAX_TOKENS=16384
GENERATION_HOST=<端点主机>                     # 让容器 NO_PROXY 排除它
```

> ⚠️ **`GENERATION_MAX_TOKENS` 别漏设**。`.env.example` 给的是 `16384`，
> 但 compose 在没有该项时的兜底默认只有 `2048`。
> 推理模型会先输出 `reasoning_content`，预算给小了会出现 `content` 为空 + `finish_reason=length`
> —— **HTTP 200、看起来成功，其实没答案**。
>
> ⚠️ **模型清单的权威来源 = `model_registry` 表**：在「模型管理」页
> （`#/models`）注册，或调 `{RKB_PREFIX}/models`。保存即生效，**不需要重启**。
> `deploy/.env` 的 `GENERATION_MODELS` 降级为**首次播种 + 回落**：
> 首次启动把它播种进注册表；注册表读不到时逐项回落它。
> 格式仍是 `模型名=显示名;模型名=显示名`，**值必须带引号**：用 `set -a; . deploy/.env`
> 取值时，分号会被 shell 当命令分隔符，变量被静默截断成只剩第一项——不在 `.env` 这层报错，
> 只表现为容器里少了几个模型。
>
> ⚠️ **可以没有 rerank 端点**。`RERANK_URL` 留空时：保存会提示、发布会拒绝、运行时显式报错
> （`rerank-endpoint-not-configured`），而不是静默按原顺序返回。默认工作流用 `LLMReranker`
> （复用生成模型做重排），不需要额外组件。

### 4.5 最小链路验证（建库 → 导入 → 检索）

```bash
BASE=http://localhost:8080

# 5.0 登录（AUTH_MODE=local；首次管理员密码见容器内 /data/rkb/initial-admin-password）
curl -s -c cookies.txt -X POST "$BASE/api/co-knowledge/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<密码>"}'

# 首次登录若 must_change_password=true，先改密：
#   curl -s -b cookies.txt -X POST "$BASE/api/co-knowledge/v1/auth/password" \
#     -H 'Content-Type: application/json' \
#     -d '{"currentPassword":"<密码>","newPassword":"<新密码>"}'

# 5.1 创建知识库（文档库：不带 type 参数；图谱库才加 ?type=graph）
KB=$(curl -s -b cookies.txt -X POST "$BASE/api/co-knowledge/v1/knowledge-bases" \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo-kb","props":{"embeddingModel":"Qwen3-Embedding-0.6B"}}')
KBID=$(echo "$KB" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 5.2 取默认目录（返回数组，取第一个文件夹）
DIRID=$(curl -s -b cookies.txt "$BASE/api/co-knowledge/v1/knowledge-bases/$KBID/directories?type=folder&sort=true" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')

# 5.3 上传文档（用系统算子 -1 切分）
curl -s -b cookies.txt -X POST "$BASE/api/co-knowledge/v1/knowledge-bases/$KBID/documents" \
  -F "files=@deploy/init/seed/sample-zh.md" \
  -F 'metadata={"kType":"outer-document","directoryId":"'$DIRID'","splitType":"system","parseOperator":{},"splitOperator":{"md":{"operatorId":-1,"fileFormat":"md","args":[{"argName":"maxWordCount","argType":"int","defaultValue":512},{"argName":"overlap","argType":"int","defaultValue":128}]}}}'

# 5.4 检索（向量路 type=0）
curl -s -b cookies.txt -X POST "$BASE/api/co-knowledge/v1/retrieval" \
  -H 'Content-Type: application/json' \
  -d '{"question":"什么是 RAG","type":0,"bases":[{"baseList":["doc_'$KBID'"],"priority":0}]}'
```

**上传元数据的必填约束**（最容易踩的地方）：

- `splitOperator` **整个键必填**：缺席会走业务错误；`parseOperator` 可省略（等价于 `{}`，表示不做额外解析）。
- 每个算子条目必须有 `operatorId`，且 `args` 存在且不为 `null`；`args: []` 是合法的
  （系统算子会使用注册表里的默认参数）。
- `splitOperator` 以**文件扩展名**为键（`md` / `pdf` / `docx` / `txt` / `csv`）。
- 系统算子用**负 id**，自定义算子用**正 id**。
- 系统算子默认值来源（唯一真源）：`backend/src/ingestion/split/operator_all.json`
  （`maxWordCount` 默认 512，`overlap` 默认 128，须小于 `maxWordCount`；系统算子不落库，见 §3.1）。

### 4.6 首次初始化与数据卷

**单库**：PostgreSQL 官方镜像按 `POSTGRES_DB`（默认 `rag_studio`）在 `pgdata` 卷为空时
自动创建唯一业务库。静态表由 `deploy/init/pg/00-schema.sql` 在空卷上创建；
`flow_*` / `model_registry` 等表由应用在首次使用时幂等自建；
动态 `doc_*` / `graph_*` 表按库创建。

**命名卷**：`pgdata`、`osdata`、`kb-storage`（上传文件卷）、`rkb-storage`、
`model-cache`、`miniodata`（可选，仅 `--profile minio`）。

> ⚠️ `kb-storage` 的挂载路径不可改（默认 `/data/kb`，RKB 以 `RKB_KBASE_STORAGE_PATH` 指向它）。
> **local 后端**下任务里的 `diskPath` 是**绝对路径**，已有数据要求挂载点保持不变——
> 换路径会让已入库的文件全部读不到。
>
> **对象存储（可选）**：`RKB_STORAGE_BACKEND=minio` 时，持久文件
> （`core/`、`pict/`、`dump/`）写 MinIO；对象键与本地相对路径一致
> （`core/<id 前 4 位>/<id>`），解析/切片前由 `storage.materialize_ref()` 物化到
> `RKB_STORAGE_TEMP_PATH`。算子包、名称锁、清洗中间件**仍留在本地卷**，所以
> `kb-storage` 不能省。

### 4.7 停止、清理、离线部署

```bash
docker compose -f deploy/docker-compose.yml down        # 停容器，保留数据卷
docker compose -f deploy/docker-compose.yml down -v     # 连数据卷一起删
```

**无法 `docker build` 的环境**（如内核 seccomp 拦截 `clone3`）可复用已有镜像跳过构建：

```bash
docker compose -f deploy/docker-compose.yml up -d --no-build
```

前提是 compose 引用的 **3 个自建镜像**都已存在（或从有构建能力的机器 `docker save` / `docker load` 导入）：

```
ragstudio/rag-knowledge-base:latest
ragstudio/web:latest
ragstudio/opensearch:2.19.6-ik      # deploy/opensearch/Dockerfile：官方 2.19.6 + analysis-ik
```

其余外部镜像直接拉取：`pgvector/pgvector:0.8.7-pg16`、`michaelf34/infinity:0.0.77-cpu`（可选）；
（**OpenSearch 基础镜像为 `opensearchproject/opensearch:2.19.6`，Apache-2.0。**）

**本地 embedding 的离线权重预置**（仅 `local-embedding` profile）：`model-gateway` 首次启动会从
HuggingFace 下载 `BAAI/bge-base-zh-v1.5` 到 `model-cache` 卷。目标机器不能访问 HuggingFace 时，
在有网机器下载权重后预置进卷：

```bash
huggingface-cli download BAAI/bge-base-zh-v1.5 --local-dir ./bge-base-zh-v1.5
docker run --rm -v rag-studio_model-cache:/data/hf-cache -v "$PWD":/src \
  alpine sh -c 'mkdir -p /data/hf-cache/hub && cp -r /src/bge-base-zh-v1.5 /data/hf-cache/hub/models--BAAI--bge-base-zh-v1.5'
```

模型权重与镜像均**不入 git 仓库**。

### 4.8 上传大小限制

nginx 已配 `client_max_body_size 650m`，与业务侧按格式的上传上限配套：超大文件返回的是
**业务侧友好 JSON 错误**（`413 payload_too_large` problem+json），而不是 nginx 的 HTML 413。
上限定义在 `file_service.py` 的 `FILE_MAX_SIZE_MAP`：上限查询走 `GET /system/file-size-limits?category=<1|10>`，格式与大小校验走上传前置的 `checkDocTypeAndSize`。

按格式的上限（定义在 `src/knowledge_base/service/file_service.py` 的 `FILE_MAX_SIZE_MAP`）：

| 格式 | 上限 |
|---|---|
| `md` / `docx` | 100 MB |
| `pdf` | 150 MB |
| `txt` | 5 MB |
| `xlsx` / `csv` / `html` | 10 MB |
| `pptx` | 20 MB |

---

## 5. 功能指南

### 5.1 知识库

#### 5.1.1 建库

界面：`/#/knowledge` → 「新建知识库」弹窗（旧整页表单路由已重定向到 `/#/knowledge`）。

后端 `POST /api/co-knowledge/v1/knowledge-bases` 会连带创建：

- `kb_kbase` 行（PostgreSQL）
- 向量表 `kb_index.doc_<kbId>_vector` 与 `..._chunk`
- ES 索引 `doc_<kbId>`
- 根目录 `Default|folder`

建库时按模型注册表登记的 `dimension` 建 `vector(N)` 表，并在写入前**校验实际返回维度**。

#### 5.1.2 目录与文件

目录与文档都嵌套在知识库资源下：

- 目录：`GET/POST /knowledge-bases/{kb_id}/directories`、
  `GET/PATCH/DELETE /knowledge-bases/{kb_id}/directories/{directory_id}`
- 文档：`GET/POST /knowledge-bases/{kb_id}/documents`、
  `DELETE /knowledge-bases/{kb_id}/documents/{document_id}`、
  `GET .../documents/{document_id}/content`（下载原文件）

上传后「文件列表」会显示 `status`（0 初始 / 中间态 / 1 成功 / 2 失败）；
导入是后台异步任务，失败原因在文档行的 `errorMsg` 里。

#### 5.1.3 导入编排

上传时通过 `metadata` 指定解析与切分方式，RKB 随后异步完成
（解析与切分为**进程内调用**，见 §3.1）：

```
RKB（进程内）─▶ ingestion.runtime.file_parse   （解析）
RKB（进程内）─▶ ingestion.runtime.text_split   （切分）
RKB ──HTTP──▶ embedding 端点                       （向量化）
RKB ──▶ PostgreSQL + OpenSearch                    （落库 / 建索引）
```

#### 5.1.4 切片管理

- 全库切片：`GET /knowledge-bases/{kb_id}/chunks`
- 单文档切片：`GET /knowledge-bases/{kb_id}/documents/{document_id}/chunks`
- 手工新增：`POST /knowledge-bases/{kb_id}/chunks`

#### 5.1.5 索引一致性怎么验

**千万不要只看 HTTP 200**——这条链路上静默失败很常见。逐项核对：

| 检查项 | 通过的样子 |
|---|---|
| 切片量 | 切片正文总量 ≈ 原文量（量级 1.0×，明显偏大说明重复切片） |
| 向量表行数 | == chunk 表行数 |
| 向量维度 | == 配置的 `EMBEDDING_DIMENSION` |
| ES 文档数 | == chunk 数 |
| 向量值 | 是真实非零浮点（不是全 0 或 null） |

数据库侧核对示例：

```bash
C="docker compose -f deploy/docker-compose.yml"
$C exec postgresql psql -U rag -d rag_studio -c \
  "SELECT count(*) FROM kb_index.doc_<kbId>_chunk;"
$C exec postgresql psql -U rag -d rag_studio -c \
  "SELECT count(*) FROM kb_index.doc_<kbId>_vector;"
```

#### 5.1.6 删除知识库

删除会连带删向量表 / chunk 表 / ES 索引；`kb_kbase`、目录/文件行都是**物理 DELETE**（见 [`data-deletion-policy.md`](data-deletion-policy.md)）。

### 5.2 知识检索

界面入口是「对话测试」页（检索结果与引用在问答里展示）；脚本与集成方直接调接口：

接口：`POST /api/co-knowledge/v1/retrieval`

```json
{
  "question": "什么是 RAG",
  "type": 0,
  "bases": [ { "baseList": ["doc_<kbId>"], "priority": 0 } ]
}
```

**两条路的语义**：

| `type` | 路径 | 检索后端 |
|---|---|---|
| `0` | 向量路 | PostgreSQL + pgvector 相似度 |
| `1` | 关键词路 | OpenSearch 全文检索 |

**硬性入参约束**（错一个就静默返回空）：

- `bases[].baseList` 必须是 **`doc_<kbId>`** 这种检索侧基名，不是裸 `kbId`，也不是物理表名。
  传裸 id 会拼错表名 → 返回空，且**不报错**。
- `bases[].priority` **必填**。缺失会抛 `groupingBy` 的 null key NPE。

**多库分组优先级**：按 `bases[].priority` 分组，**高优先级先查，命中即返回**（不再查低优先级库）。

**正向与反向断言**（验收时两条都要跑）：

- 正向：查一个确实存在的词 → 返回预期文档 + 合理的 score。
- **反向**：查一个**不存在**的词 → `docs: []`。如果返回了全部文档，说明关键词路是坏的（见 §9.1）。

### 5.3 自定义算子

#### 5.3.1 算子包格式

**扁平结构**（zip 根目录直接放，不要再套一层目录）：

```
<name>.zip
├── config.json      ← 必填，算子元数据
└── <name>.py        ← 必填，入口函数
```

`config.json` 必填字段：`display_name{zh,en}`、`desc{zh,en}`、`module`、`version`、
`supportedFormat`、`is_published`、`visibleRange`。

**命名约束**（最容易失败的地方）：`display_name.en` 去掉空格后必须匹配 `^[A-Za-z0-9_]+$`
且 ≤ 50 字符 —— **连字符、标点都不合法**。`display_name.zh` 须匹配中文名规则。

入口函数契约：

```python
def file_split(file_path: str, **args) -> list:
    """返回 JSON 可序列化的分片列表"""
    return [{"content": "...", "metadata": {"source": "...", "chunk_index": 0, "split_type": "..."}}]
```

`file_path` 由 `ingestion` 模块注入；其余参数来自算子定义里的 `defaultArgs`。

#### 5.3.2 注册与使用

1. 上传：`POST /api/co-knowledge/v1/operator/import`（多部分表单，字段 `file`；入口文件名 `config.json`）。
2. 在导入文档时通过 `splitOperator.<扩展名>.operatorId` 指定（自定义算子用**正 id**）。
3. 算子会经过 `code-check` 安全校验：含 `os.system` 之类危险调用的算子会被拒绝
   （`code=0005`，`Custom operator content validation failed.`）。

#### 5.3.3 沙箱约束

- 沙箱限制（见 `contracts/schemas/operator-exec.json`）：内存 500 MB、结果 ≤ 10 MB、
  **网络隔离尽力而为**。
- 子进程装配（合并时统一）：自定义算子与系统算子两条路径共用 `ingestion/utility/sandbox_runtime.py`；
  上下文由 **spawn 改为 forkserver**（子进程基线小且确定），预载列表**显式不含 `'__main__'`**，
  防止 RKB 的常驻线程在每个沙箱子进程里各起一份（见 §3.1）。
- 网络隔离是**尽力而为**（`unshare(CLONE_NEWNET)`）：无特权时退化为文档级声明。
  **生产环境建议用容器级隔离，不要只依赖它。**
- 算子版本由 `operator.version` 单字段标识；升级前保留上一版本算子文件，便于回退。

### 5.4 检索编排（画布 → 发布 → 执行）

#### 5.4.1 操作路径

```
/#/flow（列表）→ 新建/编辑 → 画布 /#/flow/detail/<appId>
  → 拖节点、连线、配置
  → 「保存」（写草稿）
  → 「发布」（写已发布快照）★ 必须点这一步
```

内置三种建流模板：**顺序检索 / 混合检索 / 条件检索**。绑图谱库时，服务端会自动选择
Blended 的图谱变体（只绑图谱库 → `Blended_graph`；普通库 + 图谱库 →
`Blended_normal_graph`），画布里出现 `KnowledgeGraphRetriever`，发布后即可在对话页使用。

跑起来之后，**对话测试页 `/#/chat`** 是这个运行时的产品内入口：
流式（SSE）问答、`<think>` 段先铺开结束后收起、Markdown 渲染；**左侧历史会话列表**可切换/
删除多段会话（localStorage，按工作流隔离），刷新后恢复并记住上次选择的工作流。
每条回答上方还有**知识库依据**：展示本轮重排后实际提供给模型的片段（来源文件、知识库、
分数、改写后的检索问句），零命中时明确告警；数据来自同一次 `/query`，由请求体
`include_retrieval: true` 打开（默认关闭，老客户端行为不变），流式时是正文之前的
`event: retrieval` 事件。右侧「检索链路与效果」面板还展示本轮**服务端实测**的问题理解/
检索/重排耗时（`evidence.timings`；未启用的阶段显示 `—`），生成回答由客户端从证据帧
到流结束测量；刷新后这些数据仍随会话恢复。契约与边界见 `docs/query-trace-persistence.md`。
每次 `/query` 的指标也 best-effort 写入 `public.chat_query_trace`，并提供
`GET /query-traces`（列表/详情/按时间桶 P50/P95/P99 统计；仅指标，30 天保留），
见 `docs/query-trace-persistence.md`。
**多轮会话**按 `conversation_id` 保持——同一会话追问会接上上一轮的主题，换新会话则从零开始。
前端随请求带 `chat_history`（最近 8 个问答对），改写算子不再只依赖进程内
`last_question`：刷新页面/换浏览器/服务重启后多轮仍然成立（进程内缓存仍是旧客户端的回落路径）。

画布上有这些要素：引擎、节点、连线，以及节点内的算子绑定（注意每份画布有**两份 `variables`**
副本：节点内的与顶层的 —— 前端保存时按节点内的回写顶层，模板作者要保证两份一致）。
下拉类配置包括「知识库下拉」（文档库与图谱库都会列出）与「大模型下拉」。

#### 5.4.2 执行

```bash
curl -s -X POST http://localhost:8080/api/co-knowledge/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"这个知识库里的文档讲了什么？","conversation_id":"demo-1",
       "workflow_id":"RAG_Workflow_xxxx","stream":false}'
```

> ⚠️ 默认 compose **不向宿主发布 8091**（RKB 只在 compose 网络内），
> 但经 `web` 的 8080（宿主映射）走 `/api/co-knowledge/v1/` 即可。要在容器内直打，把
> `localhost:8091/api/co-knowledge/v1/query` 换进上面的 URL。

#### 5.4.3 前置条件与语义

- **必须先配好生成模型端点**（§4.4）。内置 `model-gateway`（Infinity）只提供 embedding，
  `POST /v1/chat/completions` 会 404。
- **编排只读「已发布」快照**。改了画布必须重新发布。
- **`rag-knowledge-base` 建议单副本**：前端已随请求带 `chat_history`，多轮不再强依赖进程内
  缓存；但 `chat_memory` 仍是旧客户端的回落路径，且 SSE 会话状态不宜跨副本（见 §3.3）。
- 未配置 rerank 端点时，含 `ExternalModelReranker` 的工作流会被拒绝；默认工作流用 `LLMReranker` 不受影响。
- `ExternalModelReranker` 节点可在画布上选择具体重排模型（`kwargs.model`，空值 = 跟随部署默认）；
  选中的模型必须在模型注册表里启用，否则发布被拒、运行期报 `rerank-model-not-configured`。

### 5.5 知识图谱

#### 5.5.1 存储模型

- **PostgreSQL** 存实体与边：每个图谱知识库两张表 **`graph_<kbId>_vertex/_edge`**。
- **PostgreSQL** 同时存图谱元数据：`knowledge_graph_info`（记录 `kb_id` → 图基名）、
  `graph_schema`（Schema 定义）、`graph_import_tasks`（导入任务）。

> ⚠️ 这三张表在 `rag_studio` 库；RKB 侧曾有同名副本，现已合并为**一套**，DDL 权威是
> `V6__merge_graph_tables.sql`。

#### 5.5.2 接口族

| 域 | 端点（前缀 `/api/co-knowledge/v1`） |
|---|---|
| 模板 | `GET/POST /graph-schemas`、`GET/PATCH/DELETE /graph-schemas/{id}`、`POST /graph-schemas/import` |
| 建库/导入 | `POST /graph-extractions`、`POST /graph-imports`、`PUT /knowledge-bases/{id}/graph` |
| 实体/边 | `POST /knowledge-bases/{id}/graph/entities|edges`、`PATCH/DELETE .../{entity_id|edge_id}` |
| 查询 | `POST /knowledge-bases/{id}/graph/query` |
| 导出 | `GET /knowledge-bases/{id}/graph/export` |
| 图检索 | `POST /retrieval/graph` |

完整清单见 [`api-reference.md`](api-reference.md)。

#### 5.5.3 Schema 约束（写 Schema 时必看）

- **类型名不能是图 schema 保留字**：`EDGE` / `VERTEX` 等会被 `GraphSchemaValidator` 拒绝
  （避免类型名与保留字冲突）。
- 边的端点必须有 `source_id` / `target_id`；PG 后端把它们落成独立列，导入时强制校验。
- 文档切片的正文在 `content_expand` 字段（**没有 `text` 字段**），chunk 标识是 `id`。

#### 5.5.4 前置条件

- **「文档 → 自动出图」需要生成模型端点**。没有可用的 LLM 时，抽取算子模板与校验链路是完整的，
  但真跑会失败。

---

## 6. 配置参考

所有配置都通过 `deploy/.env` 注入（`cp deploy/.env.example deploy/.env`）。
优先级：**环境变量 > `.env` > 代码内默认值**。

### 6.1 必填项

| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL 口令。**生产务必替换** |

### 6.2 分组一览

**PostgreSQL**

| 变量 | 默认 |
|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | `postgresql` / `5432`（容器初始化） |
| `POSTGRES_DB` / `POSTGRES_USER` | `rag_studio` / `rag`（容器初始化） |
| `RKB_DB_HOST` / `RKB_DB_PORT` / `RKB_DB_NAME` | 由 `POSTGRES_*` 映射；应用只读这一组 |
| `RKB_DB_USER` / `RKB_DB_PASSWORD` | 应用角色（默认 `rag_app`） |
| `RKB_DB_POOL_MIN` / `RKB_DB_POOL_MAX` | `1` / `10` |

**OpenSearch**

| 变量 | 默认 |
|---|---|
| `RKB_ES_HOST` / `RKB_ES_PORT` / `RKB_ES_USERNAME` / `RKB_ES_PASSWORD` | `opensearch` / `9200` / 空 / 空 |

**embedding**

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODEL_GATEWAY_URL` | 占位符，**需自行填写** | embedding 端点基址 |
| `MODEL_GATEWAY_EMBEDDINGS_PATH` | `/v1/embeddings` | 端点路径（远端带 `/v1`，本地 Infinity 不带） |
| `MODEL_GATEWAY_API_KEY` | 空 | 端点需要鉴权时填 |
| `EMBEDDING_MODEL` | `Qwen3-Embedding-0.6B` | **model_code**：发给端点的 `model` 字段 |
| `EMBEDDING_MODEL_NAME` | `Qwen3-Embedding-0.6B` | **model_name**：写进 `kb_kbase.embedding_model`，下拉显示的就是它 |
| `EMBEDDING_DIMENSION` | `1024` | **校验基准**，须与模型实际输出一致 |
| `EMBEDDING_HOST` | 占位符 | 仅用于容器 `NO_PROXY` 排除；改 URL 时要一起改 |

> `EMBEDDING_MODEL` 与 `EMBEDDING_MODEL_NAME` 是**同一模型的两个命名空间，不要合并**。

**生成 / 编排**

| 变量 | 默认 | 说明 |
|---|---|---|
| `GENERATION_GATEWAY_URL` | `http://model-gateway:8000/v1` | OpenAI 兼容端点（**需改**） |
| `GENERATION_MODEL` | `your-chat-model` | 默认生成模型，**必须出现在 `GENERATION_MODELS` 里** |
| `GENERATION_API_KEY` | 空 | **只放 `deploy/.env`，不要提交** |
| `GENERATION_MAX_TOKENS` | `2048`（`.env.example` 给 16384） | 推理模型要给足，否则「看起来成功其实没答案」；必须小于 summarizer 上下文窗口（默认 32768） |
| `GENERATION_TEMPERATURE` / `GENERATION_TIMEOUT` | `0.01` / `120` | — |
| `GENERATION_REASONING_EFFORT` | 空 | 推理模型思考开关。推理模型建议设 `none`：否则重排/改写会把 max_tokens 烧在 reasoning_content 上，20–60s 后抛 `llm-empty-content-truncated` 并静态回落 |
| `GENERATION_RERANK_MODEL` | 空 | 重排专用模型（画布未显式写 `llm` 时生效）。推理模型做重排会先思考很久，建议配非推理模型（实测非推理约 11s，推理模型 21–63s） |
| `GENERATION_MODELS` | — | 模型清单，格式 `名=显示名;名=显示名`。**值必须带引号** |
| `GENERATION_MODELS_PATH` | `/models` | 探测可用模型用；探测失败=无法判定，放行 |
| `REASONING_MODELS` | — | 推理模型清单（逗号分隔）；选中时 preCheck 追加「较慢」警告 |
| `RERANK_URL` | 空 | rerank 端点；**留空时三处一致拒绝**，不静默降级 |
| `GENERATION_HOST` | 空 | 仅用于容器 `NO_PROXY` 排除 |
| `BLACK_LIST_DIR` | `/app/black_list` | 敏感词词表目录。**镜像里没有该目录**；要生效需自己挂载 + 放 `<词表名>.txt`（`\|#\|` 分隔）+ 算子里填 `black_vocabulary`（§3.3） |
| `LOG_DIR` | `/data/rkb/logs`（compose 注入；未设时 RKB 回落 `<work_dir>/logs`、engine 回落 `/tmp/rkb-logs`） | RKB 与编排**共用**的日志目录（只有一个文件 handler）。**不要**指到创建不出来的路径——目录创建失败会让整个 RKB 在 import 期起不来 |

**业务服务寻址与存储**

| 变量 | 默认 |
|---|---|
| `STORAGE_MAIN_PATH` | `/data/kb`（**上传文件卷的挂载点，不要改**；RKB 以 `RKB_KBASE_STORAGE_PATH` 指向同一路径） |

**鉴权**

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTH_MODE` | `local` | `local` = 本地账号 + HttpOnly 会话（推荐）；`none` = 放行所有请求（仅开发/隔离网络）；`gateway` = 仅做「网关令牌存在性」检查（`X-Auth-Value`/`X-Auth-Token`/`Authorization`）。未知取值会让启动失败 |
| `AUTH_DEFAULT_USER` | `admin` | `none`/`gateway` 模式下，未带 `X-Emp-No` 的请求以此身份归属 |
| `RKB_ADMIN_USERNAME` / `RKB_ADMIN_PASSWORD` | `admin` / 空 | 首次启动且账号表为空时创建 admin；密码留空则随机生成 |
| `RKB_ADMIN_PASSWORD_FILE` | `/data/rkb/initial-admin-password` | 生成的初始密码写入位置（0600），首次改密后删除 |
| `RKB_ADMIN_MUST_CHANGE` | `true` | 首次登录是否强制改密（E2E 自动栈设 `false`） |
| `RKB_AUTH_SESSION_TTL_SECONDS` | `43200` | 会话有效期（60s–30d） |
| `RKB_AUTH_COOKIE_SECURE` | `auto` | Cookie 的 `Secure`：auto 按 scheme/`X-Forwarded-Proto`；HTTP 部署不要强制 true |
| `RKB_AUTH_LOGIN_MAX_FAILURES` / `RKB_AUTH_LOGIN_IP_MAX_FAILURES` / `RKB_AUTH_LOGIN_WINDOW_SECONDS` | `5` / `20` / `900` | 登录失败限流（账号+IP / 每 IP / 窗口秒数） |

**RKB 专用**

| 变量 | 默认 | 说明 |
|---|---|---|
| `RKB_FLOW_LLM_MODELS` / `RKB_FLOW_REASONING_MODELS` / `RKB_RERANK_URL` | 由 `GENERATION_MODELS` / `REASONING_MODELS` / `RERANK_URL` 注入 | 与编排侧**必须同源** |

**资源限额与通用**

| 变量 | 默认 |
|---|---|
| `POSTGRES_MEM_LIMIT` / `OPENSEARCH_MEM_LIMIT` | `1g` / `1.5g` |
| `MODEL_GATEWAY_MEM_LIMIT` | `4g` |
| `MEM_LIMIT` | 空（按容器 cgroup 内存上限自动推导） | 文件域上传档位（MB）：< 800 视为小内存 → 文档库单次 **1** 个文件且单文件上限压缩；≥ 800 → 单次 **50** 个、原始大小上限（pdf 150MB 等）。**是档位阈值，不是内存分配** |
| `TZ` | `Asia/Shanghai`（全栈统一） |

> ⚠️ **写在 `.env` 里不等于生效**：只有 compose 显式接了该变量的服务才会收到。
> 改完配置记得 `docker compose up -d --force-recreate <service>`。
> 典型例子：模型清单相关变量必须同时被编排与 RKB 接收，两边不同源会出现
> 「preCheck 说能跑、运行时跑不了」。

Agent 接口的 `RKB_AGENT_*` 变量见 [`agent-integration.md`](agent-integration.md) §2.2。

---

## 7. 接口契约

### 7.1 契约体系

见 §2.5。要点重申：

- `contracts/` 是**唯一来源**，不得私造第二份定义。
- 正式 OpenAPI 有两份：`rkb-api.yaml`（全量 REST，2.3.0）与 `agent-api.yaml`（Agent，1.4.0）。
- `rkb-api.yaml` 由 `tools/verify/generate-rkb-openapi.py` 从运行期路由生成，
  并有快照测试锁定；改动接口后要重新生成。
- 改动契约要同步更新 `contracts/VERSION`。

### 7.2 响应契约（2.0.0 起）

**成功**：没有信封，body 就是资源本身。

- 单资源：对象；
- 分页：`{items, total, page, pageSize}`；
- 非分页集合：数组；
- 创建 `201` + `Location`；异步 `202`；删除 `204`；
- 下载/导出：`application/octet-stream`。

**失败**：真实 HTTP 状态码 + RFC 9457 `application/problem+json`：

```json
{
  "type": "urn:ragstudio:problem:knowledge_base_not_found",
  "title": "Knowledge base not found",
  "status": 404,
  "detail": "知识库不存在",
  "code": "knowledge_base_not_found",
  "instance": "/api/co-knowledge/v1/knowledge-bases/nope"
}
```

`title` 稳定英文；`detail` 按 `Accept-Language` 本地化；客户端按 `code` 分支。
常见状态码：400/401/403/404/409/413/415/422/429/500/502/503。

协议端点（不属于 REST 错误契约）：`/mcp`（MCP 标准语义）、`/health`（纯文本 `ok`）。
`POST /query`、`POST /retrieval/graph` 与 `/agent/*` 都走统一契约：成功体就是
资源对象，错误是真实状态码 + problem+json；`/query` 的流式模式用标准具名 SSE 事件
（`retrieval`/`token`/`done`/`error`）。

健康检查只有 `<prefix>/health` 一条（纯文本 `ok`）。

> ⚠️ 前端 axios 拦截器直接返回 body；失败统一 reject `ApiError {status,code,detail}`。

### 7.3 端点总览

| 项 | 值 |
|---|---|
| 对外前缀 | **`/api/co-knowledge/v1`**（经 nginx；单点定义 `src/shared/prefixes.py`） |
| REST 契约 | `contracts/openapi/rkb-api.yaml`：**65 条路径 / 93 个操作** |
| Agent | REST `/agent/*`（6 条路径，`contracts/openapi/agent-api.yaml`）+ MCP `/mcp` |
| 健康检查 | `GET /api/co-knowledge/v1/health`（纯文本 `ok`） |

按资源分组：

| 分组 | 路径 |
|---|---|
| 系统 | `/health` |
| 知识库 | `/knowledge-bases`、`/knowledge-bases/{id}` |
| 目录 / 文档 / 切片 | `/knowledge-bases/{id}/directories`、`/documents`、`/chunks` |
| 检索 | `/retrieval`、`/retrieval/graph`、`/query`、`/query-traces*` |
| 图谱 | `/graph-schemas`、`/graph-extractions`、`/graph-imports`、`/knowledge-bases/{id}/graph/*` |
| 算子 | `/operators` |
| 工作流 | `/workflows`、`/workflows/{id}/flow`、`/workflows/{id}/publication` |
| 模型 | `/models`、`/models/{id}`、`/system/*-models` |
| Agent | `/agent/*`、`/agent-keys`、`/mcp` |
| 账号 | `/auth/*` |

> 完整请求/响应示例见 [`api-reference.md`](api-reference.md)；
> 机器可读契约见 `contracts/openapi/`。

### 7.4 模型接入契约

见 [`contracts/model-gateway.md`](../contracts/model-gateway.md)。核心是三件事：

1. **契约约束的是请求/响应形状（OpenAI 兼容），不是固定路径**——路径必须可配
   （`MODEL_GATEWAY_EMBEDDINGS_PATH`），换实现只改配置、不改代码。
2. **维度必须显式校验**：返回维度不等于登记维度时**必须显式失败**，不得静默截断或补零。
3. **生成侧的静默失败必须显式抛错**：`content` 为空 + `finish_reason=length` 属于截断，
   不能被当成正常返回（编排会抛 `llm-empty-content-truncated`）。

---

## 8. 排错与 FAQ

### 8.1 「脚本报 ✅ 却其实没通」——这条链路的静默失败清单

这是本项目最容易误判的地方：**HTTP 200、答案有内容，但检索那段其实没生效**。
验收编排链路时，必须同时看三处：

| 看什么 | 通的样子 | 不通的样子 |
|---|---|---|
| 响应体 `answer` | 内容**来自你的文档** | 「我无法访问/没有提供知识库内容」= 走了无上下文兜底 |
| 编排日志（在 rag-knowledge-base 容器内） | 依次出现：改写调用 → 检索 + 非空结果 → 重排调用 → `Most similar base is [...]` 非空 → 合成 | 少检索那行，或 `to node result is []` / `Most similar base is []` |
| 反向用例 | 两条（不存在的工作流 / 空问题）都返回可读的业务错误：HTTP 200 + `{"code":-1,...}`（=「显式失败」，不是空结果；请求体缺字段才是 FastAPI 422） | 任何一条返回空结果或 500 |
| **trace id** | 响应头 `X-Request-Id` 与日志里 `[trace=...]` 一致；一次提问的所有阶段（rewrite / retriever / reranker / synthesizer）都能用同一个 id 串起来 | 日志里是 `[trace=-]`，或响应头缺失 = 没走统一入口 |

### 8.2 高频坑速查表

| 症状 | 原因 |
|---|---|
| 检索**静默返回空** | 算子里的库名必须写成检索侧基名 `doc_<kbId>`。写成物理表名（`doc_<kbId>_vector`）也会查不到 |
| 检索命中为空但库里确实有数据 | 算子的 `kwargs.embedding` 没填或填错，后端用了默认模型 |
| 答案正常但没走检索 | 重排把 token 预算烧光（推理模型）→ 重排异常 → 空节点 → 兜底回答。把 `GENERATION_MAX_TOKENS` 给足 |
| `/query` 一直卡住 | 容器 `no_proxy` 没排除生成端点 → 请求被宿主代理接走 |
| 画布下拉里没有知识库 | `RKB_FLOW_KBASE_OPTIONS_URL` 被设成了非空（应留空，见 §8.6）；或库本身没有 `tableName`（会被跳过并记日志） |
| 页面点不动 / 接口全 404 | 前端是 **hash 路由**，地址应是 `/#/knowledge` 而不是 `/knowledge` |
| 接口报 `Tunnel connection failed: 302 Moved` | `NO_PROXY` 没排除该域名，请求被代理接走。**看响应体的内容类型，别只看状态码**（代理对不存在的主机名回 302，跟过去是一页「DNS 解析失败」的 HTML） |
| 关键词检索查什么都能命中（误报） | 分词器问题，见 §9.1 |
| 向量检索恒定返回空 | 维度冲突（768 维库 vs 当前 1024），见 §9.2 |
| 上传后导入永久失败（`code=0005`） | `splitOperator.args` 没给全三个字段，见 §4.5 |
| 建了库但在列表里看不到 | 建库时 `category` 不在列表筛选范围内（文档库 1 / 图谱库 10） |
| `content` 为空但 `finish_reason=length` | 推理模型 token 预算不足，见 §4.4 |

### 8.3 代理配置（`NO_PROXY`）

若宿主配置了 HTTP 代理，容器会继承 `http_proxy`。**每个服务一份、按各自出站目标定制**
（不是一份通用列表）：

- 内部服务名 + Docker 网段（默认 `172.18.0.0/16`，按实际网段调整）
- embedding 端点主机（`EMBEDDING_HOST` 自动追加）
- 生成端点主机（`GENERATION_HOST` 自动追加）

**`NO_PROXY` 和 `no_proxy` 都写上**：Python 两者都认，同时存在时**小写优先**——写两份是为了不依赖这个优先级。

### 8.4 日志在哪

| 组件 | 位置 |
|---|---|
| 容器化服务（`rag-knowledge-base` / `web` / 各基础设施容器） | `docker compose logs <service>`（应用日志默认不写 stdout，见下） |
| **RKB（含编排）** | 容器内 `LOG_DIR`（默认 `/data/rkb/logs`，持久卷）。RKB 与编排**共用同一个文件 handler**：`rag-knowledge-base-<时间>-<随机>.log`，不会出现两份内容重复的日志 |

```bash
docker exec rag-studio-rag-knowledge-base-1 sh -c 'ls -t /data/rkb/logs/rag-knowledge-base-*.log | head -1'
docker exec rag-studio-rag-knowledge-base-1 sh -c 'grep "trace=<你的 X-Request-Id>" /data/rkb/logs/rag-knowledge-base-*.log'
```

每行都带 `[trace=...]`（由 `tool/log/trace.py` 的 contextvar 注入）。关键阶段各有固定前缀，
可以直接按前缀切分一次提问的耗时账单：

| 前缀 | 含义 |
|---|---|
| `[query] entry/engine/streaming/answered/stream finished` | 请求入口、引擎选择、流式结束、答案长度与总耗时 |
| `[retriever][vector]/[keyword]/[graph]` | 每条检索路的库名、命中数、图谱 seeds/entities/edges、耗时 |
| `[reranker] start/batch/done` | 重排的批次数、每批选中数、耗时（卡住时先看这里） |
| `[synthesizer] start/done/per-kb config` | 合成节点数、prompt 体量（不再打印完整 prompt）、耗时 |
| `[graph-retrieve][gateway]` | 图检索网关的开始/结束/失败与耗时 |

所有 HTTP 端点都由最外层的 `RequestIdMiddleware` 分配请求 ID：客户端传合法
`X-Request-Id`（`[A-Za-z0-9._-]`、1–64 字符）就沿用并同名回显；缺失或不合法则丢弃、
由服务端生成 16 位十六进制 ID。鉴权 401、限流 429、404/422 等不经过业务 handler
的响应同样带这个头。

### 8.5 环境自检清单

```bash
C="docker compose -f deploy/docker-compose.yml"

$C ps                                    # 默认启动的容器应全 healthy
$C exec rag-knowledge-base env | grep -i no_proxy   # 含内部服务名 + 模型端点主机
$C exec postgresql psql -U rag -d rag_studio -c '\dt iaab_kbase.*' | head
$C exec opensearch curl -fs http://localhost:9200/_cluster/health
$C exec postgresql psql -U rag -Atc "select datname from pg_database where datistemplate=false"  # 只应输出 rag_studio + postgres
```

### 8.6 FAQ

**Q：我只想看知识库和检索，需要起全部容器吗？**
至少需要 `web` + `rag-knowledge-base` + `postgresql` + `opensearch`
（文档解析与切分是后端进程内调用，见 §3.1；画布编排与检索编排运行时也在后端内）。
图谱能力已在 RKB 内，无独立图数据库容器。

**Q：能用外部 PostgreSQL / OpenSearch 吗？**
可以，改 `.env` 里的 `POSTGRES_HOST` / `RKB_ES_HOST` 等指向外部实例。
注意 §2.4 的数据归属约束仍然适用。

**Q：向量维度能改吗？**
能。改 `EMBEDDING_DIMENSION` 与对应模型，但**已建的知识库不会自动重建向量**——
不同维度的向量表不能混用。新库新维度；768 维库要么保留原模型端点，要么重建索引。

**Q：为什么建库后「文档知识库」Tab 里是 0 条？**
列表按 `category` 过滤（1=文档库 / 10=图谱库）。通过接口建库时如果 `category` 放错
（例如图谱库漏传 `10`），该库会出现在另一个 Tab 里，看起来像「静默消失」。

**Q：画布「知识库下拉」没数据？**
先确认 `RKB_FLOW_KBASE_OPTIONS_URL` **没有被设成非空值**：留空（默认）时直读
`rag_studio.kb_kbase`，文档库与图谱库都会列出；设了值会改走 HTTP 透传路径，
该路径没有对应服务，表现就是下拉「无数据」或保存前报服务器错误（§6.2）。
另外，下拉项用的是 `tableName`（检索侧基名 `doc_<uuid>`），
没有 `tableName` 的库会被跳过并记日志——不会给出「看起来能选、选了检索不到」的选项。

**Q：上传后状态「处理失败」，`errorMsg=插入或更新数据库异常`？**
该库绑定的 embedding 模型在远端网关不存在：网关对未知模型名回 404，失败被回滚步骤记成这条
误导性文案。用已注册的 `Qwen3-Embedding-0.6B` 建库，或启用 `local-embedding` profile 并把
`MODEL_GATEWAY_URL` 指回本地容器。下拉数据源是模型注册表（`/system/embedding-models`
只返回 `enabled` 的行）。

---

## 9. 运行前提与容量建议

以下配置决定部署后的行为与容量，按实际环境设置。

### 9.1 关键词检索与中文分词

默认部署使用 `ragstudio/opensearch:2.19.6-ik`（官方 OpenSearch 2.19.6 + `analysis-ik`），
索引 `text` 字段用 `ik_smart` 分词，检索查询也用 `ik_smart`。RKB 启动后通过
`_cat/plugins` 探测插件：探测到就按 IK 建索引/查询，探测不到则回落到
`minimumShouldMatch("100%")`（逐字全匹配）——回退分支用于未安装 IK 插件的部署。

已有索引需要重建 mapping 才会用上 IK（OpenSearch 不能原地改字段 analyzer）。
重建走评测工具里的脚本（从 PG 重建并校验逐文档内容）：

```bash
python3 tools/rag-metrics/reindex_es.py --kb-id <kbId> --apply
```

无 IK 时 standard 分词会把中文切成单字，`minimumShouldMatch("100%")` 等价于
逐字全匹配；长自然语言查询建议部署时安装 IK。

### 9.2 embedding 维度按知识库固定

每个知识库的向量维度由建库时的 embedding 模型决定，同一库内不要混用不同维度的模型。
用 1024 维模型去查一个 768 维的库时，底层会抛
`different vector dimensions 768 and 1024`，检索层会返回空结果。

**判别法：关键词路有结果、向量路恒定为空 = 维度不匹配。**

### 9.3 编排运行时

- **单副本部署**：`rag-knowledge-base` 使用进程内多轮缓存，按单副本规划容量。
- **发布后执行**：编排运行时读取已发布快照；画布修改需要发布后才会生效。
- **SSE**：`/api/co-knowledge/v1/query` 依赖 nginx 的专项 location 配置（§3.4）；
  改对外路由时保留三条流式指令，否则流式会退化为「卡住不动、然后一次性全出来」。
- **生成端点**：问答、改写、合成使用模型注册表中的生成端点。
- **重排端点**：在模型注册表或 `RERANK_URL` 中配置；未配置时重排算子会返回明确错误，
  不会静默跳过。
- 默认工作流的重排用 `LLMReranker`（复用生成模型），其提示词要求模型返回
  `{"ranking":[{"document_id":N,"relevance_score":S}]}` 格式。

### 9.4 模型管理

**运行时注册/纳管**：页面上（`#/models`）注册 OpenAI 兼容端点，保存即生效，
不需要改配置或重启。清单的权威来源是 `model_registry` 表，`deploy/.env`
负责首次播种与回落。

- 三类：**LLM / Embedding / Reranker**，四个路径（chat / embeddings / models / rerank）
  可在每个端点上单独覆盖（不同实现的路径确实不同，见 §4.4）。
- 每个 LLM 可单独设置「思考配置」（`thinkingMode`）：`auto` 按模型名 + 端点自动
  匹配内置预置（DeepSeek / Qwen3 / GLM / Kimi / MiniMax / GPT / Gemini / 豆包 /
  混元 / 星火等），`preset` 选具体写法，`custom` 写自定义 JSON，`none` 不发送。
  **该配置只用于回答生成**；改写、重排、路由等辅助调用只按目录自动使用关闭/最低
  思考的预置，不读取模型行的 preset/custom。保存即生效、只影响该模型。
  部署级 `GENERATION_REASONING_EFFORT` / `GENERATION_CHAT_TEMPLATE_KWARGS`
  作为注册表不可用/模型未注册时的回落。
- 模型注册表按实例共享；需要按租户隔离模型可见性时，按实例部署或在网关层分权。
- API Key 在库中静态加密（AES-256-GCM），接口只返回掩码，详见
  [`security-hardening.md`](security-hardening.md)。
- 模型清单与动态纳管的完整口径见 `contracts/model-gateway.md`。

### 9.5 数据与存储

- **单库**：全栈只有一个 PostgreSQL 业务库 `rag_studio`，不做跨库 JOIN。
- **PostgreSQL 与 OpenSearch 均由 `rag-knowledge-base` 单进程读写**；容量规划按
  单实例的连接数、内存与索引规模估算。

### 9.6 部署与安全建议

- **契约漂移由快照测试兜底**：`contracts/openapi/rkb-api.yaml` 与运行期路由的一致性由
  `backend/tests/test_rkb_openapi_snapshot.py` 锁定（见 §7.1）。
- **CI 覆盖**：前端 vitest、后端 pytest（skip==0 断言）与 `ruff check src`；
  本地入口 `tools/run-tests.sh`。
- **沙箱隔离**：生产环境建议叠加容器级隔离，限制算子沙箱的网络与文件系统访问。
- **算子版本**：算子模板随发布包版本化；升级前保留上一版本的算子文件，便于回退。
- **敏感词词表**：变更词表后重启容器，或显式调用一次 `reload_black_list()`（§3.3）。
- **老内核兼容**：内核 < 5.3 时 compose 使用 `seccomp=unconfined` 兼容 `clone3`；
  现代内核可移除该项（§4.1）。
- **容量起点**：默认 4 个容器（web / RKB / PostgreSQL / OpenSearch），单 RKB 副本；
  增大语料或并发时优先扩容 PostgreSQL 内存与 OpenSearch 节点，再按实例横向扩展。

---

## 10. 二次开发

### 10.1 代码地图

| 目录 | 技术 | 改动落点 |
|---|---|---|
| `backend/src/ingestion/` | Python（进程内模块，无独立 Web 框架） | 进程内入口 → `ingestion/runtime.py`；解析/切分 → `src/parsing/` + `ingestion/split/`；沙箱 → `utility/self_operator.py` + `utility/sandbox_runtime.py`；系统算子注册表 → `split/operator_all.json` |
| `backend` | Python / FastAPI | 画布编排接口 → `src/workflow/`；知识库域接口 → `src/knowledge_base/`；图谱 → `src/graph/`；应用装配 → `src/app.py`；检索编排运行时 → `src/engine/`；**Agent 接口 → `src/agent/`** |
| `backend/src/engine/` | Python / FastAPI | 运行时 → `primitives/`；画布→运行时翻译 → `translator.py` |
| `backend/src/agent/` | Python / FastAPI + MCP | REST 子应用 → `rest.py`；MCP → `mcp_server.py`；鉴权/限流 → `auth.py`；Key 表 → `schema.py` + `repository_pg.py`；严格检索 → `store_retrieval.py` + `search.py`；问答 → `answer.py`；Key CLI → `cli.py` |
| `frontend` | Vue 3 | 路由 → `frontend/src/app/router.js`；页面 → `frontend/src/pages/`；领域实现 → `frontend/src/features/`；共享层 → `frontend/src/shared/`；应用壳 → `frontend/src/app/` |
| `contracts` | OpenAPI / JSON Schema | 接口契约唯一来源 |
| `deploy` | docker-compose | 部署入口与 `.env` 模板 |
| `tools/verify`、`tools/run-tests.sh` | Node / Python / Bash 脚本 | 验收脚本与单测一键入口（**不是服务**）；剧本见 `tools/verify/README.md` |
| `docs/` | Markdown | 架构、接口、部署与开发约定：先读 `docs/ARCHITECTURE.md` |

### 10.2 关键约定（改代码前必读）

1. **契约唯一来源**：`contracts/` 是唯一来源，不得私造第二份定义。改契约要更新 `contracts/VERSION`。
2. **每张表只有一个写入方**（§2.4）。跨服务读写同一批表是明确禁止的——那 3 张同名表的教训。
3. **共享卷路径不能改**：`kb-storage` 的挂载点是既有绝对路径（`diskFileKey`）的基准
   （默认 `/data/kb`，RKB 以 `RKB_KBASE_STORAGE_PATH` 对齐）。选 MinIO 后端时持久文件
   走对象键，但算子包路径、名称锁与 scratch 仍依赖这个卷，**不能因此卸载它**。
4. **响应契约不能随手改**：前端拦截器直接消费纯 JSON，错误依赖 problem `code`（§7.2）。
5. **画布有两份 `variables`**：节点内的与顶层的。前端保存时按节点内的回写顶层，
   只改一份会被「打开画布再保存」静默冲掉。改模板或播种逻辑时两份都要保证一致。
6. **边按画布 DAG 生成**，不是串成一条链（条件检索靠它分路）。孤立节点、主链编号都是排查点。
7. **先看结构约定，再动手**：`docs/ARCHITECTURE.md` §7 登记了分层约定、
   大文件拆分顺序与重复逻辑处理原则。改 `frontend/src` 或编排底层代码前先读一遍。
8. **改完必须让测试绿**：至少跑 `bash tools/run-tests.sh`；新写的测试要做一次**变异验证**
   （改坏源码 → 对应用例变红 → 还原），否则无法证明它不是装饰。

### 10.3 本地构建

```bash
# Python 服务（唯一的后端；锁定依赖）
cd backend && pip install -r requirements.lock
python -m pytest -q                                                  # 2,417 条单测（宿主缺重依赖时用容器跑，见 §10.4）

# 前端
cd frontend && npm ci
npm run build                # 根路径部署（.env.production: BASE_URL=/）
npm run test:unit            # vitest：936 条 / 91 个文件（Node ≥ 22）
```

单测一键入口是 `bash tools/run-tests.sh`（前后端全跑，见 §10.4），
不要只跑自己改的那一边。

镜像构建入口是 `backend/Dockerfile` 与 `frontend/Dockerfile`；后者是两段式（node 构建 → nginx 运行）。

### 10.4 测试

**一键跑**：`bash tools/run-tests.sh`（默认前后端全跑；`--frontend` / `--backend` 只跑一边）。
退出码三值：0 全绿 / 1 有用例失败（含后端 skip > 0）/ 2 环境或用法错误。

| 测试范围 | 位置 | 命令 | 当前基线 |
|---|---|---|---|
| `rag-knowledge-base` + 编排 | `backend/tests/`（含 `tests/engine/`） | 容器内 `python -m pytest -q`（范围由 `pytest.ini` 的 `testpaths` 决定） | **2,417 passed / 7 deselected**（deselect 的是需基线库的差分用例，**skip 必须为 0**） |
| `frontend`（compose 服务名 `web`） | `frontend/tests/`（91 个 spec 参与运行） | `cd frontend && npm run test:unit`（vitest） | **936 passed** |
| `ingestion`（RKB 内模块） | `src/ingestion/tests/`（`test_split.py`、`test_sandbox.py`） | 独立入口（要容器与重依赖，**有意不进** `pytest.ini` 的 `testpaths`） | 与上表两者独立 |

三个硬约束（`tools/run-tests.sh` 与 CI 里都做成了断言，**不要绕开**）：

- 后端测试跑在容器里且**必须挂仓库根**——跨服务用例要读其它服务的文件，
  只挂服务目录会**静默 skip**（找不到 = skip 而不是 fail）；
- **skip 数必须为 0**：静默少跑按失败处理；
- 宿主内核 4.19 无 `clone3`，`docker run` 必须 `--security-opt seccomp=unconfined`，
  否则 pytest 零输出静默死（症状是「什么都没发生」）。

CI（`.github/workflows/ci.yml`）三个 job：前端 vitest（**Node 22，不能用 20**：vitest 5 要求
`^22.12`、jsdom 30 要求 `^22.22.2`；Node 20 下 11 个 jsdom 组件用例起不来）、
后端 pytest（Python 3.11，同样断言 skip==0）、`lint-backend`（`ruff check src`，
锁 `ruff==0.17.0`，**只 check 不 `--fix`**）。

### 10.5 端到端验收脚本

`tools/verify/` 下有可重复执行的验收脚本（用法见该目录的 `README.md`）：

| 脚本 | 层级 | 验什么 |
|---|---|---|
| `verify-orchestration.py` | 接口层 | 建流 → 存画布 → 发布 → `/query` + 反向用例 |
| `verify-workflow-templates.py` | 模板层 | 三种建流模板各走一遍完整流程（含画布体检与模拟保存） |
| `verify-multi-turn.py` | 多轮 | **成对跑**：同会话追问接上主题 + 新会话答非所问（对照组） |
| `verify-startup-lifecycle.py` | 生命周期 | `import app` 不起后台线程、运行态 lifespan 已执行（当前已无常驻线程） |
| `verify-graph-extract-e2e.py` | 图谱抽取 | L1~L4 断言 + 否决层 + 分阶段耗时账单（容器内，≈6s） |
浏览器层由 `e2e/` 的 Playwright 用例覆盖（见 `e2e/README.md`）。
脚本的完整用法、前置条件与踩坑清单都写在 `tools/verify/README.md`，**跑之前先读它**。

依赖：`.py` 接口层脚本只依赖 Python 标准库（`verify-graph-extract-e2e.py` 要在**容器内**跑）。
**验收时请配合 §8.1 的三处判据一起看**——脚本报 ✅ 不等于链路真的通。

### 10.6 验收手册

分层入口、通用判据、边界夹具与回归闭环见
[`docs/acceptance-handbook.md`](acceptance-handbook.md)。**测试与验收按该手册执行**：
每条问题必须落成回归用例，判定为非缺陷的也要写明理由。

---

## 附：许可

[Apache License 2.0](../LICENSE)。

第三方组件与许可声明见 [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md)。
