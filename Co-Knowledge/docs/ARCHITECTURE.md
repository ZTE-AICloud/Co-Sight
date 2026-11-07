# Knowledge Studio 架构、目录与修改约定

> 本文是当前代码结构的权威说明，同时收录代码修改约定（§7）。

## 1. 领域词表（前后端共用）

代码包用单数 snake_case，HTTP 资源用复数 kebab-case；前端 feature 目录与后端包同名
（TypeScript 用 kebab-case，例如 `knowledge-base/`）。

| 领域 | 后端包 | API 资源 | 前端 feature |
|---|---|---|---|
| 知识库 | `knowledge_base/` | `/knowledge-bases` | `knowledge-base/` |
| 图谱 | `graph/` | `/graph-schemas`、`/graph-extractions`、`/graph-imports`、`/knowledge-bases/{id}/graph/*` | `graph/` |
| 算子 | `operators/` | `/operators` | `operators/` |
| 工作流 | `workflow/` | `/workflows` | `workflow/` |
| 问答 | `chat/` | `/query`（SSE） | `chat/` |
| 模型 | `model/` | `/models`、`/system/*-models` | `model/` |
| 检索 | `retrieval/` | `/retrieval` | — |
| Agent | `agent/` | `/agent/*`、`/mcp`、`/agent-keys` | `agent/` |
| 账号认证 | `auth/` | `/auth/*`（status/login/logout/me/password） | `auth/` |
| 系统 | `system/` | `/system/*`、`/health` | `system/` |
| 文档摄取 | `ingestion/` | —（内部） | — |
| 执行引擎 | `engine/` | —（内部） | — |
| 解析库 | `parsing/` | —（内部叶子） | — |
| 平台 | `infrastructure/` | — | 对应 `shared/` |
| 共享内核 | `shared/` | — | `shared/` |

**命名例外（避免遮蔽标准库）：** `src/` 是 `PYTHONPATH` 的第一项，顶层包名不能与
stdlib 重名。因此共享层叫 `infrastructure/`（不能叫 `platform`），算子域叫
`operators/`（不能叫 `operator`）。新增顶层包前先查 `sys.stdlib_module_names`。

### 1.1 命名

| 对象 | 规则 | 示例 |
|---|---|---|
| 后端包 | 单数 snake_case | `knowledge_base/` |
| HTTP 资源 | 复数 kebab-case | `/knowledge-bases` |
| 前端 feature | kebab-case，与后端领域同名 | `knowledge-base/` |
| Vue 组件 | PascalCase | `WorkflowEditorPage.vue` |
| 组合式函数 | `use` 前缀 | `useTableFillHeight.ts` |
| 常量 | UPPER_SNAKE_CASE | `DEFAULT_KB_TYPE` |

## 2. 当前后端结构

```text
backend/src/
├── main.py / app.py / http_api.py / startup.py
├── infrastructure/     # auth config crypto db http i18n logging search storage transport
├── shared/             # prefixes problem errors chunk_schema i18n
├── knowledge_base/     # KB、目录、文档、切片、task 队列
├── graph/              # schema、抽取、导入、查询、导出、图检索
├── operators/          # 注册、导入、模板、沙箱、系统算子
├── workflow/           # 画布、校验、发布、templates
├── engine/             # RAG 运行时（算子、检索器、重排、合成）
├── chat/               # /query、SSE、翻译、进程内 RKB 适配器
├── model/              # 注册表、网关客户端、端点解析
├── agent/              # REST、MCP、Key
├── auth/               # 本地账号、登录会话、AuthMiddleware、CLI
├── ingestion/          # 解析/切分/抽图管线、算子沙箱
├── system/             # /system、/health、系统端点
└── parsing/            # 纯格式解析库
```

## 2.1 前端结构

```text
frontend/src/
├── app/              # main.js、App.vue、router、store、i18n、directives、layout
├── pages/            # 路由级页面：knowledge-base/graph/workflow/chat/model/operators/agent/login
├── features/         # 领域实现，前后端同名：
│   ├── knowledge-base/  # api/components/composables/lib
│   ├── graph/           # api/components/composables/lib
│   ├── workflow/        # api/components/lib/modules
│   ├── chat/            # api/composables/lib
│   ├── model/           # api/components
│   ├── operators/       # api
│   ├── agent/           # api/components/lib
│   └── auth/            # api/session/guard/components（用户菜单、修改密码）
├── shared/           # api、ui、layout、lib、composables、constants、types
├── styles/
└── assets/
```

规则：页面只做编排；feature 内部自包含；`shared/lib` 不 import Vue；`shared/ui`
不 import 任何 feature；跨 feature 只通过对方公开入口或 `shared`。

## 3. 依赖规则

允许方向：

```text
app.py -> http_api -> 各领域 api -> service -> repository -> infrastructure / shared
领域之间只调用对方 service 的公开接口；禁止跨领域 import repository
infrastructure -> shared；shared 不得 import infrastructure 或领域
engine 不得 import workflow / chat（通过注入 provider/transport 反转）
ingestion 不得写知识库或图谱表（落库由 knowledge_base / graph 负责）
parsing 只依赖 infrastructure/shared
```

- 每个领域持久化统一叫 `repository`（KB 为 `knowledge_base/repository/`，
  workflow/model/agent 为 `repository.py` / `repository_pg.py`）。
- `engine` 的 workflow 配置 provider 与 RKB transport 由 `chat` 注入
  （`engine.context.rag_context.set_workflow_config_provider`、
  `engine.gateways.knowledge_base_client.set_transport`）。
- `graph` 对 KB 创建/删除的依赖走 `graph.service.lifecycle`。
- `operators` 对外只暴露 `operators.service`；其他领域不得直接 import `operators.repository`。

**可执行检查：**

```bash
python3 tools/check-architecture.py          # 与基线比较，禁止新增违规
python3 tools/check-architecture.py --strict # 最终要求 0
```

## 4. 稳定逻辑 ID（不是 Python 路径）

工作流画布/模板/DB 里持久化的算子包名形如 `core.rag.retriever.vector_retriever`。
它们是**工作流格式的稳定 ID**，运行时由
`engine/config_loader/default_packages_info.py:to_importable()` 统一翻译成可导入模块：

```text
core.rag.retriever.vector_retriever -> engine.retriever.vector_retriever
```

**不要**直接改这些字符串：那会让所有已保存/已发布画布被判为不可运行。

## 5. 新增一个领域

1. 建 `src/<domain>/`，至少包含 `api.py`、`service/`、`repository/`、`models.py`、`errors.py`。
2. 在 `app.py` 的显式注册序列里加 `register_<domain>_api`，**放在 catch-all 之前**。
3. 领域间只通过 service 调用；需要反向依赖时用注入（参考 `chat` 对 `engine` 的做法）。
4. 在本文词表与 `tools/check-architecture.py` 的 `DOMAINS` 里登记。
5. 补 `tests/<domain>/` 单测；跑 `tools/check-architecture.py` 与全量 pytest。

## 6. 关键装配点

- 领域间反向依赖通过装配点注入：`knowledge_base.graph_bridge`（graph 生命周期）、
  `knowledge_base.service.kbase_v2_service.set_workflow_binding_provider`
  （画布绑定检查）、`retrieval.repository.kbase_lookup`（KB 行读取）。
- HTTP 装配在顶层 `http_api.py`：按顺序 include 各领域 router，catch-all 最后注册；
  装配时安装上述提供者。路由实现分别在 `system/api.py`、`knowledge_base/api.py`、
  `retrieval/api.py`、`operators/api.py`、`graph/api.py`。
- `retrieval/` 负责查询面（`retrieve_service`、ES/向量读取、`node_mapper`）；
  写入面由 KB 调用 `retrieval.service.write/index`。
- 算子插件 ABI v2：`operator_api/`（types/logging/storage/llm/graph）是唯一
  公开导入面；沙箱只挂 `src/` 与插件目录；不兼容的导入在导入期返回
  `operator_plugin_incompatible`。
- 前端按 `app/ pages/ features/ shared/` 分层；大文件拆分顺序见 §7.1。

## 7. 代码修改约定

### 7.1 大文件与拆分顺序

以下文件体量大、耦合深，且大部分逻辑与 UI 状态绑定。拆分前先补测试，按下面的顺序推进：

| 文件 | 规模 | 说明 |
|---|---|---|
| `frontend/src/features/graph/components/GraphVisualization.vue` | ~3100 行 | 图谱可视化：大量 x6 事件与响应式状态，纯函数比例低 |
| `frontend/src/pages/workflow/WorkflowEditorPage.vue` | ~2500 行 | 画布编辑器：节点/连线/抽屉/保存/发布耦合在一个页面 |
| `frontend/src/features/graph/components/GraphCanvasVis.vue` | ~2500 行 | 图谱画布渲染 |
| `frontend/src/features/graph/components/GraphControls.vue` | ~2300 行 | 属性面板：props 契约被模板多处直接读取 |
| `frontend/src/pages/graph/GraphDetailPage.vue` | ~2100 行 | 图谱详情：查询/编辑/可视化多态 |

拆分的正确顺序：**先把纯函数抽到 `lib/` 并补单测，再谈 UI 层拆分**。
抽函数时函数体保持原样，只加 `export` 与类型标注；新模块文件头写明用途。
拆 UI 时，被拆区块的 scoped 样式必须一起搬走（scoped 规则到不了子组件内部）。

### 7.2 重复逻辑处理原则

跨页面重复的逻辑（错误信息提取、`getCurrentInstance()` 取 `proxy` 等）统一收敛到
`shared/lib/` 或领域内的 `lib/`，新代码直接复用这些入口。
重复逻辑清理作为独立改动提交，与功能改动分开，避免半截清理造成两套实现并存。

## 8. 验证入口

```bash
bash tools/run-tests.sh                     # 前端 vitest + 后端 pytest（容器内）
python3 tools/check-architecture.py --strict
python3 tools/verify/generate-rkb-openapi.py --check
python3 tools/verify/exposure-audit.py --check
```

要点：

- 后端单测在容器内跑，且**挂载仓库根**（只挂服务目录会让跨服务模板用例静默 skip）；
  **skip 数必须为 0**，出现 skip 按失败处理。
- 前端测试需要 **Node ≥ 22**（vitest 5 + jsdom 30 的要求）；Node 20 下 jsdom 组件用例
  会以 `Failed to start forks worker` 失败。
- 新写的测试要做一次**变异验证**（改坏源码 → 确认对应用例变红 → 还原），
  否则无法证明它不是装饰。
- 前端构建固定 `BASE_URL=/`（镜像构建里已显式设置）。

CI 见 `.github/workflows/ci.yml`：前端 vitest、后端 pytest（含 skip==0 断言）、
`ruff check src`。

`contracts/openapi/rkb-api.yaml` 与路由/operationId 必须逐字节不变；任何路由函数改名
要么保持函数名，要么显式写 `operation_id='<旧值>'`。
