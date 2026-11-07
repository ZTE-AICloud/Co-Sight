<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/zte-logo-white.svg">
    <img src="frontend/public/brand/zte-logo.svg" width="160" height="95" alt="ZTE">
  </picture>
  <h1>Knowledge Studio</h1>
  <p><b>开源知识工程平台</b><br>把私有知识变成可检索、可编排、可追溯的 AI 资产</p>
</div>

<p align="center">
  <b>简体中文</b> · <a href="README.en.md">English</a>
</p>

<p align="center">
  <code>Apache-2.0</code> · <code>默认 4 容器</code> · <code>单一 API 前缀</code> · <code>模型端点可插拔</code> · <code>中 / 英双语</code>
</p>

> Knowledge Studio 是产品 / 界面名；组件名 Co-Knowledge；仓库名为 Co-Knowledge，镜像与包名沿用 `ragstudio` 前缀。

Knowledge Studio 是一个可私有化部署的 **知识工程平台**：文档进来，经过解析、切片、向量与全文双索引，变成可检索的知识；关系型知识由大模型按 Schema 或通用模式抽取成实体与关系，存进知识图谱，并可与文档检索混合成 **GraphRAG** 链路；检索流程可以在画布上自由编排，发布后按 DAG 执行；问答以 SSE 流式返回，并逐条给出知识库依据。

一条 Compose 起全栈：**1 个前端 + 1 个后端 + 2 个存储**，对外只有 **一个 API 前缀**。embedding / 生成 / 重排全部接你自己的 OpenAI 兼容端点，数据、模型与算力都留在自己的环境里。

---

## 它解决什么问题

| 企业里的真问题 | Knowledge Studio 的做法 |
|---|---|
| **答案不可溯源** —— 模型会一本正经地编 | 回答直接列出本轮提供给模型的片段、来源文件、分数与改写后的检索问句；Agent 问答返回 `[S1]` 引用，可逐条核对 |
| **关系型问题答不了** —— 关键词和向量都不行 | 图谱库：Schema 定义或通用抽取 → 实体/关系抽取 → 图谱查询与图谱检索；可在同一条编排链路里与文档检索并用 |
| **自建成本高** —— 解析、切片、向量、全文、图库、编排、模型接入，缺一不可 | 一条 Compose 起 4 个容器；只用 PostgreSQL 与 OpenSearch 两个通用存储 |

---

## 核心能力

| 能力 | 说明 |
|---|---|
| **知识库管理** | 文档知识库 / 图谱知识库两类；目录树、批量导入、文档状态与统计、切片查看与手工新增；每库独立的向量表与全文索引 |
| **文档解析与切片** | md / docx / xlsx / pdf / pptx / html / txt / csv；默认按 512 字符切片、128 字符重叠；切片同时写入向量与全文 |
| **自定义算子** | 上传 zip → 注册 → 导入时指定；支持 `file_parse` / `text_split` / `graph_extract` 三类入口（ABI v2），提供模板下载、发布/可见性与导出；子进程隔离执行（500MB 内存 / 10MB 结果 / 网络隔离尽力而为），上传前做 AST 静态安全检查；算子导入仅管理员，算子按可信代码对待 |
| **双路检索** | 向量检索（`type=0`）与关键词检索（`type=1`，OpenSearch + analysis-ik）；多库分组与优先级，高优先级库命中即返回 |
| **知识图谱** | Schema（本体）定义与模板设计器、LLM 抽取、PostgreSQL JSONB 存储（`graph_<kbId>_vertex/_edge`）、实体/关系编辑、图谱查询 / 导出 / 可视化 / 图谱向量检索；内置**通用**（`-6` v1.2.0，不依赖 Schema，`extractionProfile` 支持 `general` / `general_attributes`）与**专业**（`-5` v1.0.0，按 Schema 抽取）两个算子 |
| **检索编排** | @antv/x6 画布；顺序 / 混合 / 条件三类内置模板（含图谱变体）；草稿与发布快照分离，运行时只读已发布版本；图谱检索节点可配置 `depth` / `top_k` / `include_edge_facts` |
| **对话测试** | SSE 流式输出、多轮会话、知识库依据、阶段耗时；查询指标可落 `chat_query_trace`，并提供列表与 P50/P95/P99 统计 |
| **模型管理** | LLM / Embedding / Reranker 三类模型的注册、连通性测试与启停；保存即生效；思考配置内置 17 组预置并支持自定义 JSON |
| **Agent 接入** | REST 6 条路径 + MCP 5 个工具；API Key 作用域、知识库白名单、每 Key 限流与调用量统计 |
| **账号与鉴权** | `local` 本地账号（scrypt + HttpOnly 会话）/ `gateway` 网关令牌 / `none` 关闭鉴权 |

### 几个关键设计

- **双索引一致性**：切片同时落 pgvector 与 OpenSearch，可用「向量数 == 切片数 == 全文文档数」核对。
- **草稿 / 发布分离**：画布改了必须重新「发布」才生效；运行时只执行已发布快照。
- **检索可观测**：命中片段、来源文件、相关度分数、改写问句与各阶段耗时都在同一次请求里返回。
- **扩展点独立于内核**：自定义格式或切分策略 → 传一个算子包；模型换代 → 在模型管理页换端点；检索策略要变 → 改画布。

---

## 架构

```text
        Browser / business systems / Agents (REST · MCP)
                             │  HTTP · SSE
                     ┌───────▼────────┐
                     │  web (nginx)   │  sole public entry :80
                     └───────┬────────┘
                             │  /api/co-knowledge/v1
        ┌────────────────────▼───────────────────┐
        │  rag-knowledge-base                    │  sole backend (FastAPI :8091)
        │  knowledge base · graph · operators    │
        │  retrieval · engine · chat · models    │
        │  agent · auth                          │
        └──────────┬─────────────────────┬───────┘
                   │                     │
     ┌─────────────▼────────┐  ┌─────────▼──────────────┐
     │  PostgreSQL 16       │  │  OpenSearch 2.19.6     │
     │  + pgvector 0.8.7    │  │  + analysis-ik         │
     │  vectors / metadata  │  │  full-text / keyword   │
     │  graph JSONB         │  └────────────────────────┘
     └──────────────────────┘
     Outside the stack: OpenAI-compatible endpoints (embedding / chat / rerank)
```

图中左侧存储负责向量、业务元数据与图谱，右侧存储负责全文与关键词索引。

默认启动 **4 个容器**：

| 容器 | 作用 | 宿主端口 |
|---|---|---|
| `web` | nginx 静态资源 + 反向代理（唯一对外入口） | **80** |
| `rag-knowledge-base` | 唯一后端：知识库 / 图谱 / 算子 / 检索 / 编排 / 问答 / 模型 / Agent | 仅容器网络 |
| `postgresql` | 业务表、向量表（pgvector 0.8.7）与图谱表（JSONB） | `127.0.0.1:5432` |
| `opensearch` | 全文与关键词索引（OpenSearch 2.19.6 + analysis-ik） | `127.0.0.1:9200` |

另有 **两个可选 profile**，按需启动：

- `local-embedding`：本地 Infinity 0.0.77 容器，提供 768 维 embedding（`bge-base-zh-v1.5`）；
- `minio`：把持久文件放到 MinIO（RELEASE.2024-10-13）对象存储，否则使用本地命名卷。

### 技术栈与组件依赖

| 层 | 组件与版本 |
|---|---|
| 前端运行时 | Vue 3.5.26 · Element Plus 2.14.7 · Vue Router 4.6.4 · Vuex 4.1.0 |
| 画布与可视化 | @antv/x6 2.19.2 · vis-network 9.1.13 |
| 前端构建 / 测试 | Node 22.23.3 · @vue/cli-service 5.0.9 · Vitest 5.0.4 |
| 后端运行时 | Python 3.11.18 · FastAPI 0.111.0 · Uvicorn 0.27.0 · Pydantic 2.9.2 · psycopg2-binary 2.9.9 · MCP SDK 1.12.4 |
| 文档解析 | pdfplumber 0.11.7 · pypdfium2 5.14.0 · python-docx 1.1.2 · python-pptx 1.0.2 · openpyxl 3.1.5 |
| 存储 | PostgreSQL 16 + pgvector 0.8.7 · OpenSearch 2.19.6 + analysis-ik |
| 入口与部署 | nginx 1.27.5 · Docker Compose v2 |

> 版本以 [`backend/requirements.txt`](backend/requirements.txt)、[`frontend/package.json`](frontend/package.json) 与 [`deploy/docker-compose.yml`](deploy/docker-compose.yml) 为准；本表只列直接影响部署与集成的组件。

### 后端模块

```text
backend/src/
├── knowledge_base/  知识库、目录、文档、切片、任务队列
├── ingestion/       解析 / 切分 / 抽图管线
├── parsing/         纯格式解析库
├── operators/       算子注册、模板、沙箱、系统算子
├── operator_api/    算子 ABI v2 的公开导入面
├── graph/           Schema、抽取、导入、查询、导出、图谱检索
├── retrieval/       向量与关键词读取、节点映射
├── workflow/        画布、校验、发布、模板
├── engine/          RAG 运行时（改写 → 检索 → 重排 → 合成）
├── chat/            /query、SSE、多轮会话、证据、查询轨迹
├── model/           模型注册表、网关客户端、思考配置
├── agent/           REST / MCP / API Key
├── auth/            本地账号、会话与 CLI
├── infrastructure/  配置、数据库、HTTP、日志、存储、搜索等平台层
├── shared/          前缀、Problem、错误、切片模型、i18n
└── system/          健康检查与系统信息
```

前端按 `app / pages / features / shared` 分层，feature 目录与后端领域同名。完整结构、依赖规则与修改约定见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 快速开始

### 前置条件

- Docker ≥ 24 + `docker compose` v2（构建本地镜像需要 buildx ≥ 0.17；低于该版本请用 `docker build` 手动构建后 `up -d --no-build`）
- 磁盘 ≥ 20GB，内存建议 ≥ 6GiB
- 一个可达的 **OpenAI 兼容 embedding 端点**；问答另需生成端点（重排可选）
- 80 端口可用；OpenSearch 需要宿主参数：

```bash
sudo sysctl -w vm.max_map_count=262144
# 持久化：echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf
```

### 四步起栈

**1. 配置环境**

```bash
cp deploy/.env.example deploy/.env
# 至少修改数据库口令：
#   POSTGRES_PASSWORD / RKB_DB_PASSWORD
# 模型端点也可在启动后到「模型管理」注册；先填在这里则作为首次播种：
#   MODEL_GATEWAY_URL / MODEL_GATEWAY_API_KEY / EMBEDDING_MODEL / EMBEDDING_DIMENSION
# 使用 Agent REST / MCP 还需设置：
#   RKB_AGENT_KEY_PEPPER（openssl rand -hex 32）
```

`.env` 必须放在 `deploy/`（与 compose 文件同目录），compose 才会自动读取。

> **内网 / 镜像站**：构建期默认访问官方 PyPI 与 npm registry。把镜像地址填进
> `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` / `NPM_REGISTRY` 即可（留空 = 官方源），
> 这些值会作为 build ARG 传给后端与前端镜像。OpenSearch 的 IK 插件**离线安装**：
> 插件包随仓库分发（`deploy/opensearch/analysis-ik.zip`，上游
> [analysis-ik releases](https://github.com/medcl/elasticsearch-analysis-ik/releases)，
> 版本须与 `OPENSEARCH_VERSION` 一致）。完全离线时先在有网环境构建镜像，再按
> 「部署注意」里的 `--no-build` 拉起。

**2. 一键启动**

```bash
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps    # 默认 4 个容器均应为 healthy
```

**3. 验证健康**

```bash
curl -fs http://localhost/api/co-knowledge/v1/health   # → ok
```

**4. 登录并注册模型**

打开 `http://localhost`。默认 `AUTH_MODE=local`，首次启动会创建管理员 `admin`，随机密码写入容器内文件：

```bash
docker compose -f deploy/docker-compose.yml exec rag-knowledge-base \
  cat /data/rkb/initial-admin-password
```

首次登录会强制改密。进入「模型管理」注册 embedding / 生成 / 重排端点，**保存即生效**。模型注册表是清单的权威来源，`deploy/.env` 只负责首次播种与回落。

然后即可：**建知识库 → 导入文档 → 检索 / 画布编排 / 图谱抽取**。

> 离线环境：镜像就绪后加 `--no-build` 直接拉起；开发态叠加 `deploy/docker-compose.dev.yml`（源码挂载 + 热重载，复用现有服务）。

---

## 使用方式

### 界面

| 入口 | 路径 | 用途 |
|---|---|---|
| 知识库 → 文档知识库 | `/#/knowledge`；详情 `/#/knowledge/detail/:id`；文档 `/#/knowledge/detail/:id/documents` | 列表、数据集/基本信息、目录与文档管理 |
| 知识库 → 图谱知识库 | `/#/graph`；详情 `/#/graph/detail/:id`、编辑 `/#/graph/edit/:id`、新建 `/#/graph/create`、模板 `/#/graph/createTemplate/:templateId` | 列表、详情、编辑、建库与模板设计器 |
| 知识检索 | `/#/flow`；画布 `/#/flow/detail/:id` | 知识检索列表、画布编排、保存与发布 |
| 对话测试 | `/#/chat` | 流式问答、多轮会话、知识库依据与阶段耗时 |
| 自定义算子 | `/#/operators` | 上传、模板下载、发布/可见性与导出 |
| 模型管理 | `/#/models` | LLM / Embedding / Reranker 注册、连接测试与思考配置 |
| 远程接入 → 接入方法 | `/#/access` | Agent REST + MCP 接入说明 |
| 远程接入 → 密钥管理 | `/#/keys` | Agent API Key、作用域、白名单与限流 |
| 登录 / 改密 | `/#/login`、`/#/change-password` | 本地账号登录与强制改密 |

> 前端使用 **hash 路由**：页面地址形如 `/#/knowledge`。`/` 重定向到 `/#/login`，未知地址兜底到 `/#/knowledge`。

### HTTP API + SSE

- **只有一个前缀**：`/api/co-knowledge/v1`。
- 主 REST 契约 **OpenAPI 2.3.0**：**65 条路径 / 93 个操作**（含 `/health`），文件 [`contracts/openapi/rkb-api.yaml`](contracts/openapi/rkb-api.yaml)。
- Agent REST 契约 **OpenAPI 1.4.0**：**6 条路径 / 6 个操作**，文件 [`contracts/openapi/agent-api.yaml`](contracts/openapi/agent-api.yaml)。
- 成功响应直接返回资源本身；分页为 `{items,total,page,pageSize}`；错误为 RFC 9457 `application/problem+json`。
- 问答 `POST /query` 使用标准 SSE 具名事件，经 nginx 单独关闭缓冲。

```bash
BASE=http://localhost/api/co-knowledge/v1
curl -fs $BASE/health
```

完整接口见 [`docs/api-reference.md`](docs/api-reference.md)；管理面之外的集成文档见 [`docs/external-api/`](docs/external-api/)。

### Agent REST + MCP

给智能体平台 / IDE 的知识访问、检索问答与已发布工作流执行面：

| 类型 | 内容 |
|---|---|
| REST | `GET /agent/knowledge-bases`、`GET /agent/knowledge-bases/{id}`、`POST /agent/search`、`POST /agent/answer`、`GET /agent/workflows`、`POST /agent/query`（执行已发布工作流） |
| MCP | `list_knowledge_bases`、`search_knowledge`、`ask_knowledge_base`、`list_workflows`、`run_workflow`（执行已发布工作流） |

```bash
curl -s http://localhost/api/co-knowledge/v1/agent/search \
  -H "Authorization: Bearer <API_KEY>" \
  -H 'Content-Type: application/json' \
  -d '{"query":"设备巡检周期","mode":"hybrid","top_k":5}'
```

API Key 在「密钥管理」创建，可限制作用域（`kb:list` / `kb:search` / `kb:answer` / `workflow:read` / `workflow:run`）、知识库白名单、每 Key 限流与调用量统计。工作流执行走 `POST /agent/query`，需要 `workflow:run`。MCP 入口为 `/api/co-knowledge/v1/mcp`。接入细节见 [`docs/agent-integration.md`](docs/agent-integration.md)。

---

## 质量与基线

| 项目 | 当前值（2026-11-04 实测） |
|---|---|
| 后端单测 | **2,417 passed** / 7 deselected（约 58s） |
| 前端单测 | **936 passed** / 91 files（约 35s） |
| 接口契约 | OpenAPI **2.3.0**：65 条路径 / 93 个操作（含 `/health`），快照测试锁定 |
| E2E | Playwright：快速门禁 11 条用例约 25s；全量 148 条 / 20 个 spec（约 10 min） |
| 架构检查 | `python3 tools/check-architecture.py --strict`：**0 违规** |
| 检索基线（2,000 条查询，2026-10-29） | 向量 NDCG@10 **81.57%**、Recall@80 **95.02%**；关键词 NDCG@10 59.96% |
| 重排增益（2026-10-20 消融） | `Qwen3-Reranker-4B` 重排 top-50 → top-10：NDCG@10 **81.57% → 88.10%（+6.53 pp）** |
| 公开基准（2026-11-01） | SciFact 向量 NDCG@10 **68.45%**（同模型公开值 69.72%）；CRUD-RAG 关键词 **83.83%** / 向量 72.51%；RGB 噪声三档 88.67 / 86.67 / 85.67% |
| 图谱端到端（2WikiMultiHopQA，100 题，2026-11-02） | 属性抽图 + 边事实 + 规范化提示：EM **82.0%**、规范化 EM **90.0%**（同日 v1：75.0% / 81.0%） |

> 检索与基准指标均为公开数据集上的单次全量或抽样测量，随语料、模型与硬件变化；公开基准的口径与复跑见 [`docs/rag-benchmark-20261101.md`](docs/rag-benchmark-20261101.md)。

---

## 配置

关键环境变量（完整清单见 [`deploy/.env.example`](deploy/.env.example)，逐项说明见 [`docs/TECHNICAL-GUIDE.md`](docs/TECHNICAL-GUIDE.md) §6）：

| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` / `RKB_DB_PASSWORD` | 数据库口令，首次启动前必须修改 |
| `MODEL_GATEWAY_URL` / `MODEL_GATEWAY_EMBEDDINGS_PATH` | embedding 端点与路径（远端 `/v1/embeddings`，本地 Infinity `/embeddings`） |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` | 模型名与维度；1024 / 768 维按库共存，同一次查询使用该库绑定的模型 |
| `GENERATION_GATEWAY_URL` / `GENERATION_MODEL` / `GENERATION_API_KEY` | 生成端点 |
| `GENERATION_MAX_TOKENS` | 默认 16384；需小于上下文窗口 32768 |
| `RERANK_URL` / `RERANK_MODEL` | 可选 cross-encoder 重排端点/模型；模型注册表中的 rerank 模型优先 |
| `AUTH_MODE` | `local`（默认）/ `gateway` / `none` |
| `RKB_ADMIN_USERNAME` / `RKB_ADMIN_PASSWORD_FILE` | 首次管理员与初始密码文件 |
| `RKB_AGENT_KEY_PEPPER` | 使用 Agent REST / MCP 时需设置（`openssl rand -hex 32`） |
| `RKB_SECRET_KEY` / `RKB_SECRET_KEY_FILE` | 模型注册表凭据（`model_registry.api_key`）的静态加密密钥，请妥善保管 |
| `RKB_STORAGE_BACKEND` | `local`（默认）/ `minio` |
| `NO_PROXY` / `no_proxy` | 有宿主代理时，必须包含所有模型端点主机 |

### 鉴权模式

| `AUTH_MODE` | 行为 |
|---|---|
| `local` | 本地账号 + scrypt 口令 + HttpOnly 会话 Cookie；未登录的 UI/API 请求返回 `401` |
| `gateway` | 信任前置网关，只检查 `X-Auth-Value` / `X-Auth-Token` / `Authorization` 是否存在 |
| `none` | 关闭鉴权，未带身份时以 `AUTH_DEFAULT_USER` 归属 |

未知取值按启动失败处理，便于尽早发现误配置。账号管理用容器内 CLI：`python3 -m auth.cli create|list|reset-password|enable|disable|delete`。详见 [`docs/auth-login.md`](docs/auth-login.md)。

---

## 部署注意

- **单副本**：查询改写用进程内缓存保存多轮上下文，`rag-knowledge-base` 按单副本部署。
- **老内核（< 5.3）**：compose 已为容器写入 `security_opt: [seccomp:unconfined]` 以兼容 `clone3`；现代内核可直接移除该项。
- **HTTP 代理**：容器会继承宿主 `http_proxy`。模型端点域名必须进 `NO_PROXY`，否则请求被代理接走，症状类似「embedding 服务故障」。
- **离线部署**：3 个自建镜像（`ragstudio/rag-knowledge-base`、`ragstudio/web`、`ragstudio/opensearch`）就绪后，`docker compose ... up -d --no-build`。
- **子路径部署**：在 `deploy/.env` 设 `WEB_BASE_URL=/co-knowledge/`（首尾斜杠都要）并重建 web 镜像（`up -d --build web`），站点即挂在 `/co-knowledge/`，根路径自动 302 过去；后端 API 前缀 `/api/co-knowledge/v1` 不变。
- **数据**：唯一业务库 `rag_studio`；知识库文件默认在命名卷 `kb-storage`，运行期数据（密钥、日志、临时文件）在 `rkb-storage`；停止用 `down`，删数据用 `down -v`。

---

## 项目结构

```text
.
├── backend/      Python 3.11 + FastAPI：唯一后端
├── frontend/     Vue 3.5 + Element Plus + @antv/x6：唯一前端
├── contracts/    OpenAPI + JSON Schema：接口契约唯一来源
├── deploy/       Docker Compose、初始化脚本、OpenSearch 镜像
├── docs/         技术文档、架构、数据库 Schema、评测报告、验收记录
├── e2e/          Playwright 端到端
└── tools/        验收 / 基准评测脚本、架构检查
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/TECHNICAL-GUIDE.md`](docs/TECHNICAL-GUIDE.md) | 完整技术文档：架构与数据流、组件详解、部署、功能指南、配置、接口、排错与运维 |
| [`docs/api-reference.md`](docs/api-reference.md) | 对外 API 参考：约定、资源、状态码、SSE |
| [`docs/agent-integration.md`](docs/agent-integration.md) | Agent 接入：REST + MCP、API Key、作用域、Claude Code 配置、排错 |
| [`docs/external-api/`](docs/external-api/) | 交付给集成方的接口文档包（单文件 HTML + Markdown + Agent OpenAPI） |
| [`docs/database-schema.md`](docs/database-schema.md) | 数据库 Schema：单库两 schema、逐表定义、动态向量/图谱表模板 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 代码结构、依赖规则与修改约定 |
| [`docs/operator-abi.md`](docs/operator-abi.md) | 自定义算子 ABI v2：包格式、入口、公开模块 |
| [`deploy/operators/general-graph-extract/README.md`](deploy/operators/general-graph-extract/README.md) | 通用抽图算子 v1.2.0：`extractionProfile`、安装与升级 |
| [`docs/rag-benchmark-20261101.md`](docs/rag-benchmark-20261101.md) | 11 个公开基准的评测报告 |
| [`docs/opensearch.md`](docs/opensearch.md) | 为什么使用 OpenSearch（许可与中文分词） |
| [`e2e/README.md`](e2e/README.md) | E2E 运行手册 |
| [`docs/acceptance-handbook.md`](docs/acceptance-handbook.md) | 验收手册：分层入口、错误分支判据、边界夹具、缺陷分类与回归闭环 |

---

## 路线图

方向性规划：

| 阶段 | 方向 |
|---|---|
| 近期 | 本体约束全量生效（extends / disjoint / constraints）；传递、对称、反向关系；实体别名与规范化；Agentic 检索（向量/关键词种子 + 图遍历扩展上下文） |
| 中期 | 多跳子图按 BFS 层级返回并与 `depth` / `seed_k` 联动；图谱规模从百万级走向千万级；从文档自动归纳本体；质量治理（过期、冲突、血缘可查） |
| 远期 | 多域知识联邦与开放本体生态；算子与连接器市场；让 AI 应用直接消费结构化知识 |

---

## 开发与贡献

前端构建与单测需要 **Node ≥ 22.22**。

```bash
bash tools/run-tests.sh                 # 前端 vitest + 后端 pytest
python3 tools/check-architecture.py --strict   # 架构依赖检查
python3 tools/verify/generate-rkb-openapi.py --check   # 契约快照校验
```

- 接口契约以 [`contracts/`](contracts/) 为唯一来源，改接口先改契约。
- 改代码前请先读 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)（结构与修改约定）。

---

## 许可

[Apache License 2.0](LICENSE)。可自由商用与二次开发。

第三方组件与许可声明见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。
