<!-- doc-title: Knowledge Studio REST 接入指南（Agent API） -->
<!-- doc-version: 1.4.0 -->

# Knowledge Studio REST 接入指南（Agent API）

## 文档信息

| 项 | 值 |
|---|---|
| 文档名称 | Knowledge Studio REST 接入指南（Agent API） |
| 接口契约版本 | 1.4.0 |
| 文档版本 | 1.4 |
| 更新日期 | 当前版本 |
| 适用产品 | Knowledge Studio |
| 读者 | 外部集成方、Agent 平台、后端服务开发者 |
| 接口前缀 | `/api/co-knowledge/v1/agent` |
| 认证方式 | Agent API Key（`Authorization: Bearer`） |
| 机器可读契约 | OpenAPI 3.0.2（`GET /openapi.json`） |

> 本文只覆盖 **REST 接入方式**：使用 Agent API Key 调用文档知识库的列库、详情、检索、引用式问答，以及工作流的查询与执行。
> 建库、上传、删除、切片、算子、工作流创建/编排/发布、模型注册与密钥管理等操作请在 Knowledge Studio 控制台完成；这些不在本文范围内。
> 需要 MCP 接入（Claude Code、IDE、桌面 Agent）时，请使用同一套 Key 与 Scope，接入点为 `/api/co-knowledge/v1/mcp`，详见主接口文档。

## 1. 概述

### 1.1 适用场景

REST 接入使用标准 HTTP + JSON，适合：

- 后端服务、工作流引擎、定时任务等机器对机器集成；
- Dify、Coze 等支持导入 OpenAPI 的 Agent 平台；
- 需要自行拼装检索结果、或需要引用式问答结果的业务系统；
- 不依赖 MCP 客户端的脚本与自动化流程。

### 1.2 接口覆盖范围

| 能力 | 覆盖方式 | 说明 |
|---|---|---|
| 列出可访问的文档知识库 | Agent API | 只返回当前 Key 有权访问的文档库 |
| 单个知识库详情 | Agent API | 不存在或为图谱库时返回 404 |
| 片段检索（向量 / 关键词 / 混合） | Agent API | 返回带 `S1…` 编号的原文片段 |
| 引用式问答 | Agent API | 基于片段生成回答，答案带 `[S1]` 引用 |
| 工作流查询 | Agent API | 用于发现工作流 ID 与发布状态 |
| 执行已发布工作流 | Agent API | `POST /query`，需要 `workflow:run`；支持 JSON 与 SSE |
| 图谱知识库检索 | 原生图谱检索接口 | Agent 接口聚焦文档库检索与问答 |
| 建库、上传、修改、删除 | 控制台 | 管理面操作在控制台完成 |
| 工作流创建、画布编排、发布 | 控制台 | 管理面操作在控制台完成 |
| 流式回答（SSE） | Agent API | 通过 `POST /query` 的 `stream=true`；`/agent/answer` 仍为非流式 |

### 1.3 与 MCP 的关系

REST 与 MCP 共用同一套 Agent API Key、Scope 与知识库白名单：

- 同一个 Key 既可以调用 REST，也可以连接 MCP；
- 权限、限流、过期时间在两种接入方式上一致；
- REST 成功响应体就是资源本身，MCP 的工具结果里带 `trace_id`。

本文只描述 REST；MCP 的客户端配置与工具语义见主接口文档。工作流执行在 REST 面是 `POST /query`，在 MCP 面是 `run_workflow`（`stream=true` 时 token 通过 MCP progress 通知旁路送达，工具结果仍返回完整答案），两者共用同一套发布快照与白名单校验。

## 2. 接入准备

### 2.1 基础地址

```text
https://<host>/api/co-knowledge/v1/agent
```

- 控制台「远程接入 → 接入方法 → REST API」会显示当前部署的实际基础地址，可直接复制。
- 部署方可以通过 `RKB_AGENT_PUBLIC_BASE` 把它覆盖成绝对地址；覆盖后 OpenAPI 的 `servers[0].url` 同步为该值。
- 下文示例统一使用 `https://rag.example.com` 作为部署域名，请替换为实际地址。

### 2.2 获取 API Key

Agent API Key 由平台管理员在控制台「远程接入 → 密钥管理」创建，创建时可以设置：

| 配置项 | 说明 |
|---|---|
| 名称 | 便于识别的 Key 名称，例如 `dify-prod` |
| 权限范围（Scope） | 决定可调用哪些接口，见 3.2 |
| 知识库白名单 | 留空 = 全部可访问文档库；非空 = 只允许列表内的库 |
| 每分钟上限 | 每个 Key 的限流，默认 60 次/分钟；`0` 表示不限制 |
| 过期时间 | 留空 = 永不过期；到期后请求返回 401 |

Key 的格式为：

```text
ragk_<8 位前缀>_<secret>
```

完整 Key **只在创建成功时显示一次**，关闭后只能看到前缀。请立即复制并保存到密钥管理系统；服务端只保存前缀与哈希，无法找回明文。

### 2.3 网络与证书

- 生产环境必须使用 HTTPS。Agent Key 是 Bearer 凭据，走 HTTP 时是明文传输。
- 如果服务前面有网关或反向代理，请确认：
  - 网关不会剥离 `Authorization` 请求头；
  - 网关的读超时 ≥ 问答接口的服务端超时（默认 120 秒，部署可能配置得更大）；
  - 网关不会把 `application/problem+json` 改写为其他错误格式。

## 3. 认证与权限

### 3.1 请求头

每个请求都必须携带 Agent API Key，以下两种写法二选一：

```http
Authorization: Bearer <YOUR_API_KEY>
```

```http
X-API-Key: <YOUR_API_KEY>
```

- 同时携带时，优先使用 `Authorization: Bearer`；只有它无法解析时才回落到 `X-API-Key`。
- Agent REST 不使用浏览器会话 Cookie，也不受控制台登录状态影响；无状态请求，适合服务端集成。
- 如果部署启用了 `AUTH_MODE=gateway`，请统一使用 `Authorization` 请求头，前置网关会校验它。

### 3.2 权限范围（Scope）

| Scope | 允许调用的接口 |
|---|---|
| `kb:list` | `GET /knowledge-bases`、`GET /knowledge-bases/{kb_id}` |
| `kb:search` | `POST /search` |
| `kb:answer` | `POST /answer` |
| `workflow:read` | `GET /workflows` |
| `workflow:run` | `POST /query`（执行已发布工作流） |

- 缺少所需 Scope 时返回 `403 forbidden_scope`，错误体里的 `required_scope` 会指出缺少哪一项。
- 需要问答时，Key 必须显式勾选 `kb:answer`；只有 `kb:search` 不能调用问答接口。
- 按最小权限原则创建 Key；不同集成方建议使用不同 Key，便于单独停用与统计调用量。

### 3.3 知识库白名单

- Key 的 `kbIds` 为空：可以访问**全部文档知识库**。
- Key 的 `kbIds` 非空：只允许访问列表内的知识库。
- 显式传入不存在或图谱知识库的 ID：`404 knowledge_base_not_found`。
- 显式传入存在但不在白名单的 ID：`403 knowledge_base_forbidden`。
- 不传 `knowledge_base_ids` 时，接口会检索该 Key 可访问的全部文档库；如果数量超过部署上限（默认 50），返回 `400 invalid_request`，此时请显式传 `knowledge_base_ids`。
- 执行工作流时，服务端会读取该工作流**发布快照**绑定的文档/结构化知识库；只要有一个不在 Key 的白名单内，就返回 `403 knowledge_base_forbidden`。图谱知识库不在 Agent Key 白名单的下拉范围内，运行含图谱检索的工作流由 `workflow:run` scope 授权。
- Agent API 的直接检索只覆盖**文档知识库**，不包含图谱知识库；工作流内部仍可包含图谱检索。

### 3.4 与部署鉴权模式（AUTH_MODE）的关系

| `AUTH_MODE` | 原生 REST（`/knowledge-bases`、`/query` 等） | Agent REST（`/agent/*`） |
|---|---|---|
| `none` | 不做应用层鉴权，仅靠网络隔离 | **仍要求 Agent API Key** |
| `local` | 要求登录会话 Cookie | 使用 Agent API Key，不需要会话 |
| `gateway` | 要求网关注入的身份头 | 使用 Agent API Key；请使用 `Authorization` 头 |

> 无论部署采用哪种 `AUTH_MODE`，Agent REST 都只认 Agent API Key。`AUTH_MODE=none` 时请务必通过内网或前置网关保护服务地址。

### 3.5 Key 的生命周期

| 状态 | 请求结果 |
|---|---|
| 正常 | 通过鉴权，按 Scope 与白名单放行 |
| 已停用 | `401 unauthorized` |
| 已过期 | `401 unauthorized` |
| 已删除 | `401 unauthorized` |
| 服务端未配置签名 pepper | `503 configuration_error`（属于部署配置问题） |
| Key 存储不可用 | `503 agent_key_store_unavailable`（数据库未初始化） |

- 修改 Scope、白名单、限流或过期时间后**立即生效**，已在进行中的请求不受影响。
- 轮换服务端签名 pepper 会使所有已发放的 Key 立即失效，必须与 Key 重发一起进行。
- 删除 Key 不可恢复；删除后使用该 Key 的集成会立即收到 401。

## 4. 快速开始

### 4.1 环境变量

```bash
export BASE="https://rag.example.com/api/co-knowledge/v1/agent"
export KNOWLEDGE_STUDIO_KEY="ragk_1a2b3c4d_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### 4.2 第一步：列出可访问的知识库

```bash
curl -sS "$BASE/knowledge-bases" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY"
```

```json
[
  {
    "id": "0123456789abcdef0123456789abcdef",
    "name": "product-manual",
    "description": "产品手册",
    "type": "document",
    "embedding_model": "Qwen3-Embedding-0.6B",
    "status": "0",
    "created_date": "2024-01-01T00:00:00"
  }
]
```

从响应里取 `id`，作为下一步检索的 `knowledge_base_ids`；也可以省略该字段，让服务检索全部可访问文档库。

### 4.3 第二步：检索片段

```bash
curl -sS "$BASE/search" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何配置检索编排？",
    "knowledge_base_ids": ["0123456789abcdef0123456789abcdef"],
    "mode": "auto",
    "top_k": 5
  }'
```

响应体直接是检索结果对象，`results[].text` 是原文片段，`citation_id` 是 `S1`、`S2` 这样的引用编号。

### 4.4 第三步：生成带引用的回答

```bash
curl -sS "$BASE/answer" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何配置检索编排？",
    "knowledge_base_ids": ["0123456789abcdef0123456789abcdef"],
    "top_k": 8
  }'
```

有检索结果时返回 `answer` 与 `citations`；检索结果为空时返回 HTTP 200、`answer: null`、`no_results: true`，不会调用生成模型。

## 5. 接口参考

所有路径均相对基础地址 `/api/co-knowledge/v1/agent`。

| 方法 | 路径 | Scope | 用途 |
|---|---|---|---|
| `GET` | `/knowledge-bases` | `kb:list` | 列出当前 Key 可访问的文档知识库 |
| `GET` | `/knowledge-bases/{kb_id}` | `kb:list` | 单个知识库详情 |
| `POST` | `/search` | `kb:search` | 检索片段（vector / keyword / hybrid） |
| `POST` | `/answer` | `kb:answer` | 基于片段回答并带 `[S1]` 引用 |
| `GET` | `/workflows` | `workflow:read` | 工作流列表，支持 `publishType` 筛选 |
| `POST` | `/query` | `workflow:run` | 执行已发布工作流，支持 JSON / SSE |
| `GET` | `/openapi.json` | 无 | OpenAPI 3.0.2，供平台导入 |

### 5.1 列知识库

```http
GET /knowledge-bases
Authorization: Bearer <YOUR_API_KEY>
```

- Scope：`kb:list`
- 查询参数：无
- 响应：裸数组，返回全部**当前 Key 可访问**的文档知识库；**顺序不保证**。

**响应示例：**

```json
[
  {
    "id": "0123456789abcdef0123456789abcdef",
    "name": "product-manual",
    "description": "产品手册",
    "type": "document",
    "embedding_model": "Qwen3-Embedding-0.6B",
    "status": "0",
    "created_date": "2024-01-01T00:00:00"
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 知识库 ID |
| `name` | string | 知识库名称 |
| `description` | string \| null | 描述 |
| `type` | string \| null | 历史类型标识，不代表文档库/图谱库分类 |
| `embedding_model` | string \| null | embedding 注册名 |
| `status` | string \| null | 知识库状态码，见下方说明 |
| `created_date` | string \| null | 创建时间，ISO 8601，秒级，无时区后缀（服务端本地时间） |

**关于 `status`：**

| 值 | 含义 |
|---|---|
| `0` | 已创建，文档库通常可直接检索 |
| `1` ~ `4` | 解析 / 切分 / 生成 / 入库处理中 |
| `5` ~ `8` | 待发布 / 发布中 / 已发布 / 已发布后有改动 |
| `101` ~ `106` | 处理或发布失败 |

列表**不会**按“已就绪”过滤；请根据 `status` 判断是否适合检索。文档库通常使用 `0`。

### 5.2 知识库详情

```http
GET /knowledge-bases/{kb_id}
Authorization: Bearer <YOUR_API_KEY>
```

- Scope：`kb:list`
- 路径参数：`kb_id`，知识库 ID。
- 响应：单个对象，字段同 5.1。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 403 | `knowledge_base_forbidden` | 知识库存在，但不在 Key 的白名单 |
| 404 | `knowledge_base_not_found` | 知识库不存在，或为图谱知识库 |

### 5.3 检索片段

```http
POST /search
Authorization: Bearer <YOUR_API_KEY>
Content-Type: application/json
```

- Scope：`kb:search`
- 请求体不接受未声明字段；多传字段会返回 `422 validation_failed`。

**请求示例：**

```json
{
  "query": "如何配置检索编排？",
  "knowledge_base_ids": ["0123456789abcdef0123456789abcdef"],
  "mode": "auto",
  "top_k": 8,
  "score_threshold": 0.0
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 查询文本，1–2000 字符 |
| `knowledge_base_ids` | string[] | 否 | 省略或空数组 = 全部可访问文档库；元素会去重、去空白 |
| `mode` | string | 否 | `auto`（默认）、`hybrid`、`vector`、`keyword` |
| `top_k` | integer | 否 | 返回条数，默认 8，上限由部署配置决定（默认 20） |
| `score_threshold` | number | 否 | 0–1，仅向量路生效；默认 0 |

**`mode` 语义：**

| 模式 | 行为 | 失败处理 |
|---|---|---|
| `auto` | 两路都可用时 RRF 融合 | 单路失败自动降级到另一路；两路都失败才返回 502 |
| `hybrid` | 两路都查并做 RRF 融合 | 显式指定知识库时，任一库或任一路失败即返回 502；不指定时降级并置 `degraded=true`；两路都失败返回 502 |
| `vector` | 只查向量路 | 显式指定知识库时失败即 502；不指定时部分库失败降级，全部失败返回 502 |
| `keyword` | 只查关键词路 | 同 `vector` |

**响应示例：**

```json
{
  "query": "如何配置检索编排？",
  "mode": "hybrid",
  "results": [
    {
      "citation_id": "S1",
      "knowledge_base_id": "0123456789abcdef0123456789abcdef",
      "knowledge_base_name": "product-manual",
      "chunk_id": null,
      "document_id": "33333333333333333333333333333333",
      "source": "overview.md",
      "score": 0.03225806451612903,
      "scores": {"vector": 0.6032068008815435, "keyword": 12.344121932983398},
      "text": "切片正文……",
      "metadata": {"chunk_index": "3", "source": "overview.md", "type": 0}
    }
  ],
  "degraded": false,
  "warnings": []
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 原样返回查询文本 |
| `mode` | string | **实际生效**的模式；`auto` 可能返回 `hybrid` / `vector` / `keyword` / `auto` |
| `results` | array | 检索结果，按融合分数或单路分数排序 |
| `degraded` | boolean | `true` 表示部分路径或知识库失败，但仍有结果 |
| `warnings` | array | 结构化告警，见下表 |

**`results[]` 字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `citation_id` | string | `S1`、`S2`……用于引用 |
| `knowledge_base_id` | string | 知识库 ID |
| `knowledge_base_name` | string \| null | 知识库名称 |
| `chunk_id` | string \| null | 切片 ID；向量路可能为 null |
| `document_id` | string \| null | 文档 ID；部分文档的向量表可能没有文件 ID/切片 ID |
| `source` | string \| null | 文件名 |
| `score` | number | 单路分数；`hybrid` 时为 RRF 融合分数，不能与余弦相似度直接比较 |
| `scores` | object \| null | `hybrid` 时给出各路原始分数：`vector`、`keyword`；其他模式为 null |
| `text` | string | 片段正文，最多 2000 字符 |
| `metadata` | object \| null | 元数据：`chunk_index`、`source`、`type` 等 |

**`warnings[]`：**

| `code` | 含义 |
|---|---|
| `vector_table_missing` | 该知识库没有向量表（未导入或未建索引） |
| `keyword_index_missing` | 该知识库没有关键词索引 |
| `vector_path_failed` | 向量路查询失败（embedding 或向量库异常） |
| `keyword_path_failed` | 关键词路查询失败（搜索引擎异常） |

```json
{
  "code": "vector_path_failed",
  "message": "vector search failed",
  "knowledge_base_id": "0123456789abcdef0123456789abcdef"
}
```

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 400 | `invalid_request` | 可访问知识库超过部署上限且未显式指定 ID |
| 400 | `no_accessible_knowledge_bases` | Key 没有任何可访问的文档库 |
| 401 | `unauthorized` | Key 缺失、无效、停用或过期 |
| 403 | `forbidden_scope` | Key 没有 `kb:search` |
| 403 | `knowledge_base_forbidden` | 显式 ID 不在 Key 的白名单 |
| 404 | `knowledge_base_not_found` | 显式 ID 不存在或为图谱库 |
| 422 | `validation_failed` | 参数校验失败（含未声明字段、`top_k` 超上限、ID 数量超上限） |
| 429 | `rate_limited` | 超过 Key 的每分钟上限 |
| 502 | `retrieval_failed` | 检索整体失败 |

### 5.4 引用式问答

```http
POST /answer
Authorization: Bearer <YOUR_API_KEY>
Content-Type: application/json
```

- Scope：`kb:answer`
- 请求体不接受未声明字段。

**请求示例：**

```json
{
  "question": "如何配置检索编排？",
  "knowledge_base_ids": ["0123456789abcdef0123456789abcdef"],
  "mode": "auto",
  "top_k": 8,
  "model": "your-llm-model"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 问题文本，1–2000 字符 |
| `knowledge_base_ids` | string[] | 否 | 省略或空数组 = 全部可访问文档库 |
| `mode` | string | 否 | 检索模式，语义同 5.3 |
| `top_k` | integer | 否 | 检索来源数，默认 8，上限由部署配置决定（默认 20） |
| `model` | string | 否 | 可选，已注册的 LLM 名称；部署若设置了强制模型则忽略此字段 |

**响应示例：**

```json
{
  "answer": "根据提供的资料，配置步骤如下……[S1]",
  "citations": [
    {
      "citation_id": "S1",
      "knowledge_base_id": "0123456789abcdef0123456789abcdef",
      "document_id": "33333333333333333333333333333333",
      "source": "overview.md",
      "chunk_id": null,
      "text": "切片正文……"
    }
  ],
  "model": "your-llm-model",
  "usage": {
    "prompt_tokens": 717,
    "completion_tokens": 108,
    "total_tokens": 825
  },
  "no_results": false,
  "reason": null,
  "warnings": []
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `answer` | string \| null | 回答正文；`no_results=true` 时为 null |
| `citations` | array | 实际送入生成模型的来源；每条对应答案里的 `[S1]` |
| `citations[].text` | string | 来源片段，受总上下文预算（12000 字符）限制，可能被截断 |
| `model` | string \| null | 实际使用的模型注册名 |
| `usage` | object \| null | 上游生成端点返回的 token 用量，结构可能随模型变化 |
| `no_results` | boolean | 检索结果为空时为 true；此时不会调用生成模型，HTTP 仍为 200 |
| `reason` | string \| null | `no_results=true` 时为 `no_context` |
| `warnings` | array | 检索告警与引用告警 |

**`citations[]` 字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `citation_id` | string | `S1`、`S2`……与答案里的引用编号对应 |
| `knowledge_base_id` | string | 知识库 ID |
| `document_id` | string \| null | 文档 ID |
| `source` | string \| null | 文件名 |
| `chunk_id` | string \| null | 切片 ID；可能为 null |
| `text` | string | 送入生成模型的片段正文（可能被上下文预算截断） |

**引用告警：**

| `code` | 含义 |
|---|---|
| `unknown_citation` | 答案引用了未提供的来源编号 |
| `no_citations_in_answer` | 答案没有引用任何来源 |

**重要语义：**

- `no_results=true` 只表示**检索结果为空**。如果检索到不相关片段，模型仍可能回答“资料中没有答案”，此时 `no_results=false`，需要业务侧判断答案内容。
- `citations` 只包含**实际送入生成模型**的来源，`text` 可能因上下文预算被截断。
- 答案质量与引用完整性由模型决定；请把 `citations` 作为溯源依据，不要把 `answer` 当作唯一事实来源。
- 回答接口会调用生成模型，通常比检索慢；请给客户端设置足够的超时，不要用检索接口的超时值套用问答接口。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 400 | `invalid_request` | 可访问知识库超过部署上限且未显式指定 ID |
| 400 | `no_accessible_knowledge_bases` | Key 没有任何可访问的文档库 |
| 401 | `unauthorized` | Key 缺失、无效、停用或过期 |
| 403 | `forbidden_scope` | Key 没有 `kb:answer` |
| 403 | `knowledge_base_forbidden` | 显式 ID 不在白名单 |
| 404 | `knowledge_base_not_found` | 显式 ID 不存在或为图谱库 |
| 422 | `validation_failed` | 参数校验失败（含未声明字段） |
| 429 | `rate_limited` | 超过 Key 的每分钟上限 |
| 502 | `retrieval_failed` | 检索整体失败 |
| 502 | `answer_failed` | 生成端点不可用、返回非 2xx、空内容或输出被截断 |
| 503 | `answer_unavailable` | 没有可用生成模型，或问答接口被部署方关闭 |
| 503 | `configuration_error` | Agent Key pepper 未配置（服务端配置问题） |
| 503 | `agent_key_store_unavailable` | Key 存储不可用（数据库未初始化） |

### 5.5 工作流查询（只读）

Agent REST 只提供工作流**查询**，不提供创建、画布编排、发布或取消发布。工作流的创建与发布在 Knowledge Studio 控制台完成；查询接口用于发现工作流 ID 与发布状态。

```http
GET /workflows?page=1&size=100&publishType=1
Authorization: Bearer <YOUR_API_KEY>
```

- Scope：`workflow:read`

| 查询参数 | 默认 | 说明 |
|---|---|---|
| `page` | 1 | 页码，从 1 开始，最大 10000 |
| `size` | 10 | 每页条数，1–1000 |
| `keyword` | — | 按名称模糊匹配，不区分大小写，最长 255 字符 |
| `publishType` | — | `0` 未发布、`1` 已发布、`2` 已发布但草稿有改动；不传表示不筛选 |

**响应示例（省略部分字段）：**

```json
{
  "items": [
    {
      "workFlowId": "RAG_Workflow_1a2b",
      "name": "产品手册问答",
      "description": "客服机器人",
      "template": "Sequential",
      "knowledgeType": "knowledgeBase",
      "publishType": 1,
      "status": 1,
      "createdBy": "admin",
      "createdDate": "2024-01-01 00:00:00",
      "lastUpdatedDate": "2024-01-02 00:00:00",
      "kbPkIds": [
        {
          "name": "product-manual",
          "tableName": "doc_0123456789abcdef0123456789abcdef",
          "embeddingModel": "Qwen3-Embedding-0.6B"
        }
      ],
      "graphKbPkIds": []
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 100
}
```

| 字段 | 说明 |
|---|---|
| `workFlowId` | 工作流 ID（注意大写 `F`）；编排问答接口的 `workflow_id` 就是它 |
| `name` / `description` | 名称 / 描述 |
| `template` | 播种模板（`Sequential` / `Blended` / `Conditional`） |
| `publishType` | 0 未发布 / 1 已发布 / 2 已发布但草稿有改动 |
| `createdBy` / `createdDate` / `lastUpdatedDate` | 归属与时间 |
| `kbPkIds` / `graphKbPkIds` | 绑定的文档库 / 图谱库（含 `tableName`、`embeddingModel` 等） |

**怎么用：**

- 先查 `publishType=1`（或 `2`）拿已发布工作流的 `workFlowId`；
- `publishType=2` 表示发布后草稿又改过，仍可运行发布快照；只需排除 `0`；
- 拿到 `workFlowId` 后，用带 `workflow:run` 的同一个 Key 调用 `POST /query` 执行（见 5.6）。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 401 | `unauthorized` | Key 缺失、无效、停用或过期 |
| 403 | `forbidden_scope` | 缺少 `workflow:read` |
| 500 | `internal_error` | 工作流存储不可用等服务端错误 |

### 5.6 执行已发布工作流

```http
POST /query
Authorization: Bearer <YOUR_API_KEY>
Content-Type: application/json
```

> 完整路径是 `/api/co-knowledge/v1/agent/query`。它与浏览器「对话测试」页使用的
> 原生 `/query` 共用同一套编排与 SSE 逻辑，但鉴权与 OpenAPI 都归在 Agent 面。

- Scope：`workflow:run`
- 只执行**已发布**工作流；请求体不接受 `scope` 等内部字段（多传返回 `422 validation_failed`）。
- Key 的 `kbIds` 非空时，工作流发布快照绑定的文档/结构化知识库必须都在白名单内；
  图谱知识库不受该白名单约束（由 `workflow:run` 授权）。

**请求示例（非流式）：**

```json
{
  "question": "如何配置检索编排？",
  "conversation_id": "d-001",
  "workflow_id": "RAG_Workflow_1a2b",
  "stream": false,
  "include_retrieval": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 用户问题，1–2000 字符 |
| `conversation_id` | string | 是 | 对话 ID；同一 ID 的多轮请求共享上下文 |
| `workflow_id` | string | 是 | 已发布工作流 ID；API Key 调用必须显式传入 |
| `stream` | boolean | 否 | `true` 返回 SSE；默认 `false` |
| `include_retrieval` | boolean | 否 | `true` 时随响应返回本轮检索依据 |
| `chat_history` | array | 否 | 多轮历史，元素为 `{"question": "...", "answer": "..."}` |

> 请求体不接受 `scope`、`kwargs` 等内部字段；多传返回 `422 validation_failed`。

**非流式响应示例：**

```json
{
  "conversation_id": "d-001",
  "answer": "根据检索结果，检索编排的配置步骤如下……",
  "retrieval": {
    "query": "如何配置检索编排？",
    "items": [],
    "stats": {"count": 0, "total": 0, "sources": 0, "knowledgeBases": 0}
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `conversation_id` | string | 原样返回 |
| `answer` | string | 回答正文，通常为 Markdown/纯文本 |
| `retrieval` | object | 仅 `include_retrieval=true` 时出现 |

> Agent 面返回的是精简形状；原生 `/query` 的 `placeholder` / `citation` / `related_context`
> 历史字段不会出现在 `/agent/query` 的响应里。

**SSE 模式：**

`stream=true` 或请求头 `Accept: text/event-stream` 时返回 `text/event-stream`：

| 事件 | 出现时机 | `data` 结构 |
|---|---|---|
| `retrieval` | 仅 `include_retrieval=true`；首个 `token` 之前，最多一次 | `{"conversation_id": "...", "evidence": {...}}` |
| `token` | 多次 | `{"conversation_id": "...", "content": "增量文本"}` |
| `done` | 终态，一次 | `{"conversation_id": "...", "finish_reason": "stop"}` |
| `error` | 终态，最多一次 | problem 字段 + `conversation_id` |

- 出第一字节之前的失败仍是真实 HTTP 状态码 + `application/problem+json`；
  进入流后的失败 HTTP 仍为 200，通过 `event: error` 表达。
- 服务端约每 15 秒发送一行 `:` 开头的注释作为心跳，客户端应忽略。
- 客户端超时建议 ≥ 300 秒；`EventSource` 不支持 `POST`，请用 `fetch` + `ReadableStream` 或成熟 SSE 库。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 401 | `unauthorized` | Key 缺失、无效、停用或过期 |
| 403 | `forbidden_scope` | Key 缺少 `workflow:run` |
| 403 | `knowledge_base_forbidden` | 工作流绑定的知识库不在 Key 白名单 |
| 404 | `published_workflow_not_found` | 工作流不存在或尚未发布 |
| 422 | `validation_failed` | 缺少 `question`、`conversation_id`、`workflow_id`，或参数非法 |
| 429 | `rate_limited` | 超过 Key 的每分钟上限 |
| 500 | `workflow_config_invalid` | 工作流配置损坏 |
| 502 | `knowledge_base_unavailable` / `llm_unavailable` / `upstream_unavailable` | 上游依赖失败 |
| 503 | `knowledge_base_not_imported` / `no_llm_available` | 知识库未就绪或没有可用生成模型 |

### 5.7 OpenAPI 导入

```http
GET /openapi.json
```

- 该端点**不需要 Agent API Key**（若部署前置网关有统一鉴权，则以网关要求为准）。
- Agent 接口总开关或 REST 子接口关闭时，该端点同样不可用（404）。
- 返回 OpenAPI **3.0.2**，可直接导入 Dify、Coze 等平台。
- `servers[0].url` 由部署配置决定；未配置时为相对路径 `/api/co-knowledge/v1/agent`。需要绝对地址的平台，请让部署方把 `RKB_AGENT_PUBLIC_BASE` 设为完整地址。
- 不提供 Swagger UI。
- OpenAPI 覆盖 `/agent/*` 的 **6 条**业务路径（含 `POST /agent/query`）。
- 本目录另附一份离线快照 `openapi/agent-api.yaml`，字段与运行时契约一致。

## 6. 通用约定

### 6.1 成功响应

- 成功响应的 `Content-Type` 为 `application/json`。
- 响应体就是资源本身：列表是 JSON 数组，详情/检索/问答是 JSON 对象；没有 `{code, data, bo}` 之类的信封。
- 所有响应（含错误）都带 `X-Request-Id` 响应头，可用于与服务端日志对账；客户端传入合法的 `X-Request-Id` 会原样回显，缺失或不合法时由服务端生成。

### 6.2 错误响应

错误使用真实 HTTP 状态码，响应体为 RFC 9457 `application/problem+json`：

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
X-Request-Id: 8f1d2c3b4a5e6f70

{
  "type": "urn:ragstudio:problem:forbidden_scope",
  "title": "Forbidden scope",
  "status": 403,
  "detail": "API key does not have the required scope: kb:search",
  "code": "forbidden_scope",
  "instance": "/api/co-knowledge/v1/agent/search",
  "required_scope": "kb:search"
}
```

| 字段 | 说明 |
|---|---|
| `type` | 稳定的问题类型 URI，形如 `urn:ragstudio:problem:<code>` |
| `title` | 人类可读的英文标题，可能随版本调整 |
| `status` | HTTP 状态码，与响应状态行一致 |
| `detail` | 具体错误说明；请勿依赖其精确文案做逻辑判断 |
| `code` | **稳定的机器码**，业务逻辑请以它为准 |
| `instance` | 触发错误的请求路径 |
| 扩展字段 | 视错误而定，例如 `required_scope`、`knowledge_base_id`、`errors[]`、`retry_after_seconds` |

**错误码总表：**

| HTTP | `code` | 说明 |
|---|---|---|
| 400 | `invalid_request` | 请求语义不合法，例如可访问知识库超过上限且未显式指定 ID |
| 400 | `no_accessible_knowledge_bases` | Key 没有任何可访问的文档知识库 |
| 401 | `unauthorized` | Key 缺失、无效、停用或过期 |
| 403 | `forbidden_scope` | Key 缺少所需 Scope |
| 403 | `knowledge_base_forbidden` | 知识库不在 Key 的白名单 |
| 404 | `knowledge_base_not_found` | 知识库不存在或为图谱库 |
| 404 | `not_found` | 路径不存在 |
| 405 | `method_not_allowed` | HTTP 方法不被支持 |
| 422 | `validation_failed` | 请求参数未通过校验；`errors[]` 给出字段级原因 |
| 429 | `rate_limited` | 超过 Key 的每分钟上限；带 `Retry-After` |
| 500 | `internal_error` | 服务端未预期错误 |
| 502 | `retrieval_failed` | 检索整体失败 |
| 502 | `answer_failed` | 生成端点失败或输出不可用 |
| 503 | `answer_unavailable` | 没有可用生成模型，或问答接口被关闭 |
| 503 | `configuration_error` | 服务端配置缺失（例如签名 pepper 未配置） |
| 503 | `agent_key_store_unavailable` | Key 存储不可用（数据库未初始化） |

**错误响应头：**

| 响应头 | 出现条件 | 说明 |
|---|---|---|
| `X-Request-Id` | 所有响应 | 本次请求的链路 ID（与请求头同名）；报障时请提供 |
| `WWW-Authenticate: Bearer` | 401 | 表示应使用 Bearer 认证 |
| `Retry-After` | 429 | 建议等待的秒数 |

### 6.3 请求编码

- 请求体使用 UTF-8 JSON。
- `POST` 请求必须带 `Content-Type: application/json`；缺少时可能返回 `422 validation_failed`。
- `POST` 请求体只接受文档中声明的字段；多传字段会返回 422，不会被静默忽略。

### 6.4 超时、重试与幂等

- 所有接口都是**只读**或“只读 + 生成”，不会修改知识库或工作流数据；`POST /query` 只执行已发布快照。
- `GET` 请求天然可重试；`POST /search` 可安全重试；`POST /answer` / `POST /query` 重试会产生额外的模型调用与 token 消耗。
- 建议策略：
  - `429`：按 `Retry-After` 等待，再加指数退避；
  - `502` / `503`：指数退避后重试，最多 2–3 次；持续失败请报障；
  - 其他 4xx：不要重试，按 `code` 修正请求或权限；
  - 网络超时：先确认服务端是否已处理完成，再决定是否重试问答。
- 问答接口的服务端生成超时默认 120 秒（部署可调），客户端超时应大于该值；前置网关的读超时也必须大于它。

### 6.5 追踪与审计

- 所有响应都带 `X-Request-Id`（与请求头同名，合法的客户端值会原样回显）；服务端日志可按该 ID 检索。
- 默认审计日志只记录查询长度，不记录原始查询文本（部署可开启原文记录）。
- 控制台「密钥管理」会展示每个 Key 的最近使用时间与调用量，便于配额与异常排查。

## 7. 配额与调用约束

| 项 | 默认值 | 说明 |
|---|---|---|
| `query` / `question` 长度 | 1–2000 字符 | 超长返回 422 |
| `top_k` | 默认 8，最大 20 | 上限由部署配置 `RKB_AGENT_MAX_TOP_K` 决定 |
| 单次可访问知识库数量 | 50 | 由 `RKB_AGENT_MAX_KBS` 决定；超限时显式传 `knowledge_base_ids` |
| `knowledge_base_ids` 元素数 | 50 | 超过部署上限返回 422 |
| 每个 Key 的限流 | 60 次/分钟 | 由 Key 的「每分钟上限」决定；`0` = 不限制 |
| 问答生成超时 | 120 秒 | 由 `RKB_AGENT_ANSWER_TIMEOUT` 决定 |
| 工作流执行超时 | 120 秒 | `/query` 的生成超时；网关读超时需 ≥ 300 秒 |
| 工作流问题长度 | 1–2000 字符 | 可用 `kwargs.question_length_limit` 再收紧 |
| 检索片段长度 | 2000 字符 | 超长片段会被截断 |
| 问答上下文预算 | 12000 字符 | 超出时按来源顺序截断，`citations[].text` 同步截断 |
| 限流窗口 | 60 秒滑动窗口 | 进程内实现；多副本部署需要共享限流存储 |

> 以上默认值可能随部署调整；接入前请向平台管理员确认实际配额。

## 8. 部署侧配置与状态

控制台「远程接入 → 接入方法 → 服务与鉴权配置」展示当前部署的实时状态。外部集成方在排障时可以先确认这些状态：

| 配置项 | 含义 | 不可用时的表现 |
|---|---|---|
| `RKB_AGENT_API_ENABLED` | Agent 接口总开关 | 关闭时 `/agent/*` 与 `/mcp` 返回 `404 not_found` |
| `RKB_AGENT_REST_ENABLED` | REST 子接口开关 | 关闭时 `/agent/*`（含 `/agent/query`）返回 `404` |
| `RKB_AGENT_KEY_PEPPER` | Key 哈希使用的服务端签名 pepper | 未配置时返回 `503 configuration_error` |
| Key 存储表 | 存放 Key 与调用计量的数据库表 | 不可用时返回 `503 agent_key_store_unavailable` |
| `AUTH_MODE` | 控制台与原生 REST 的鉴权模式（`none` / `local` / `gateway`） | 不影响 Agent API Key 校验 |

以上配置由部署方维护；外部集成方只需确认「Agent 接口」「REST」「签名 pepper」「密钥」均为可用状态。

## 9. 接入检查清单

- [ ] 已从平台管理员获取基础地址，并确认使用 HTTPS。
- [ ] 已创建 Agent API Key，并确认 Key 的 Scope 覆盖要调用的接口。
- [ ] 已确认 Key 的知识库白名单符合预期（留空 = 全部文档库）。
- [ ] 已确认 Key 的每分钟上限与过期时间满足业务需要。
- [ ] 客户端每个请求都携带 `Authorization: Bearer` 或 `X-API-Key`。
- [ ] 已按 `code` 而不是 `detail`/`title` 处理错误。
- [ ] 已为问答接口设置大于服务端 120 秒的客户端超时。
- [ ] 已在网关/反向代理上放行 `Authorization` 头，并配置足够的读超时。
- [ ] 已确认日志中不会打印完整 Key。
- [ ] 已准备 Key 轮换与停用预案。

## 10. 常见问题

| 症状 | 排查方向 |
|---|---|
| 一直 401，但 Key 明明存在 | Key 已停用/过期；或复制时截断了；或服务端 pepper 与创建 Key 时不一致 |
| 401 `API key is disabled` | Key 已被停用，请在控制台启用或换用其他 Key |
| 401 `API key has expired` | Key 已过期，请创建新 Key 或调整过期时间 |
| 403 `forbidden_scope` | Key 没有对应 Scope；按错误体 `required_scope` 补齐 |
| 403 `knowledge_base_forbidden` | 显式传了不在白名单的 ID；调整 `knowledge_base_ids` 或修改 Key 白名单 |
| 404 `knowledge_base_not_found` | ID 写错，或该 ID 是图谱知识库（Agent API 不覆盖图谱库） |
| 400 `invalid_request`（too many accessible knowledge bases） | 可访问文档库超过部署上限；显式传 `knowledge_base_ids` |
| 400 `no_accessible_knowledge_bases` | 该 Key 没有任何可访问的文档库；检查白名单与知识库状态 |
| 422 `validation_failed` | 参数类型/长度/上限不合法，或请求体多传了未声明字段；查看 `errors[]` |
| 429 `rate_limited` | 触发每分钟上限；按 `Retry-After` 退避，或让管理员调高该 Key 的限流 |
| 502 `retrieval_failed` | 检索整体失败；确认知识库索引与搜索引擎状态，稍后重试 |
| 502 `answer_failed` | 生成端点不可用、鉴权失败或输出被截断；请管理员检查模型注册与上游服务 |
| 503 `answer_unavailable` | 没有可用生成模型，或问答接口被关闭；改用 `/search` 或联系管理员 |
| 503 `configuration_error` | 服务端未配置签名 pepper；属于部署问题，请联系管理员 |
| 503 `agent_key_store_unavailable` | Key 存储不可用，通常是数据库未初始化；请联系管理员 |
| 调用 `/query` 返回 403 `forbidden_scope` | Key 缺少 `workflow:run`；`workflow:read` 只能列工作流，不能执行 |
| 调用 `/query` 返回 404 `published_workflow_not_found` | `workflow_id` 不存在或尚未发布；先发布工作流，或改用 `publishType=1/2` 的 ID |
| 调用 `/query` 返回 422 `validation_failed` | 没有显式传 `workflow_id`，或缺少 `question` / `conversation_id` |
| 调用 `/query` 返回 403 `knowledge_base_forbidden` | 工作流发布快照绑定了 Key 白名单之外的知识库；调整白名单或换 Key |
| 检索结果为空但 HTTP 200 | 查询没有命中；确认知识库 `status`、索引是否就绪，或放宽 `score_threshold` |
| `degraded=true` 且有 `keyword_path_failed` | 关键词路不可用，但向量结果仍可用；可继续使用或联系管理员修复索引 |
| 回答很慢 | 默认 LLM 可能是推理模型；请管理员设置更快的回答模型或关闭推理，或改用 `/search` 自行生成 |

## 附录 A：curl 速查

```bash
export BASE="https://rag.example.com/api/co-knowledge/v1/agent"
export KNOWLEDGE_STUDIO_KEY="ragk_1a2b3c4d_..."

# 列知识库
curl -sS "$BASE/knowledge-bases" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY"

# 知识库详情
curl -sS "$BASE/knowledge-bases/0123456789abcdef0123456789abcdef" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY"

# 检索
curl -sS "$BASE/search" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"your question","top_k":5}'

# 问答
curl -sS "$BASE/answer" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":"your question","top_k":8}'

# 工作流列表（只读）
curl -sS "$BASE/workflows?page=1&size=100&publishType=1" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY"

# 执行已发布工作流（需要 workflow:run）
curl -sS "$BASE/query" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":"your question","conversation_id":"d-001","workflow_id":"RAG_Workflow_1a2b"}'

# OpenAPI 契约（无需 Key）
curl -sS "$BASE/openapi.json"
```

## 附录 B：最小接入代码（Python）

```python
import os

import requests

BASE = os.environ["KNOWLEDGE_STUDIO_BASE"].rstrip("/")
KEY = os.environ["KNOWLEDGE_STUDIO_KEY"]
HEADERS = {"Authorization": f"Bearer {KEY}"}


def list_knowledge_bases() -> list[dict]:
    response = requests.get(f"{BASE}/knowledge-bases", headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def search(query: str, top_k: int = 5) -> dict:
    response = requests.post(
        f"{BASE}/search",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"query": query, "top_k": top_k},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def answer(question: str, top_k: int = 8) -> dict:
    response = requests.post(
        f"{BASE}/answer",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"question": question, "top_k": top_k},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()
```

> 生产代码请根据 `code` 处理错误、记录 `X-Request-Id`，并为 429/502/503 实现退避重试。
