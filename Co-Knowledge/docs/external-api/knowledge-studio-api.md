<!-- doc-title: Knowledge Studio 对外接口文档（集成面） -->
<!-- doc-version: 2.3.0 -->

# Knowledge Studio 对外接口文档（集成面）

## 文档信息

| 项 | 值 |
|---|---|
| 文档名称 | Knowledge Studio 对外接口文档（集成面） |
| 契约版本 | 2.3.0 |
| 文档版本 | 2.3.0（与契约对齐） |
| 更新日期 | 当前版本 |
| 适用产品 | Knowledge Studio |
| 读者 | 外部集成方、Agent 平台、前端与后端开发者 |
| 接口前缀 | `/api/co-knowledge/v1` |
| 机器可读契约 | Agent 接口提供 OpenAPI 3.0.2；其余接口以本文为准 |

> 本文只覆盖**集成面**：知识库只读、检索、问答、Agent REST 与 MCP，以及 **Agent 工作流的查询与执行**（第 8.6 / 8.9 / 9.2 节）。
> 建库、上传、修改、删除、算子、工作流的创建/画布编辑/发布/删除、模型注册、密钥管理等管理接口不在本文范围内；这些操作请在 Knowledge Studio 控制台完成。
> 如果集成方需要完整管理能力，请由平台管理员在 Knowledge Studio 控制台操作，或另行申请管理接口文档。


## 1. 概述

Knowledge Studio 提供从文档知识库到检索增强问答的完整能力。对外集成通常只需要三类操作：

1. **发现知识库**：读取知识库、目录、文档、切片与图谱内容。
2. **检索**：按向量、关键词或混合方式取回原文片段；图谱库还支持基于种子实体的子图检索。
3. **问答**：基于已发布工作流的编排问答，或基于 Agent API 的引用式问答。

### 1.1 接入方式对比

| 方式 | 入口 | 认证 | 适合场景 | 主要能力 |
|---|---|---|---|---|
| Agent REST | `/agent/*` | Agent API Key | 机器对机器、后端服务、Agent 平台 | 列库、检索、引用式问答、工作流查询 |
| MCP | `/mcp` | Agent API Key | Claude Code 等支持 MCP 的客户端 | 3 个只读工具 + 1 个工作流查询工具 |
| Agent 编排问答 | `/agent/query` | Agent API Key（`workflow:run`） | 机器对机器执行已发布工作流 | JSON 或 SSE；改写 → 检索 → 重排 → 生成 |
| 原生编排问答 | `/query` | 浏览器会话 / 网关令牌 / 无鉴权（视部署） | 聊天式界面 | JSON 或 SSE；与 `/agent/query` 同一套编排 |
| 原生 REST | `/knowledge-bases/*`、`/retrieval*` | 浏览器会话 / 网关令牌 / 无鉴权（视部署） | 浏览器应用、内网系统、需要读原文 | 知识库只读、检索、图谱检索 |

**选择建议：**

- **机器对机器**优先用 Agent REST 或 MCP。它们只需要 API Key，错误语义清晰，且不会暴露管理面。
- **需要按已发布工作流执行编排问答**时使用 `POST /agent/query`：带 `workflow:run` 的
  Agent Key 即可，这也是「`/agent/workflows` 发现 → `/agent/query` 执行」的闭环。
  浏览器「对话测试」页仍走原生 `/query`。
- **需要浏览知识库原文**（目录、文档、切片）时，使用原生 REST 的知识库只读接口；这类接口跟随部署的 `AUTH_MODE`。
- **需要流式回答**时使用 `POST /agent/query`（Agent Key）或 `POST /query`（会话/网关）的 SSE 模式。
- **只需要片段、不需要生成答案**时使用 `/agent/search` 或 `POST /retrieval`。

### 1.2 首次接入需要准备什么

| 项目 | 说明 | 从哪里获取 |
|---|---|---|
| 服务地址 | 例如 `https://rag.example.com` | 部署方 |
| API 前缀 | 固定 `/api/co-knowledge/v1` | 本文 |
| Agent API Key | 形如 `ragk_1a2b3c4d_...`，只在创建时显示一次 | 平台管理员在「远程接入 → 密钥管理」创建 |
| 知识库 ID | 32 位十六进制字符串，例如 `0123456789abcdef0123456789abcdef` | `/agent/knowledge-bases` 或 `/knowledge-bases` |
| 工作流 ID | 已发布工作流的 ID，例如 `RAG_Workflow_xxxx` | 由部署方在控制台创建/发布，或通过 `/agent/workflows` 查询。`/query` 只接受**已发布**工作流 |
| 登录账号 | 仅 `AUTH_MODE=local` 且走原生 REST 时需要 | 平台管理员 |

> 生产环境务必使用 HTTPS。Agent Key 是 Bearer 凭据，走 HTTP 时是明文传输。


## 2. 快速开始

以下示例统一使用：

```bash
export BASE="https://rag.example.com/api/co-knowledge/v1"
```

### 2.1 Agent 最小链路（推荐）

**第一步：列可访问的知识库**

```bash
curl -sS "$BASE/agent/knowledge-bases" \
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

**第二步：检索片段**

```bash
curl -sS "$BASE/agent/search" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何配置检索编排？",
    "knowledge_base_ids": ["0123456789abcdef0123456789abcdef"],
    "mode": "auto",
    "top_k": 5
  }'
```

**第三步：基于片段生成带引用的答案**

```bash
curl -sS "$BASE/agent/answer" \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何配置检索编排？",
    "knowledge_base_ids": ["0123456789abcdef0123456789abcdef"],
    "top_k": 5
  }'
```

### 2.2 原生 REST 最小链路（`AUTH_MODE=local`）

**第一步：登录，保存会话 Cookie**

```bash
curl -sS -c cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"integration-user","password":"********"}' \
  "$BASE/auth/login"
```

**第二步：检索**

带会话 Cookie 的 `POST` 必须同时带 `Origin`（或 `Referer`），且 host 必须与请求的 `Host` 一致：

```bash
curl -sS -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何配置检索编排？",
    "type": 0,
    "bases": [{
      "baseList": ["doc_0123456789abcdef0123456789abcdef"],
      "priority": 1,
      "top_k": 5,
      "score_threshold": 0.0
    }]
  }' \
  "$BASE/retrieval"
```

**第三步：编排问答**

```bash
curl -sS -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何配置检索编排？",
    "conversation_id": "d-20261026-001",
    "workflow_id": "RAG_Workflow_xxxx",
    "include_retrieval": true
  }' \
  "$BASE/query"
```

### 2.3 流式问答

```bash
curl -sS -N -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何配置检索编排？",
    "conversation_id": "d-20261026-002",
    "workflow_id": "RAG_Workflow_xxxx",
    "stream": true,
    "include_retrieval": true
  }' \
  "$BASE/query"
```

返回是标准 SSE，详见 7.3。


## 3. 通用约定

### 3.1 地址与版本

- 唯一对外前缀：`/api/co-knowledge/v1`。
- 只使用该前缀下的路径。其他 `/api/...` 路径在部署中可能被前端静态资源接管，返回 `200` 的 HTML 而不是 `404`。
- 当前契约版本：`2.3.0`。版本号随契约发布，新增字段/端点属于向后兼容变更；删除或改语义才升主版本。
- Agent 子接口另有 OpenAPI 版本 `1.4.0`，见 8.8。

### 3.2 编码与媒体类型

| 场景 | 约定 |
|---|---|
| 字符编码 | UTF-8 |
| JSON 请求 | 必须显式 `Content-Type: application/json` |
| JSON 响应 | `application/json; charset=utf-8` |
| 错误响应 | `application/problem+json; charset=utf-8` |
| 文件下载 | `application/octet-stream` |
| SSE | `text/event-stream; charset=utf-8` |
| 健康检查 | `text/plain; charset=utf-8`，正文固定为 `ok` |

请求体是 JSON 时应显式设置 `Content-Type: application/json`：

- 原生 REST 在缺少或使用不支持的媒体类型时返回 `415 unsupported_media_type`；
- Agent 端点由 FastAPI 直接绑定，缺少 `Content-Type` 时可能返回 `422 validation_failed`（错误体里 `loc` 指向 `body`）。

### 3.3 鉴权

鉴权方式由部署的 `AUTH_MODE` 决定。集成前先向部署方确认。

| `AUTH_MODE` | 原生 REST（`/knowledge-bases`、`/retrieval`、`/query`） | Agent REST / MCP（`/agent/*`、`/mcp`） |
|---|---|---|
| `none` | 不做应用层鉴权，仅靠网络隔离 | 仍要求 Agent API Key |
| `local` | 要求 `ragstudio_session` HttpOnly Cookie | 绕过浏览器会话，使用 Agent API Key |
| `gateway` | 要求前置网关注入 `X-Auth-Value` / `X-Auth-Token` / `Authorization` 任一非空 | 使用 Agent API Key |

`AUTH_MODE=local` 下的公开端点：`GET /health`、`GET /auth/status`、`POST /auth/login`、`POST /auth/logout`。`/agent/*` 与 `/mcp` 不受浏览器会话约束，但必须带 Agent API Key。

**Agent API Key：**

```http
Authorization: Bearer ragk_1a2b3c4d_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

也接受：

```http
X-API-Key: ragk_1a2b3c4d_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Key 的格式为 `ragk_<8 位前缀>_<43 位密钥>`。服务端只存哈希，**明文只在创建时返回一次**。Key 可以配置：

- 权限范围：`kb:list`、`kb:search`、`kb:answer`、`workflow:read`、`workflow:run`；
- 可访问知识库白名单：为空表示全部可访问文档库；
- 每分钟请求上限；
- 过期时间；
- 启用/停用。

**Agent Key 不能用于** `/retrieval`、`/query`、`/workflows` 管理面或知识库只读接口。机器访问知识库问答请使用 `/agent/search` 与 `/agent/answer`；需要执行**已发布工作流**时，用带 `workflow:run` 的 Key 调用 `POST /agent/query`（第 8.9 节）；只需查询工作流时使用 `/agent/workflows`（第 8.6 节）。工作流的创建、画布编排与发布在控制台完成。

> `POST /agent/query` 的 Agent Key 调用，Key 的 `kbIds` 白名单仍然生效：服务端会校验工作流发布快照绑定的文档/结构化知识库都在白名单内，否则返回 `403 knowledge_base_forbidden`。图谱知识库不在 Agent Key 白名单的下拉范围内，运行含图谱检索的工作流由 `workflow:run` scope 授权。

**会话 Cookie：**

| 属性 | 值 |
|---|---|
| 名称 | `ragstudio_session` |
| HttpOnly | 是 |
| SameSite | `Lax` |
| Path | `/` |
| Secure | 部署配置 `auto` 时按请求协议自动加 |
| 默认有效期 | 12 小时（可配置 60 秒–30 天） |

带会话 Cookie 的 `POST` / `PUT` / `PATCH` / `DELETE` 会做 CSRF 来源校验：`Origin` 或 `Referer` 的 host 必须等于请求的 `Host`。脚本调用时显式带 `Origin` 最稳妥。

### 3.4 请求头

| 请求头 | 必填 | 说明 |
|---|---|---|
| `Authorization` | Agent 必填 | `Bearer <Agent API Key>` |
| `X-API-Key` | 可选 | Agent Key 的另一种传法；与 `Authorization` 二选一 |
| `Content-Type` | JSON 请求必填 | `application/json` |
| `Accept-Language` | 可选 | 原生 REST 错误 `detail` 的语言；Agent 的 `detail` 为英文固定文案。见下方说明 |
| `X-Request-Id` | 可选 | 客户端链路 ID，`[A-Za-z0-9._-]` 且 1–64 字符；合法则原样沿用，缺失或不合法时由服务端生成。所有端点同名回显 |
| `Origin` / `Referer` | 会话非安全方法必填 | CSRF 校验；host 必须与 `Host` 一致 |

**`Accept-Language` 的实际行为（原生 REST）：**

| 取值 | `detail` 语言 |
|---|---|
| `zh-CN` | 中文 |
| `zh-CN,en;q=0.9` | 中文 |
| `*` | 中文 |
| 不带 | 英文 |
| `zh` / `zh-TW` / `en-US` / 其他 | 英文 |

需要稳定中文提示时，请显式发送 `Accept-Language: zh-CN`。

**响应头：**

| 响应头 | 说明 |
|---|---|
| `X-Request-Id` | 本次请求的链路 ID，**所有端点**都返回（与请求头同名，见 3.10）。客户端应记录并在报障时提供 |
| `Retry-After` | 仅 `429` 时出现，单位秒 |
| `WWW-Authenticate` | 仅 Agent 鉴权失败时出现，值为 `Bearer` |

### 3.5 成功响应

成功响应**没有** `{code, bo, other}` 信封，body 就是资源本身：

| 形态 | 示例 |
|---|---|
| 单资源 | `{...}` |
| 集合 | `[...]` |
| 分页 | `{"items":[...],"total":123,"page":1,"pageSize":20}` |
| 无内容 | `204 No Content` |
| 文件 | `application/octet-stream` |
| 流式 | `text/event-stream` |

### 3.6 分页、排序与筛选

**分页：**

| 端点 | 请求参数 | 默认 | 上限 |
|---|---|---|---|
| `GET /knowledge-bases` | `page`、`size` | `page=1`、`size=10` | `page` 1–10000，`size` 1–500 |
| `GET /knowledge-bases/{kb}/documents` | `page`、`size` | `page=1`、`size=50` | `size` ≤ 100 |
| `GET /knowledge-bases/{kb}/chunks` | `page`、`size` | `page=1`、`size=20` | 服务端未强制上限，建议 ≤ 100 |
| `GET /knowledge-bases/{kb}/documents/{doc}/chunks` | `page`、`size` | `page=1`、`size=10` | 服务端未强制上限，建议 ≤ 100 |

分页响应统一为：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "pageSize": 20
}
```

**排序（仅知识库列表）：**

```text
?sort=name:asc&sort=createdDate:desc
```

也支持 `?sort=name:asc,createdDate:desc`。可用 key：`id`、`name`、`createdDate`、`embeddingModel`、`createdBy`。缺省按 `createdDate` 倒序。

**筛选（仅知识库列表）：**

| 参数 | 说明 |
|---|---|
| `keyword` | 按知识库**名称**模糊匹配（不区分大小写） |
| `categories` | 分类过滤，逗号分隔。`1` 文档知识库，`10` 图谱知识库 |
| `embeddingModel` | 按 embedding 注册名过滤 |

### 3.7 错误模型

原生 REST 与 Agent REST 的错误使用 RFC 9457 `application/problem+json`，并返回真实 HTTP 状态码；MCP 工具错误使用 MCP 的 `isError` 语义（见 9.4）。

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
X-Request-Id: 4f2c9a1b7d8e4c60

{
  "type": "urn:ragstudio:problem:knowledge_base_not_found",
  "title": "Knowledge base not found",
  "status": 404,
  "detail": "Knowledge base not exist",
  "instance": "/api/co-knowledge/v1/knowledge-bases/nope",
  "code": "knowledge_base_not_found"
}
```

| 字段 | 说明 |
|---|---|
| `type` | 稳定 URN，格式 `urn:ragstudio:problem:<code>` |
| `title` | 稳定英文标题，不随语言变化 |
| `status` | HTTP 状态码，与响应行一致 |
| `detail` | 可读原因。原生 REST 按 `Accept-Language` 本地化；Agent 为英文固定文案。**不要**用它做程序分支 |
| `instance` | 请求路径 |
| `code` | 稳定机器码，客户端应按它分支 |
| `errors` | 可选。参数校验明细，见下 |
| 其他扩展字段 | 可选，例如 `knowledge_base_id`、`required_scope`、`retry_after_seconds` |

参数校验失败时通常附带 `errors`：

```json
{
  "type": "urn:ragstudio:problem:validation_failed",
  "title": "Validation failed",
  "status": 422,
  "detail": "Request validation failed",
  "code": "validation_failed",
  "instance": "/api/co-knowledge/v1/agent/search",
  "errors": [
    {"loc": ["body", "top_k"], "msg": "Value error, top_k must be <= 20", "type": "value_error"}
  ]
}
```

> `errors[]` 的文案字段在不同端点可能是 `message` 或 `msg`，这是历史差异；客户端不应依赖该字段的键名，应以 `code`/`status` 为准。

**常见状态码：**

| HTTP | 含义 | 典型 `code` |
|---|---|---|
| 400 | 请求格式错误或业务上无法处理 | `malformed_request`、`bad_request`、`invalid_request`、`no_accessible_knowledge_bases` |
| 401 | 未认证或凭据无效 | `unauthorized`、`session_expired`、`invalid_credentials` |
| 403 | 无权限、作用域不足或 CSRF 失败 | `permission_denied`、`forbidden_scope`、`knowledge_base_forbidden`、`csrf_rejected` |
| 404 | 资源不存在 | `knowledge_base_not_found`、`directory_not_found`、`file_not_found`、`not_found`、`published_workflow_not_found` |
| 409 | 状态冲突 | `conflict`、`auth_not_enabled` |
| 413 | 请求体过大 | `payload_too_large` |
| 415 | 媒体类型不支持 | `unsupported_media_type` |
| 422 | 语义校验失败 | `validation_failed`、`graph_query_not_ready`、`graph_query_failed` |
| 429 | 触发限流 | `rate_limited`、`login_rate_limited` |
| 500 | 服务内部错误 | `internal_error` |
| 502 | 上游依赖失败 | `retrieval_failed`、`answer_failed`、`upstream_unavailable`、`llm_unavailable` |
| 503 | 依赖未配置或暂不可用 | `answer_unavailable`、`configuration_error`、`agent_key_store_unavailable`、`knowledge_base_not_imported`、`no_llm_available` |

### 3.8 限流与配额

| 对象 | 限制 | 超限响应 |
|---|---|---|
| `POST /retrieval/graph` | 每客户端 IP 300 次/秒（1 秒窗口，进程内计数） | `429 rate_limited`，`Retry-After: 1` |
| Agent API Key | 每个 Key 独立配置，默认 60 次/分钟，可设 0 表示不限 | `429 rate_limited`，带 `Retry-After` 与 `retry_after_seconds` |
| 登录 | 同一账号+IP 15 分钟内 5 次失败；同一 IP 15 分钟内 20 次失败 | `429 login_rate_limited`，带 `Retry-After` |
| 其他端点 | 应用层未统一限流，建议在网关侧限流 | — |

> 限流计数在服务进程内。Knowledge Studio 当前按单副本设计；多副本部署需要网关侧共享限流。

### 3.9 超时、重试与幂等

| 场景 | 建议 |
|---|---|
| 普通读接口 | 客户端读超时 ≥ 30 秒 |
| `/agent/search` | 读超时 ≥ 60 秒 |
| `/agent/answer` | 读超时 ≥ 180 秒（生成默认超时 120 秒，网关通常配 300 秒） |
| `/query`（非流式） | 读超时 ≥ 300 秒 |
| `/query`（SSE） | 连接超时 ≥ 300 秒，并处理 15 秒心跳注释 |
| `POST /retrieval/graph` | 读超时 ≥ 120 秒 |

- `GET`、`POST /agent/search`、`POST /retrieval`、`POST /retrieval/graph` 是只读语义，可安全重试；建议指数退避。
- `POST /query` 会写入对话历史与追踪记录；重试前请确认上一次未成功，或换一个新的 `conversation_id`。
- `POST /agent/answer` 会消耗生成模型资源；重试前先确认上一次是否已成功。
- `429` 时按 `Retry-After` 等待；不要立即重试。
- 网络错误或 `502`/`503` 可以重试；`400`/`401`/`403`/`404`/`422` 通常不应原样重试。

### 3.10 追踪与日志

所有 HTTP 端点统一使用 `X-Request-Id`，**请求头与响应头同名**：

| 场景 | 链路 ID 行为 |
|---|---|
| 客户端发送合法的 `X-Request-Id` | 原样沿用，并在响应头同名回显 |
| 未发送，或值不合法（字符集 `[A-Za-z0-9._-]`、长度 1–64） | **丢弃客户端值**，由服务端生成 16 位十六进制 ID |
| 全部端点（含 `/knowledge-bases/*`、`/retrieval`、`/auth/*`、`/health`、`/agent/*`，以及 404/422/429 等错误响应） | 响应头都带 `X-Request-Id` |
| `/mcp` | HTTP 响应头同样回显；工具结果 JSON 里的 `trace_id` 是同一个值 |

服务端日志默认不记录问题原文；排障时优先提供响应头里的 `X-Request-Id`。


## 4. 系统

### 4.1 健康检查

```http
GET /health
```

- 认证：公开，不需要会话或 API Key。
- 响应：`200 OK`，`Content-Type: text/plain`，正文 `ok`。
- 用途：存活探针。不要用它判断知识库或模型是否可用。

```bash
curl -sS "$BASE/health"
# ok
```


## 5. 知识库只读

> 本节接口跟随部署的 `AUTH_MODE`，不使用 Agent API Key。
> 响应中可能包含 `pkId`、`esIndexName`、`tableName`、`schemaObj` 等 UI/实现字段；它们**不属于对外契约**，可能随版本变化，请忽略。

### 5.1 知识库列表

```http
GET /knowledge-bases
```

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `page` | integer | 1 | 页码，1–10000 |
| `size` | integer | 10 | 每页条数，1–500 |
| `keyword` | string | — | 按名称模糊匹配 |
| `categories` | string | — | 逗号分隔。`1` 文档库，`10` 图谱库；省略时返回全部分类 |
| `embeddingModel` | string | — | embedding 注册名 |
| `sort` | string | `createdDate:desc` | 排序，见 3.6 |

**响应：** 分页对象 `{items,total,page,pageSize}`。

```json
{
  "items": [
    {
      "id": "0123456789abcdef0123456789abcdef",
      "name": "product-manual",
      "description": "产品手册",
      "type": "document",
      "embeddingModel": "Qwen3-Embedding-0.6B",
      "currentFileCount": 16,
      "fileCountLimit": 5000,
      "createdBy": "creator",
      "createdDate": "2024-01-01 00:00:00",
      "lastUpdatedBy": "creator",
      "lastUpdatedDate": "2024-01-01 00:00:00",
      "status": 0,
      "failReason": "",
      "processDetailInfo": ""
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 10
}
```

**稳定字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 知识库 ID |
| `name` | string | 名称 |
| `description` | string \| null | 描述 |
| `type` | string | 子类型标识（当前固定 `document`）。**不能**用它区分文档库/图谱库，请用 `categories` |
| `embeddingModel` | string | embedding 注册名 |
| `currentFileCount` | integer | 当前文件数 |
| `fileCountLimit` | integer | 文件数上限 |
| `createdBy` | string \| null | 创建人 |
| `createdDate` | string | 创建时间，`YYYY-MM-DD HH:mm:ss`，服务端本地时间 |
| `lastUpdatedBy` | string \| null | 最后修改人 |
| `lastUpdatedDate` | string \| null | 最后修改时间，格式同上 |
| `status` | integer | 状态码，见下表（原生 REST 为整数；Agent API 为字符串，见 8.2） |
| `failReason` | string | 失败原因（可能为空串） |
| `processDetailInfo` | string | 处理进度描述（可能为空串） |

**`status` 取值：**

| 值 | 含义 |
|---|---|
| `0` | 已创建（文档库通常直接可用；图谱库需发布后才可用于工作流） |
| `1` | 解析中 |
| `2` | 切分中 |
| `3` | 生成中 |
| `4` | 入库中 |
| `5` | 待发布 |
| `6` | 发布中 |
| `7` | 已发布 |
| `8` | 已发布后有改动，待再次发布 |
| `101` | 解析失败 |
| `102` | 切分失败 |
| `103` | 生成失败 |
| `104` | 入库失败 |
| `106` | 发布失败 |

> 文档库通常以 `0` 表示可用；图谱库在 `5`（已创建）之后还需要发布才能被工作流使用。检索/问答前请确认知识库状态与索引已就绪。

### 5.2 知识库详情

```http
GET /knowledge-bases/{kb_id}
```

**响应：** 单个知识库对象，字段同 5.1，并额外包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `props` | object | 建库属性，通常含 `embeddingModel`、`splitMethod`、`regex` |

```json
{
  "id": "0123456789abcdef0123456789abcdef",
  "name": "product-manual",
  "description": "产品手册",
  "type": "document",
  "props": {
    "embeddingModel": "Qwen3-Embedding-0.6B",
    "splitMethod": "comprehensiveSplitter",
    "regex": "\n\n"
  },
  "embeddingModel": "Qwen3-Embedding-0.6B",
  "currentFileCount": 16,
  "fileCountLimit": 5000,
  "status": 0,
  "createdDate": "2024-01-01 00:00:00",
  "lastUpdatedDate": "2024-01-01 00:00:00"
}
```

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 404 | `knowledge_base_not_found` | 知识库不存在 |

### 5.3 目录

#### 5.3.1 目录/文档节点列表

```http
GET /knowledge-bases/{kb_id}/directories
```

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `parentId` | string | — | 父目录 ID。省略/空串时返回库内全部有效节点；给出时返回该目录的**递归后代**（不含自身） |
| `type` | string | — | `folder` 或 `file`；用于过滤节点类型 |
| `sort` | boolean | false | `true` 时文件夹在前、再按标题排序 |

**响应：** 数组。

```json
[
  {
    "id": "11111111111111111111111111111111",
    "kbaseId": "0123456789abcdef0123456789abcdef",
    "title": "overview.md",
    "parentId": "22222222222222222222222222222222",
    "parentPath": "0",
    "canSpread": "N",
    "type": "file",
    "fileSize": 5671,
    "status": 1,
    "kType": null,
    "errorMsg": null,
    "childList": null,
    "props": {"file_size": "5671", "KType": "outer-document"},
    "idChain": null
  },
  {
    "id": "22222222222222222222222222222222",
    "kbaseId": "0123456789abcdef0123456789abcdef",
    "title": "Default",
    "parentId": null,
    "parentPath": "0",
    "canSpread": "N",
    "type": "folder",
    "fileSize": 0,
    "status": null,
    "childList": [
      {
        "id": "11111111111111111111111111111111",
        "title": "overview.md",
        "parentId": "22222222222222222222222222222222",
        "type": "file"
      }
    ],
    "props": {}
  }
]
```

**节点字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 节点 ID（目录或文件） |
| `kbaseId` | string | 所属知识库 |
| `title` | string | 目录名或文件名 |
| `parentId` | string \| null | 父目录 ID |
| `parentPath` | string | 父路径串 |
| `type` | string | `folder` 或 `file` |
| `canSpread` | string | `Y`/`N`，是否有**文件夹**子节点 |
| `fileSize` | integer \| null | 文件字节数；目录通常为 0 或 null |
| `status` | integer \| null | 文件状态：`1` 可用，`2` 失败；目录为 null；其他值为处理中间态 |
| `kType` | string \| null | 文件类型（如 `outer-document`）；目录为 null |
| `errorMsg` | string \| null | 仅失败文件有本地化错误信息 |
| `childList` | array \| null | 列表内按 `parentId` 组装的子节点视图 |
| `props` | object | 文件属性，通常含 `file_size`、`KType` |
| `fileFrom` | string \| null | 来源标识 |
| `failReason` | string \| null | 失败原因原文 |
| `idChain` | string \| null | 祖先链；本接口通常为 null，文档列表接口会填 |

> **去重提示：** 本接口返回的数组同时包含顶层节点和 `childList` 中的嵌套引用；同一节点可能在两处出现。客户端应按 `id` 去重，不要假设顶层数组只含根节点。
>
> 需要“直接子节点”时，请调用本接口并筛选 `parentId == 目标目录 ID` 的节点；`parentId` 参数本身返回的是**递归后代**。

#### 5.3.2 目录详情

```http
GET /knowledge-bases/{kb_id}/directories/{directory_id}
```

**响应：** 单个节点对象，字段同 5.3.1，`idChain` 通常为 null。

**注意：** 如果知识库存在但目录 ID 不存在，本接口返回 **HTTP 200 + 全字段 null 的对象**，而不是 404：

```json
{
  "id": null,
  "kbaseId": null,
  "title": null,
  "parentId": null,
  "type": null,
  "childList": null
}
```

客户端必须检查 `id` 是否为 null 来判断“不存在”。知识库不存在时才返回 404 `knowledge_base_not_found`。

### 5.4 文档

#### 5.4.1 整库文档分页

```http
GET /knowledge-bases/{kb_id}/documents
```

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `keyword` | string | — | 按文件名模糊匹配 |
| `page` | integer | 1 | 页码 |
| `size` | integer | 50 | 每页条数，最大 100 |

**响应：** 分页对象，`items` 为文档节点。

```json
{
  "items": [
    {
      "id": "11111111111111111111111111111111",
      "kbaseId": "0123456789abcdef0123456789abcdef",
      "title": "overview.md",
      "parentId": "22222222222222222222222222222222",
      "parentPath": "0",
      "type": "file",
      "fileSize": 5671,
      "status": 1,
      "kType": "outer-document",
      "errorMsg": null,
      "props": {"file_size": "5671", "KType": "outer-document"},
      "idChain": "0-11111111111111111111111111111111"
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 50
}
```

字段含义同 5.3.1；本接口会填充 `kType` 与 `idChain`。

#### 5.4.2 下载原文件

```http
GET /knowledge-bases/{kb_id}/documents/{document_id}/content
```

- 响应：`200 OK`，`Content-Type: application/octet-stream`，`Content-Length` 为字节数。
- 正文是上传时的原始文件字节，不做格式转换。
- **响应不包含 `Content-Disposition`**；文件名请从 5.4.1 的 `title` 获取。
- 错误：文件不存在返回 `404 file_not_found`。

```bash
curl -sS -b cookies.txt \
  -o overview.md \
  "$BASE/knowledge-bases/<KB_ID>/documents/<DOC_ID>/content"
```

#### 5.4.3 单文档切片

```http
GET /knowledge-bases/{kb_id}/documents/{document_id}/chunks
```

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `keyword` | string | — | 按切片正文模糊匹配 |
| `page` | integer | 1 | 页码 |
| `size` | integer | 10 | 每页条数 |

**响应：** 分页对象，额外带 `nameChain`。

```json
{
  "items": [
    {
      "chunkId": 204179,
      "kbaseId": "0123456789abcdef0123456789abcdef",
      "fileId": "11111111111111111111111111111111",
      "content": "切片正文……",
      "supplement": "补充/展开文本……",
      "source": "overview.md",
      "score": null,
      "rankScore": null,
      "fullScore": null
    }
  ],
  "total": 14,
  "page": 1,
  "pageSize": 10,
  "nameChain": ["Default", "overview.md"]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `chunkId` | integer | 切片 ID（本接口为整数；检索结果里可能是字符串） |
| `kbaseId` | string | 知识库 ID |
| `fileId` | string | 文件 ID |
| `content` | string | 切片正文 |
| `supplement` | string | 补充文本；可能等于 `content`，也可能是切片展开内容 |
| `source` | string | 文件名 |
| `score` / `rankScore` / `fullScore` | null | 本接口恒为 null，保留字段 |
| `nameChain` | array | `[父目录名, 文件名]`；未知时为空串 |

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 404 | `file_not_found` | 文档不存在，或传入的是目录 ID |
| 404 | `knowledge_base_not_found` | 知识库不存在 |

#### 5.4.4 全库切片

```http
GET /knowledge-bases/{kb_id}/chunks
```

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `keyword` | string | — | 按正文模糊匹配 |
| `page` | integer | 1 | 页码 |
| `size` | integer | 20 | 每页条数 |

**响应：** 分页对象，`items` 字段同 5.4.3（无 `nameChain`）。本接口返回整库切片，按切片 ID 倒序。

### 5.5 图谱库内容

#### 5.5.1 图谱库详情

```http
GET /knowledge-bases/{kb_id}/graph
```

**响应：**

```json
{
  "schemaInfo": {
    "schema_id": "General_Schema",
    "schema_name": "General_Schema",
    "schema_desc": "通用图谱模板",
    "entities": [
      {
        "entity_type": "Entity",
        "properties": [
          {"name": "entity_name", "type": "STRING", "desc": "实体名称", "is_primary": true, "is_embedding": true}
        ]
      }
    ],
    "edges": [
      {
        "edge_type": "Relation",
        "source_entity": "Entity",
        "target_entity": "Entity",
        "properties": [
          {"name": "relationship_description", "type": "STRING", "desc": "关系描述", "is_embedding": true}
        ]
      }
    ]
  },
  "data": {
    "id": "fedcba9876543210fedcba9876543210",
    "name": "product-graph",
    "type": "document",
    "embeddingModel": "Qwen3-Embedding-0.6B",
    "status": 5,
    "description": "产品知识图谱"
  },
  "fileInfo": [],
  "stats": {
    "entityCount": 128,
    "edgeCount": 256
  }
}
```

| 字段 | 说明 |
|---|---|
| `schemaInfo` | 图谱模板：实体类型、边类型、属性定义；**文档知识库为 null** |
| `data` | 知识库元数据，字段同 5.1 |
| `fileInfo` | 源文件/节点信息数组，可能为空；对文档知识库会是目录节点（`DirectoryNode`） |
| `stats` | 图谱全量统计：`entityCount` / `edgeCount` 为图存储中的物理实体/关系数，**与当前查询条件无关**；文档库、图谱尚未建表或计数失败时为 `null`（图谱已建但为空时为 `0`） |

> 该端点主要用于图谱库。对文档知识库调用不会报错，而是返回 `schemaInfo: null` 加 `fileInfo` 节点列表；不要据此判断“图谱库不存在”。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 404 | `knowledge_base_not_found` | 知识库不存在 |

#### 5.5.2 图查询

```http
POST /knowledge-bases/{kb_id}/graph/query
```

用于按实体类型、边类型、属性或子图条件读取图内容。只读，不会修改图。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query_type` | string | 是 | `entity`、`edge`、`path`、`sub_graph` |
| `filters` | array | 否 | 过滤条件数组，见下 |
| `depth` | integer | 否 | 子图深度，1–100；`sub_graph` 默认 10 |
| `direction` | string | 否 | 子图方向，默认 `both`；常用 `both` / `in` / `out` |
| `limit` | integer | 否 | 返回条数，1–1000；默认 100 |
| `offset` | integer | 否 | 偏移量，≥ 0；默认 0 |
| `cursor` | string | 否 | 游标分页；给出时优先于 `offset` |

**`filters[]` 字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `entity_type` | string[] | 实体类型过滤 |
| `edge_type` | string[] | 边类型过滤 |
| `properties` | object | 实体/边属性过滤 |
| `start_entity_type` | string[] | 子图起点实体类型 |
| `start_entity_properties` | object | 子图起点实体属性（例如 `{"entity_id":["Person_1"]}`） |
| `start_entity_rid` | string | 子图起点 RID |
| `path_entity_type` | string[] | 路径上的实体类型 |
| `path_entity_properties` | object | 路径上的实体属性 |
| `path_edge_type` | string[] | 路径上的边类型 |
| `path_edge_properties` | object | 路径上的边属性 |

> 类型类字段必须是**数组**，例如 `"entity_type": ["Person"]`；传字符串会返回 `400 malformed_request`。
> 属性过滤对象的值也可以是数组，表示“任一匹配”。

**示例：查询 Person 类型实体**

```bash
curl -sS -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d '{
    "query_type": "entity",
    "filters": [{"entity_type": ["Person"]}],
    "limit": 5
  }' \
  "$BASE/knowledge-bases/<KB_ID>/graph/query"
```

```json
{
  "entities": [
    {
      "entity_id": "Person_1",
      "entity_type": "Person",
      "entity_name": "Alice",
      "properties": {"name": "Alice", "age": 34}
    }
  ],
  "edges": [
    {
      "edge_id": "Knows_1",
      "edge_type": "Knows",
      "source_id": "Person_1",
      "target_id": "Person_2",
      "properties": {"since": ""}
    }
  ],
  "paths": [],
  "entity_num": 1,
  "edge_num": 1,
  "total": 1,
  "has_more": false,
  "offset": 0,
  "limit": 5,
  "next_cursor": null
}
```

| 字段 | 说明 |
|---|---|
| `entities` | 实体数组：`entity_id`、`entity_type`、`entity_name`、`properties` |
| `edges` | 边数组：`edge_id`、`edge_type`、`source_id`、`target_id`、`properties` |
| `paths` | 路径数组；无路径时为空数组 |
| `entity_num` | 本次返回的实体数 |
| `edge_num` | 本次返回的边数 |
| `total` | 结果总数；不同 `query_type` 语义不同，实体数/边数请以 `entity_num`/`edge_num` 为准 |
| `has_more` | 是否还有下一页。**判定为“返回条数 ≥ limit”，正好满页也为 true** |
| `offset` / `limit` | 本次分页参数 |
| `next_cursor` | 游标分页下一页游标；仅 `has_more=true` 时可能非空 |

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 404 | `knowledge_base_not_found` | 知识库不存在 |
| 422 | `validation_failed` | `query_type` 非法、过滤条件类型错误等 |
| 422 | `graph_query_not_ready` | 图谱仍在构建（状态 1–4） |
| 422 | `graph_query_failed` | 图谱构建失败（状态 101–104） |
| 500 | `internal_error` | 图存储查询失败 |


## 6. 检索

### 6.1 文档检索（向量 / 关键词）

```http
POST /retrieval
```

按知识库分组检索文档切片，支持向量路与关键词路。可跨多个知识库，并按 `priority` 做降级。

**请求体：**

```json
{
  "question": "如何配置检索编排？",
  "type": 0,
  "model": "Qwen3-Embedding-0.6B",
  "bases": [
    {
      "baseList": ["doc_0123456789abcdef0123456789abcdef"],
      "priority": 1,
      "top_k": 5,
      "score_threshold": 0.0
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 检索问题，不能为空 |
| `type` | integer | 否 | `0` 向量检索（默认），`1` 关键词检索 |
| `model` | string | 否 | embedding 注册名；向量路使用。缺省用部署默认模型 |
| `bases` | array | 是 | 检索分组，不能为空 |
| `bases[].baseList` | string[] | 是 | 检索的 base 名列表。文档库格式：`doc_<kb_id>` |
| `bases[].priority` | integer | 实际必填 | 0–10；按优先级从高到低检索。缺失会导致整次检索失败并返回空数组 |
| `bases[].top_k` | integer | 否 | 每个 base 返回条数，1–80；默认 8 |
| `bases[].score_threshold` | number | 否 | 0–1；仅向量路生效；默认 0 |

**响应：** 数组，每个 base 一项。

```json
[
  {
    "baseName": "doc_0123456789abcdef0123456789abcdef",
    "docs": [
      {
        "chunkId": "5",
        "content": "切片正文……",
        "score": 0.3731858951402778,
        "sourceDocId": null,
        "metadata": {
          "chunk_index": "",
          "source": "overview.md",
          "chunk_id": 5,
          "type": 0
        }
      }
    ]
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `baseName` | string | base 名，已去掉 `\|#\|scope` 后缀 |
| `docs[].chunkId` | string \| null | 切片序号/ID；该字段可能为 `null` 或空串 |
| `docs[].content` | string | 切片正文 |
| `docs[].score` | number | 向量路为余弦相似度（0–1）；关键词路为 ES 相关性分数（未归一化） |
| `docs[].sourceDocId` | string \| null | 文件 ID；部分知识库可能为 null |
| `docs[].metadata` | object \| null | 元数据：`chunk_index`、`source`、`chunk_id`、`type` |

**检索语义：**

1. 按 `priority` 从高到低分组，组内按 `baseList` 顺序检索。
2. 一旦累计结果中出现非空 `docs`，立即返回并停止向低优先级降级。
3. 如果所有组都没有命中，返回已累计的结果（可能包含空 `docs` 的 base）。
4. 某个 base 没有对应向量表/索引时，该 base **可能不出现在响应里**；请按 `baseName` 匹配，不要依赖数组长度或顺序。
5. `type=1` 的关键词路**不使用** `score_threshold`。

> ⚠️ **重要：** 本接口内部异常会被收敛成 `200 + []`（与“没命中”同形），不会返回 5xx。
> 生产集成建议使用 `/agent/search`，它会通过 `degraded` 与 `warnings` 暴露部分失败，并在完全失败时返回 `502`。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 400 | `malformed_request` | 请求体不是 JSON 对象、字段类型错误 |
| 415 | `unsupported_media_type` | `Content-Type` 不是 `application/json` |
| 422 | `validation_failed` | `question` 为空、`bases` 为空、`priority`/`top_k`/`score_threshold` 越界 |

### 6.2 图谱检索

```http
POST /retrieval/graph
```

先用向量检索找到种子实体/边/切片，再按深度传播获取子图。只读。

**请求体：**

```json
{
  "query": "Alice",
  "embedding": "Qwen3-Embedding-0.6B",
  "bases": ["graph_fedcba9876543210fedcba9876543210"],
  "seed_k": 5,
  "depth": 1,
  "limit": 1000,
  "score": 0.0,
  "labels": ["Person", "Knows"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 自然语言查询，不能为空 |
| `embedding` | string | 是 | embedding 注册名，不能为空 |
| `bases` | string[] | 是 | 图谱 base 名列表，格式 `graph_<kb_id>`；不能为空 |
| `seed_k` | integer | 否 | 种子节点数，1–50；默认 5 |
| `depth` | integer | 否 | 传播深度，1–10；默认 1 |
| `limit` | integer | 否 | 返回实体数上限，1–1000；默认 1000 |
| `score` | number | 否 | 种子相似度阈值，0–1；默认 0 |
| `labels` | string[] | 否 | 实体/边标签前置过滤，最多 10 个非空字符串；自动去重 |

**响应：**

```json
{
  "base_results": [
    {
      "base": "graph_fedcba9876543210fedcba9876543210",
      "entities": [
        {"entity_id": "Person_1", "age": 34, "name": "Alice", "chunk_id": "00000000-0000-4000-8000-000000000000"}
      ],
      "edges": [
        {"edge_id": "Knows_1", "source_id": "Person_1", "target_id": "Person_2", "since": null}
      ],
      "entity_count": 3,
      "edge_count": 4,
      "seed_entity_ids": ["Person_3", "Person_2", "Person_1"],
      "chunks": {
        "00000000-0000-4000-8000-000000000000": {
          "chunk_id": "00000000-0000-4000-8000-000000000000",
          "source": "team.md",
          "chunk_order": "0",
          "spilt_type": "system",
          "text": "切片正文……",
          "label": "",
          "table_name": "",
          "table_id": ""
        }
      },
      "chunk_count": 1
    }
  ],
  "total_entities": 3,
  "total_edges": 4,
  "base_count": 1
}
```

| 字段 | 说明 |
|---|---|
| `base_results[].base` | 图谱 base 名 |
| `base_results[].entities` | 实体数组。**属性是平铺的**：`entity_id` 加上实体自身的属性键 |
| `base_results[].edges` | 边数组。**属性是平铺的**：`edge_id`、`source_id`、`target_id` 加上边自身的属性键 |
| `base_results[].entity_count` / `edge_count` | 该 base 返回的实体/边数量 |
| `base_results[].seed_entity_ids` | 命中的种子实体 ID |
| `base_results[].chunks` | `chunk_id → 切片详情` 映射；可能为空对象 |
| `base_results[].chunk_count` | 切片数量 |
| `base_results[].error` | 可选。该 base 级失败时的错误文本 |
| `total_entities` / `total_edges` | 所有 base 的合计 |
| `base_count` | 请求的 base 数量 |

> 图谱检索的实体/边**不返回相似度分数**；如果需要排序依据，请使用 `seed_entity_ids` 的顺序或另外调用图查询。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 415 | `unsupported_media_type` | `Content-Type` 不是 `application/json` |
| 422 | `validation_failed` | 参数缺失/越界、`labels` 超限 |
| 429 | `rate_limited` | 超过 300 次/秒/IP（1 秒窗口） |
| 502 | `upstream_unavailable` | embedding 服务失败 |
| 500 | `internal_error` | 图存储查询失败 |


## 7. 编排问答

`POST /query` 执行一个**已发布工作流**的完整链路：查询改写 → 检索 → 重排 → 答案合成。支持普通 JSON 与 SSE 流式两种模式。

### 7.1 请求

```http
POST /query
Content-Type: application/json
```

```json
{
  "question": "如何配置检索编排？",
  "conversation_id": "d-20261026-001",
  "workflow_id": "RAG_Workflow_1a2b",
  "stream": false,
  "include_retrieval": true,
  "chat_history": [{"question": "上一轮问题", "answer": "上一轮回答"}]
}
```

- 鉴权：浏览器会话 / 网关令牌（跟随部署的 `AUTH_MODE`）。
- **机器对机器请使用 `POST /agent/query`**（Agent API Key，第 8.9 节）；两者运行同一套编排与 SSE 逻辑。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 用户问题，不能为空 |
| `conversation_id` | string | 是 | 对话 ID。同一 ID 的多轮请求共享上下文 |
| `workflow_id` | string | 实际必填 | 已发布工作流 ID。默认值 `default_workflow_id` 通常不存在，建议显式传入 |
| `stream` | boolean | 否 | `true` 时返回 SSE；默认 `false` |
| `include_retrieval` | boolean | 否 | `true` 时随响应返回本轮检索依据；默认 `false` |
| `chat_history` | array | 否 | 多轮历史，元素为 `{"question": "...", "answer": "..."}` |
| `kwargs` | object | 否 | 画布运行时高级参数；普通集成不需要。支持 `question_length_limit`（正整数） |

**关于 `workflow_id`：**

- 只接受**已发布**的工作流。未发布、已下线或 ID 不存在时返回 `404 published_workflow_not_found`。
- 模型、检索库、重排、提示词等全部由工作流配置决定；请求里的 `llm` 等字段不生效。

**关于 `chat_history` 与多轮：**

- `chat_history` 是调用方显式传入的历史，优先级高于服务端进程内记忆。
- 服务端也会按 `conversation_id` 在进程内保存最近几轮问题；**该记忆只在单副本内有效**。
- 多副本部署时请每次显式传 `chat_history`，并保证同一 `conversation_id` 落到同一副本（会话粘滞），否则多轮效果不稳定。

### 7.2 非流式响应

```json
{
  "conversation_id": "d-20261026-001",
  "answer": "根据检索结果，检索编排的配置步骤如下……",
  "placeholder": {},
  "citation": {},
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
| `placeholder` | object | 历史保留字段，通常为 `{}`，请勿依赖 |
| `citation` | object | 历史保留字段，通常为 `{}`，请勿依赖 |
| `related_context` | array | 可选。多轮/反馈场景的上下文，普通请求通常不出现 |
| `retrieval` | object | 仅 `include_retrieval=true` 时出现，见 7.4 |

### 7.3 流式响应（SSE）

**触发方式：**

- 请求体 `"stream": true`，或
- 请求头 `Accept: text/event-stream`。

**响应头：**

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Request-Id: 4f2c9a1b7d8e4c60
```

**事件序列：**

```text
event: retrieval
data: {"conversation_id":"d-001","evidence":{...}}

event: token
data: {"conversation_id":"d-001","content":"根据"}

event: token
data: {"conversation_id":"d-001","content":"检索结果，"}

event: done
data: {"conversation_id":"d-001","finish_reason":"stop"}
```

| 事件 | 出现时机 | `data` 结构 |
|---|---|---|
| `retrieval` | 仅 `include_retrieval=true`；在第一个 `token` 之前，最多一次 | `{"conversation_id": "...", "evidence": {...}}` |
| `token` | 多次 | `{"conversation_id": "...", "content": "..."}`；`content` 是增量文本 |
| `done` | 终态，一次 | `{"conversation_id": "...", "finish_reason": "stop"}` |
| `error` | 终态，最多一次 | RFC 9457 字段 + `conversation_id`，见下 |

**流中途错误：**

```text
event: error
data: {
  "type": "urn:ragstudio:problem:llm_unavailable",
  "title": "LLM unavailable",
  "status": 502,
  "detail": "……",
  "code": "llm_unavailable",
  "conversation_id": "d-001"
}
```

- 出第一字节**之前**的失败仍是真实 HTTP 状态码 + `application/problem+json`。
- 已经进入流之后的失败，HTTP 状态仍是 `200`，错误通过 `event: error` 表达。
- `error` 与 `done` 互斥；收到任一事件即应结束读取。

**心跳：**

- 服务端约每 15 秒发送一行以 `:` 开头的注释（例如 `: ping - 2024-01-01 00:00:00`）。
- 客户端应忽略注释行，不要把它当成事件。

**客户端实现建议：**

- 浏览器 `EventSource` 不支持 `POST`；请使用 `fetch` + `ReadableStream`，或使用成熟的 SSE 解析库。
- 按 `\n\n` 分帧，逐行解析 `event:` 与 `data:`；`data:` 可能跨多行（本服务每帧只有一个 `data:`）。
- 拼接所有 `token.content` 作为最终答案；`done` 后停止。
- 为连接设置 ≥ 300 秒的空闲超时，并处理断线重连（重连后应使用新的 `conversation_id` 或由业务去重）。

### 7.4 检索依据（`include_retrieval=true`）

非流式响应中的 `retrieval` 与 SSE `retrieval` 事件的 `evidence` 同形：

```json
{
  "query": "如何配置检索编排？",
  "items": [
    {
      "index": 1,
      "kind": "document",
      "kb": "doc_0123456789abcdef0123456789abcdef",
      "source": "overview.md",
      "sourceId": "",
      "chunkId": "5",
      "chunkIndex": "3",
      "score": 0.87,
      "label": "",
      "text": "切片正文……",
      "truncated": false
    }
  ],
  "stats": {
    "count": 4,
    "total": 4,
    "sources": 3,
    "knowledgeBases": 1
  },
  "timings": {
    "understandingMs": 332.7,
    "retrievalMs": 127.3,
    "vectorRetrievalMs": 78.4,
    "keywordRetrievalMs": 46.1,
    "rerankMs": 5600.2
  }
}
```

| 字段 | 说明 |
|---|---|
| `query` | 本轮实际用于检索的查询（可能已被改写） |
| `items` | 证据片段，最多 20 条 |
| `items[].index` | 从 1 开始的展示编号 |
| `items[].kind` | `document` 或 `graph` |
| `items[].kb` | 知识库 base 名（`doc_*` 或 `graph_*`） |
| `items[].source` | 文件名 |
| `items[].sourceId` | 原始 source 值（当它与 `source` 不同时给出） |
| `items[].chunkId` | 切片 ID；可能为空串 |
| `items[].chunkIndex` | 切片序号；可能为空串 |
| `items[].score` | 重排/融合后的分数，口径随工作流 |
| `items[].label` | 图谱节点的标签；文档节点为空 |
| `items[].text` | 片段正文，单条最多 2000 字符 |
| `items[].truncated` | 正文是否被截断 |
| `stats.count` | 本次返回的条数（截断后） |
| `stats.total` | 命中总数（不受 20 条截断影响） |
| `stats.sources` | 按 `items`（截断后）去重的来源文件数 |
| `stats.knowledgeBases` | 按 `items`（截断后）去重的知识库数 |
| `timings` | 可选。阶段耗时（毫秒）：`understandingMs`、`retrievalMs`、`vectorRetrievalMs`、`keywordRetrievalMs`、`rerankMs`；未启用的阶段缺 key。`retrievalMs` 是检索合计，`vectorRetrievalMs` / `keywordRetrievalMs` 是混合检索的分项（与合计不是相加关系） |

### 7.5 错误码

| HTTP | `code` | 场景 |
|---|---|---|
| 404 | `published_workflow_not_found` | 工作流未发布/不存在 |
| 422 | `validation_failed` | 缺少 `question`、`conversation_id`、`workflow_id`，或 `question_length_limit` 非法/超限 |
| 422 | `question_not_match_desc_info` | 工作流没有可用的回答生成器 |
| 422 | `only_support_sequential_hybrid` | 当前调用方式与工作流的顺序/混合模式不匹配 |
| 422 | `web_search_not_supported` | 工作流需要联网搜索，当前部署未配置该能力 |
| 422 | `workflow_has_no_operator` | 工作流没有可执行算子 |
| 500 | `workflow_config_invalid` | 工作流配置损坏 |
| 503 | `knowledge_base_not_imported` | 工作流绑定的知识库未导入/未就绪 |
| 503 | `no_llm_available` | 没有可用生成模型 |
| 503 | `rerank_endpoint_not_configured` | 配置了重排但没有可用端点 |
| 503 | `rerank_model_not_configured` | 重排模型未配置 |
| 502 | `knowledge_base_unavailable` | 知识库服务失败 |
| 502 | `knowledge_graph_unavailable` | 图谱服务失败 |
| 502 | `llm_unavailable` | 生成模型失败 |
| 502 | `llm_gateway_unavailable` | 生成网关失败 |
| 502 | `model_gateway_unavailable` | 模型网关失败 |
| 502 | `upstream_unavailable` | 其他上游失败 |
| 502 | `llm_empty_content` | 模型返回空内容 |
| 502 | `llm_empty_content_truncated` | 模型输出被截断 |
| 500 | `internal_error` | 未预期错误 |


## 8. Agent API

Agent API 是面向机器集成的最简入口。它暴露**文档知识库**的只读能力，以及**工作流的查询与执行**，不需要浏览器会话。工作流的创建、画布编排与发布仍属控制台管理面。

- 前缀：`/api/co-knowledge/v1/agent`
- 认证：Agent API Key（`Authorization: Bearer ...` 或 `X-API-Key: ...`）
- 成功体：资源本身（数组/对象），无信封
- 错误体：`application/problem+json`
- 追踪：每个响应带 `X-Request-Id`

### 8.1 权限范围与知识库白名单

| Scope | 允许的接口 |
|---|---|
| `kb:list` | `GET /agent/knowledge-bases`、`GET /agent/knowledge-bases/{kb_id}` |
| `kb:search` | `POST /agent/search` |
| `kb:answer` | `POST /agent/answer` |
| `workflow:read` | `GET /agent/workflows` |
| `workflow:run` | `POST /agent/query`（执行已发布工作流） |

- Key 的 `kbIds` 为空表示“全部可访问文档库”；非空时只允许访问列表中的知识库。
  `POST /agent/query` 也按发布快照绑定的文档/结构化知识库执行同一份白名单校验；图谱库不在此白名单内。
- 显式传入不存在或图谱知识库的 ID → `404 knowledge_base_not_found`。
- 显式传入存在但不在白名单的 ID → `403 knowledge_base_forbidden`。
- 不传 `knowledge_base_ids` 时，会检索该 Key 可访问的**全部文档知识库**；如果超过部署上限（默认 50），返回 `400 invalid_request`，此时请显式传 `knowledge_base_ids`。
- 图谱知识库不在 Agent API 范围内；图谱能力请用原生 `/retrieval/graph` 或图查询接口。

### 8.2 列知识库

```http
GET /agent/knowledge-bases
```

- Scope：`kb:list`
- 响应：裸数组，返回全部文档知识库；**顺序不保证**。

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
| `name` | string | 名称 |
| `description` | string \| null | 描述 |
| `type` | string \| null | 历史类型标识 |
| `embedding_model` | string \| null | embedding 注册名 |
| `status` | string \| null | 状态码，含义同 5.1 |
| `created_date` | string \| null | ISO 8601，秒级，无时区后缀 |

> 列表**不按“已就绪”过滤**；请根据 `status` 判断是否可用。通常 `status="0"` 的文档库可直接检索。

### 8.3 知识库详情

```http
GET /agent/knowledge-bases/{kb_id}
```

- Scope：`kb:list`
- 响应：单个对象，字段同 8.2。
- 错误：不存在或为图谱库 → `404 knowledge_base_not_found`。

### 8.4 检索

```http
POST /agent/search
```

- Scope：`kb:search`
- 请求体不接受未声明字段（多传字段会 `422`）。

**请求：**

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
| `query` | string | 是 | 1–2000 字符 |
| `knowledge_base_ids` | string[] | 否 | 省略/空 = 全部可访问文档库；元素会去重、去空白 |
| `mode` | string | 否 | `auto`（默认）、`hybrid`、`vector`、`keyword` |
| `top_k` | integer | 否 | 返回条数，默认 8，上限由部署配置决定（默认 20） |
| `score_threshold` | number | 否 | 0–1，仅向量路生效；默认 0 |

**`mode` 语义：**

| 模式 | 行为 |
|---|---|
| `auto` | 两路都可用时 RRF 融合；某一路失败时自动降级到另一路；**永不因单路失败而整体 502** |
| `hybrid` | 两路都查，RRF 融合；显式指定 KB 时，任一路/任一库失败即 502；隐式全部库时失败记 warning 并降级 |
| `vector` | 只查向量路 |
| `keyword` | 只查关键词路 |

> `auto` 在只有一路可用时仍会返回结果，并置 `degraded=true`；两路都失败才返回 `502 retrieval_failed`。

**响应：**

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
| `query` | string | 原样返回 |
| `mode` | string | **实际生效**的模式。`auto` 可能返回 `hybrid`/`vector`/`keyword`/`auto` |
| `results` | array | 检索结果，按融合/分数排序 |
| `degraded` | boolean | `true` 表示部分路径或知识库失败，但仍有结果 |
| `warnings` | array | 结构化告警，见下 |

**`results[]` 字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `citation_id` | string | `S1`、`S2`……用于引用 |
| `knowledge_base_id` | string | 知识库 ID |
| `knowledge_base_name` | string \| null | 知识库名称 |
| `chunk_id` | string \| null | 切片 ID；向量路可能为 null |
| `document_id` | string \| null | 文件 ID；部分文档的向量表可能没有文件 ID/切片 ID |
| `source` | string \| null | 文件名 |
| `score` | number | 单路分数；`hybrid` 时为 RRF 融合分数 |
| `scores` | object \| null | `hybrid` 时给出参与融合的各路原始分数，键为 `vector` / `keyword`；某一路无命中（或未参与）时缺该键；其他模式为 null |
| `text` | string | 片段正文，最多 2000 字符 |
| `metadata` | object \| null | 元数据：`chunk_index`、`source`、`type` 等 |

**`warnings[]`：**

| `code` | 含义 |
|---|---|
| `vector_table_missing` | 该知识库没有向量表（未导入/未建索引） |
| `keyword_index_missing` | 该知识库没有关键词索引 |
| `vector_path_failed` | 向量路查询失败（embedding 或向量库异常） |
| `keyword_path_failed` | 关键词路查询失败（ES 异常） |

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
| 400 | `invalid_request` | 可访问知识库超过上限且未显式指定 ID |
| 400 | `no_accessible_knowledge_bases` | Key 没有任何可访问文档库 |
| 401 | `unauthorized` | Key 缺失/无效/停用/过期 |
| 403 | `forbidden_scope` | Key 没有 `kb:search` |
| 403 | `knowledge_base_forbidden` | 显式 ID 不在 Key 白名单 |
| 404 | `knowledge_base_not_found` | 显式 ID 不存在或为图谱库 |
| 422 | `validation_failed` | 参数校验失败（含未声明字段） |
| 429 | `rate_limited` | 超过 Key 的每分钟上限 |
| 502 | `retrieval_failed` | 检索整体失败 |

### 8.5 问答

```http
POST /agent/answer
```

- Scope：`kb:answer`
- 请求体不接受未声明字段。

**请求：**

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
| `question` | string | 是 | 1–2000 字符 |
| `knowledge_base_ids` | string[] | 否 | 省略/空 = 全部可访问文档库 |
| `mode` | string | 否 | 同 8.4 |
| `top_k` | integer | 否 | 检索来源数，默认 8，上限由部署配置决定（默认 20） |
| `model` | string | 否 | 可选，已注册的 LLM 名称。部署若设置强制模型则忽略此字段 |

**响应：**

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
| `citations[].text` | string | 来源片段（受总上下文预算 12000 字符限制，可能被截断） |
| `model` | string \| null | 实际使用的模型注册名 |
| `usage` | object \| null | 上游生成端点返回的 token 用量，结构可能随模型变化 |
| `no_results` | boolean | 检索结果为空时为 true；此时**不会调用生成模型**，HTTP 仍为 200 |
| `reason` | string \| null | `no_results=true` 时为 `no_context` |
| `warnings` | array | 检索告警 + 引用告警，见下 |

**`citations[]` 字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `citation_id` | string | `S1`、`S2`……与答案里的引用编号对应 |
| `knowledge_base_id` | string | 知识库 ID |
| `document_id` | string \| null | 文件 ID |
| `source` | string \| null | 文件名 |
| `chunk_id` | string \| null | 切片 ID；可能为 null |
| `text` | string | 送入生成模型的片段正文（可能被上下文预算截断） |

**引用告警：**

| `code` | 含义 |
|---|---|
| `unknown_citation` | 答案引用了未提供的来源编号 |
| `no_citations_in_answer` | 答案没有引用任何来源 |

**重要语义：**

- `no_results=true` 只表示**检索结果为空**；如果检索到不相关片段，模型仍可能回答“资料中没有答案”，此时 `no_results=false`，需要业务侧判断答案内容。
- `citations` 只包含**实际送入生成模型**的来源；`text` 可能因上下文预算被截断。
- 答案质量与引用完整性由模型决定；请把 `citations` 作为溯源依据，而不是把 `answer` 当唯一事实来源。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 401 | `unauthorized` | Key 缺失/无效/停用/过期 |
| 403 | `forbidden_scope` | Key 没有 `kb:answer` |
| 403 | `knowledge_base_forbidden` | 显式 ID 不在白名单 |
| 404 | `knowledge_base_not_found` | 显式 ID 不存在或为图谱库 |
| 422 | `validation_failed` | 参数校验失败（含未声明字段） |
| 429 | `rate_limited` | 超过 Key 的每分钟上限 |
| 502 | `retrieval_failed` | 检索整体失败 |
| 502 | `answer_failed` | 生成端点不可用、非 2xx、空内容或输出被截断 |
| 503 | `answer_unavailable` | 没有可用生成模型，或问答端点被关闭 |
| 503 | `configuration_error` | Agent Key pepper 未配置（服务端配置问题） |
| 503 | `agent_key_store_unavailable` | Key 存储不可用（数据库未初始化） |

### 8.6 工作流查询（只读）

Agent API 提供工作流**查询与执行**，不提供创建、画布编排、发布/取消发布。工作流的创建、Embedding/LLM/检索参数调整、发布都在 Knowledge Studio 控制台画布完成；API 用来发现工作流 ID（尤其是已发布、可被 `POST /agent/query` 执行的那些）。

| 方法 | 路径 | Scope | 说明 |
|---|---|---|---|
| `GET` | `/agent/workflows` | `workflow:read` | 分页列表，支持 `keyword`、`publishType` |

**列表：**

```http
GET /api/co-knowledge/v1/agent/workflows?page=1&size=100&publishType=1
Authorization: Bearer ragk_...
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `page` | 1 | 从 1 开始 |
| `size` | 10 | 1–1000 |
| `keyword` | — | 按名称模糊匹配（不区分大小写） |
| `publishType` | — | `0` 未发布、`1` 已发布、`2` 已发布但草稿有改动；不传表示不筛 |

响应为 `{"items":[...],"total":n,"page":1,"pageSize":100}`。

`items[]` 字段：

| 字段 | 说明 |
|---|---|
| `workFlowId` | 工作流 ID（注意大写 `F`）；`/query` 的 `workflow_id` 就是它 |
| `name` / `description` | 名称 / 描述 |
| `template` | 播种模板（`Sequential` / `Blended` / `Conditional`） |
| `publishType` | 0 未发布 / 1 已发布 / 2 已发布但草稿有改动 |
| `createdBy` / `createdDate` / `lastUpdatedDate` | 归属与时间 |
| `kbPkIds` / `graphKbPkIds` | 绑定的文档库 / 图谱库（含 `tableName`、`embeddingModel` 等） |

响应示例（省略部分字段）：

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

**怎么用：**

- 先查 `publishType=1`（或 `2`）拿已发布工作流的 `workFlowId`。
- 把它作为 `POST /agent/query` 的 `workflow_id`。`publishType=2`（发布后草稿又改过）仍然可用——执行的是发布快照；只需排除 `0`。
- 用带 `workflow:run` 的 Agent Key 调用 `POST /agent/query` 即可闭环（第 8.9 节）；没有该 scope 时只能用 `/agent/answer` 做知识库问答。

**工作流的参数（Embedding 模型 / LLM / 检索参数）：**

- Embedding 模型由绑定的知识库决定（同一次工作流绑定的库必须使用同一向量化模型），在控制台建库/编排时确定。
- LLM（问题改写 / 重排 / 回答生成）、`top_k`、`score`、`priority`、`top_n`、`temperature`、提示词等都在控制台画布对应算子抽屉里配置。
- Agent API 不接收这些参数；`/query` 请求体里的 `llm` 也不生效，全部以工作流配置为准。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 401 | `unauthorized` | Key 缺失、非法、停用或过期 |
| 403 | `forbidden_scope` | 缺少 `workflow:read` |
| 500 | `internal_error` | 工作流存储不可用等服务端错误 |

### 8.7 通用错误示例

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
X-Request-Id: 8f1d2c3b4a5e6f70
WWW-Authenticate: Bearer

{
  "type": "urn:ragstudio:problem:forbidden_scope",
  "title": "Forbidden scope",
  "status": 403,
  "detail": "API key does not have the required scope: kb:answer",
  "code": "forbidden_scope",
  "instance": "/api/co-knowledge/v1/agent/answer",
  "required_scope": "kb:answer"
}
```

### 8.8 OpenAPI 导入

Agent 接口提供 OpenAPI 3.0.2，可直接导入 Dify、Coze 等平台：

```text
GET /api/co-knowledge/v1/agent/openapi.json
```

- 该端点**公开**，不需要 API Key。
- `servers[0].url` 由部署配置决定；未配置时为相对路径 `/api/co-knowledge/v1/agent`。
- OpenAPI 覆盖 `/agent/*` 的 **6 条**业务路径（含 `POST /agent/query`），可直接导入执行工作流。
- 不提供 Swagger UI。
- 本目录附带一份快照：`openapi/agent-api.yaml`。


### 8.9 执行已发布工作流

```http
POST /agent/query
Authorization: Bearer ragk_...
Content-Type: application/json
```

- Scope：`workflow:run`
- 运行的是与原生 `/query` 相同的编排链路（改写 → 检索 → 重排 → 生成），
  响应体、SSE 事件序列与错误码见第 7 节。
- 只执行**已发布**快照；`workflow_id` 必须显式传入；不接受 `scope=dev`。
- Key 的 `kbIds` 白名单会按发布快照绑定的文档/结构化知识库校验；图谱库由 `workflow:run` 授权。

**请求：**

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
| `question` | string | 是 | 1–2000 字符 |
| `conversation_id` | string | 是 | 对话 ID；同一 ID 多轮共享上下文 |
| `workflow_id` | string | 是 | 已发布工作流 ID |
| `stream` | boolean | 否 | `true` 返回 SSE；默认 `false` |
| `include_retrieval` | boolean | 否 | `true` 时返回本轮检索依据 |
| `chat_history` | array | 否 | 元素为 `{"question": "...", "answer": "..."}` |

**非流式响应：**

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
| `answer` | string | 回答正文 |
| `retrieval` | object | 仅 `include_retrieval=true` 时出现 |

> Agent 面返回精简形状，不含原生 `/query` 的 `placeholder` / `citation` / `related_context`
> 历史字段。SSE 事件序列与第 7.3 节一致。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 401 | `unauthorized` | Key 缺失、无效、停用或过期 |
| 403 | `forbidden_scope` | Key 缺少 `workflow:run` |
| 403 | `knowledge_base_forbidden` | 工作流绑定的文档库不在 Key 白名单 |
| 404 | `published_workflow_not_found` | 工作流不存在或尚未发布 |
| 422 | `validation_failed` | 缺少必填字段或参数非法 |
| 429 | `rate_limited` | 超过 Key 的每分钟上限 |
| 502 / 503 | 见第 7.5 节 | 编排链路上游失败 |


## 9. MCP 接入

MCP 入口与 Agent REST 共用同一套 Key、Scope 与知识库白名单。

### 9.1 端点与协议

```text
GET/POST /api/co-knowledge/v1/mcp
```

- 协议：MCP Streamable HTTP（客户端会按协议使用 `POST` 发送消息、`GET` 建立 SSE 流）。
- 认证：每个请求（**包括 `initialize`**）都必须带 `Authorization: Bearer <Agent API Key>`。
- 也接受 `X-API-Key`。
- 尾斜杠 `/mcp/` 同样可用。

### 9.2 工具

| 工具 | 所需 Scope | 用途 | 说明 |
|---|---|---|---|
| `list_knowledge_bases` | `kb:list` | 发现可访问文档库 | 返回 `{trace_id, knowledge_bases}` |
| `search_knowledge` | `kb:search` | 取回原文片段 | 参数 `query`、`knowledge_base_ids`、`mode`、`top_k`；返回 `{trace_id, query, mode, results, degraded, warnings}` |
| `ask_knowledge_base` | `kb:answer` | 生成带引用的答案 | 参数 `question`、`knowledge_base_ids`、`mode`、`top_k`、`model`；返回 `{trace_id, answer, citations, model, usage, no_results, reason, warnings}` |
| `list_workflows` | `workflow:read` | 工作流查询 | 参数 `page`、`size`、`keyword`、`publish_type`；返回 `{trace_id, items, total, page, pageSize}` |
| `run_workflow` | `workflow:run` | 执行已发布工作流 | 参数 `question`、`conversation_id`、`workflow_id`、`stream`、`include_retrieval`、`chat_history`；返回 `{trace_id, conversation_id, answer, retrieval?}` |

`search_knowledge` 不暴露 `score_threshold`；需要阈值过滤时请使用 REST `/agent/search`。

`list_workflows` 与 REST `GET /agent/workflows` 同源，只读；工作流的创建、画布编排与发布在控制台完成。

`run_workflow` 与 REST `POST /agent/query`（第 8.9 节）同源：同样的发布快照校验、知识库白名单与 `conversation_id` 多轮状态。MCP 没有「工具结果流」，`stream=true` 时生成的 token 通过 MCP **progress 通知**（`notifications/progress`，客户端需带 `progressToken`）旁路送达，工具结果仍在结束时返回完整答案；`stream=false`（默认）与 REST 非流式响应同形。失败以 `isError: true` 返回，消息形如 `forbidden_scope: …` / `validation_error: …` / `published_workflow_not_found: …`。

### 9.3 客户端配置

**Claude Code：**

```bash
claude mcp add --transport http knowledge-studio \
  https://rag.example.com/api/co-knowledge/v1/mcp \
  --header "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY"
```

**项目 `.mcp.json`：**

```json
{
  "mcpServers": {
    "knowledge-studio": {
      "type": "http",
      "url": "https://rag.example.com/api/co-knowledge/v1/mcp",
      "headers": {"Authorization": "Bearer ragk_xxx"}
    }
  }
}
```

**只支持 stdio 的客户端：**

```bash
npx -y mcp-remote https://rag.example.com/api/co-knowledge/v1/mcp \
  --header "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY"
```

### 9.4 工具错误

工具失败以 MCP `isError: true` 返回，文本形如：

```text
unauthorized: Invalid or missing API key
forbidden_scope: API key does not have the required scope: kb:search
validation_error: String should have at least 1 character
```

- 客户端需要检查 `isError`，不要只看文本是否为空。
- 工具结果里的 `trace_id` 可用于服务端排障。
- 每次请求都要带 `Authorization`；只在首次握手时带会导致后续调用 401。


## 10. 本地账号登录（`AUTH_MODE=local`）

仅当部署配置 `AUTH_MODE=local` 时生效。`AUTH_MODE=none` 或 `gateway` 下，登录与改密返回 `409 auth_not_enabled`。

### 10.1 登录状态

```http
GET /auth/status
```

公开接口，返回当前鉴权模式与登录状态：

```json
{
  "mode": "local",
  "initialized": true,
  "authenticated": false,
  "user": null
}
```

| 字段 | 说明 |
|---|---|
| `mode` | `none` / `local` / `gateway` |
| `initialized` | 本地账号表是否已初始化 |
| `authenticated` | 当前请求是否已携带有效会话 |
| `user` | 已登录时为用户对象，否则 null |

### 10.2 登录

```http
POST /auth/login
Content-Type: application/json

{"username": "integration-user", "password": "********"}
```

**成功：** `200 OK` + `Set-Cookie: ragstudio_session=...`。

```json
{
  "user": {
    "username": "integration-user",
    "displayName": "Integration User",
    "email": "",
    "role": "user",
    "mustChangePassword": false
  }
}
```

**Cookie 属性：** `HttpOnly; Path=/; SameSite=Lax; Max-Age=<ttl>`，HTTPS 下会加 `Secure`。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 401 | `invalid_credentials` | 用户名或密码错误 |
| 403 | `account_disabled` | 账号被禁用 |
| 403 | `csrf_rejected` | `Origin`/`Referer` 与 `Host` 不一致 |
| 409 | `auth_not_enabled` | 当前不是 `local` 模式 |
| 413 | `payload_too_large` | 请求体超过 8KB |
| 429 | `login_rate_limited` | 失败次数过多，带 `Retry-After` |
| 503 | `auth_not_initialized` | 账号表未初始化 |

> 登录请求的请求体上限为 8KB（nginx `/auth/` 与后端双重限制）。

### 10.3 退出

```http
POST /auth/logout
```

- 撤销当前会话并清除 Cookie。
- 幂等：即使没有有效会话也返回 `204 No Content`。

### 10.4 当前用户

```http
GET /auth/me
```

- 成功：`200 {"user": {...}}`。
- 未登录或会话过期：`401 unauthorized` / `401 session_expired`。

### 10.5 修改密码

```http
POST /auth/password
Content-Type: application/json

{"currentPassword": "********", "newPassword": "********"}
```

- 成功：`204 No Content`；撤销该用户的**其他**会话，当前会话保留。
- 密码策略：8–128 个字符，不能含控制字符；不强制大小写/符号组合。
- 首次登录 `mustChangePassword=true` 时，除 `/auth/me` 与 `/auth/password` 外的请求都会返回 `403 password_change_required`。

**错误：**

| HTTP | `code` | 场景 |
|---|---|---|
| 401 | `unauthorized` / `session_expired` | 未登录/会话过期 |
| 403 | `csrf_rejected` | 来源校验失败 |
| 422 | `invalid_current_password` | 当前密码错误 |
| 422 | `password_policy` | 新密码不符合策略，或与当前密码相同 |
| 429 | `login_rate_limited` | 改密失败次数过多 |


## 11. 配额与调用约束速查

| 项目 | 限制 |
|---|---|
| Agent `query` / `question` | 1–2000 字符 |
| Agent `top_k` | 默认 8，上限部署可配（默认 20） |
| Agent 可访问文档库 | 默认最多 50 个；超出需显式传 `knowledge_base_ids` |
| Agent Key 限流 | 默认 60 次/分钟/Key，可配置；0 表示不限 |
| 文档检索 `top_k` | 每个 base 1–80 |
| 文档检索 `priority` | 0–10，实际必填 |
| 图谱检索 `seed_k` | 1–50 |
| 图谱检索 `depth` | 1–10 |
| 图谱检索 `limit` | 1–1000 |
| 图谱检索 `labels` | 最多 10 个字符串 |
| 图谱检索限流 | 300 次/秒/IP（1 秒窗口） |
| 图查询 `depth` | 1–100 |
| 图查询 `limit` | 1–1000 |
| 知识库列表 `size` | 1–500 |
| Agent 工作流列表 `size` | 1–1000；`publishType` 仅 0/1/2 |
| `POST /agent/query` 问题长度 | 1–2000 字符 |
| `POST /agent/query` 生成超时 | 默认 120s；网关读超时需 ≥ 300s |
| Agent Key 执行工作流 | 必须显式传 `workflow_id`；只接受已发布快照 |
| 文档列表 `size` | 1–100 |
| 切片列表 `size` | 建议 ≤ 100（服务端未强制上限） |
| 登录/改密请求体 | ≤ 8KB |
| 会话有效期 | 默认 12 小时，可配 60 秒–30 天 |
| 登录失败限制 | 5 次/15 分钟/账号+IP；20 次/15 分钟/IP |
| `/query` 生成超时 | 默认 120 秒；nginx 读超时通常配 300 秒 |
| 检索依据条数 | 最多 20 条，单条正文最多 2000 字符 |
| Agent 问答上下文预算 | 12000 字符（所有来源合计） |


## 12. 版本与兼容性

### 12.1 版本号

- 契约版本：`2.3.0`（`contracts/VERSION`）。
- Agent OpenAPI 版本：`1.4.0`。
- 文档版本：`2.3.0`（与契约对齐）。

### 12.2 兼容承诺

- **新增**字段、端点、事件类型属于向后兼容变更，客户端必须忽略未知字段/未知事件。
- **删除**字段、改变字段类型/含义、改变错误码或路径属于破坏性变更，会提升主版本。
- `code`、`type`、HTTP 状态码是稳定契约；`detail`、`title` 文案可能调整（`title` 保持英文稳定，`detail` 本地化）。
- 分页响应中未使用的字段可能增加；客户端不要做严格结构校验（例如禁止额外字段）。
- Agent 请求体使用 `extra=forbid`：**请求**多传字段会 422，这是唯一不允许额外字段的地方。
- 会话键统一为 `conversation_id`；`POST /agent/query`（Agent Key + `workflow:run`）用于执行已发布工作流。
- MCP 的 `run_workflow` 与 REST `POST /agent/query` 同源，`stream=true` 时 token 通过
  MCP progress 通知旁路送达（第 8.9 / 9.2 节）。
- 原生 REST 的知识库 `status` 是整数（与目录/文件一致，均为 `smallint`），Agent API 的
  `status` 是字符串（第 5.1 / 8.2 节）。
- 链路 ID 响应头是 `X-Request-Id`；客户端传入的合法值（`[A-Za-z0-9._-]`、1–64 字符）原样沿用，
  不合法则丢弃并由服务端生成。


## 13. 接入检查清单

- [ ] 已确认部署地址、`AUTH_MODE` 与 TLS。
- [ ] 已创建 Agent Key，确认 `scopes` 与 `kbIds` 白名单。
- [ ] Key 已安全保存；明文只在创建时出现一次。
- [ ] 机器调用使用 `/agent/*`、`/mcp` 或带 `workflow:run` 的 `POST /agent/query`，没有误用 Agent Key 调 `/retrieval` / `/query` / `/workflows` 管理面。
- [ ] 需要查询工作流时，Key 已授予 `workflow:read`；需要执行已发布工作流时，Key 已授予 `workflow:run`；创建/编排/发布已在控制台完成。
- [ ] 已按 `code` 分支处理错误，而不是解析 `detail`。
- [ ] 已处理 `429` 的 `Retry-After`。
- [ ] 已为 `/agent/answer`、`/query` 设置足够的读超时（≥180/300 秒）。
- [ ] 流式场景已实现 SSE 解析、心跳忽略、`done`/`error` 终止。
- [ ] 需要中文错误提示时已发送 `Accept-Language: zh-CN`。
- [ ] 使用会话 Cookie 的 `POST` 已带 `Origin`（host 与 `Host` 一致）。
- [ ] 已记录 `X-Request-Id`，并在报障时提供。
- [ ] 已忽略响应中的内部/实现字段，不做严格结构校验。
- [ ] 多副本部署已考虑多轮记忆的会话粘滞或显式传 `chat_history`。
- [ ] 已确认知识库状态与索引就绪（文档库通常 `status="0"`，图谱库需已发布）。
- [ ] 已确认 `workflow_id` 是**已发布**版本。


## 14. 常见问题

### 14.1 认证与权限

**Q：Agent Key 明明存在，为什么一直 401？**

- Key 可能已被停用或过期；
- 服务端 `RKB_AGENT_KEY_PEPPER` 与创建 Key 时使用的 pepper 不一致；
- 请求没有在**每个** MCP 请求上带 `Authorization`；
- Key 格式不完整（`ragk_` + 8 位前缀 + `_` + 43 位密钥）。

**Q：为什么 Agent Key 调 `/retrieval`、`/query` 或 `/workflows` 返回 401/403？**

Agent Key 只对 `/agent/*` 与 `/mcp` 生效。原生 REST（包括 `/query`、`/workflows` 管理接口）使用部署的会话/网关鉴权。机器访问请改用 Agent 接口：检索/问答用 `/agent/search`、`/agent/answer`，工作流查询用 `/agent/workflows`、执行用 `/agent/query`。

**Q：客户/集成方要创建工作流，API 能建吗？**

不能，这是有意的：工作流的创建、画布编排、Embedding/LLM/检索参数调整与发布都在 Knowledge Studio 控制台完成。Agent API 提供 `GET /agent/workflows` 查询（第 8.6 节）与 `POST /agent/query` 执行（第 8.9 节），用来拿已发布工作流的 `workFlowId` 并执行。`/workflows` 是控制台管理接口，`AUTH_MODE=local` 时只认 `ragstudio_session` Cookie，API Key 不能调。

**Q：为什么带 Cookie 的 POST 返回 403 `csrf_rejected`？**

需要带 `Origin` 或 `Referer`，且 host 必须与请求的 `Host` 一致。脚本最稳妥的做法是显式带：

```bash
-H "Origin: https://rag.example.com"
```

### 14.2 检索与问答

**Q：`/retrieval` 返回 200 + 空数组，怎么判断是“没命中”还是“失败”？**

该接口会把内部异常收敛成空数组，两者同形。生产集成请使用 `/agent/search`，它会用 `degraded`/`warnings` 暴露部分失败，完全失败时返回 502。

**Q：`/agent/search` 返回 `degraded=true`，还能用吗？**

可以。`degraded=true` 表示某一路或某个知识库失败，但仍有结果。检查 `warnings` 定位：

- `vector_table_missing` / `keyword_index_missing`：知识库未导入或未建索引；
- `vector_path_failed` / `keyword_path_failed`：对应路径查询失败（embedding/ES/向量库）。

**Q：`document_id` 或 `chunk_id` 为 null？**

部分文档的向量表没有文件 ID/切片 ID，服务端会尽量从关系表回填，但无法保证 100%。`source`（文件名）通常可用。

**Q：`/query` 返回 404 `published_workflow_not_found`？**

`workflow_id` 必须是**已发布**的工作流。请让部署方在画布上保存并发布，或提供正确的 `RAG_Workflow_xxxx`。

**Q：多轮对话没有记忆？**

- 同一 `conversation_id` 才会共享上下文；
- 服务端记忆在进程内，多副本部署不共享；
- 显式传 `chat_history` 最可靠；
- 刷新/重连后请继续使用同一 `conversation_id`。

**Q：SSE 一直卡住，最后一次性返回？**

通常是反向代理缓冲导致的。需要确保 `/query` 路径：
`proxy_buffering off`、`proxy_http_version 1.1`、`Connection ""`，并给足 `proxy_read_timeout`。这是部署方配置，客户端无法修复。

### 14.3 图谱

**Q：图查询返回 `422 graph_query_not_ready`？**

图谱仍在构建（状态 1–4）。等待构建完成后再查；构建失败会返回 `graph_query_failed`。

**Q：图查询的 `has_more=true` 但下一页是空的？**

`has_more` 的判定是“返回条数 ≥ limit”，正好满页也为 true。请结合 `next_cursor` 或实际返回条数判断。

**Q：图谱检索没有返回分数？**

当前图谱检索不返回实体/边相似度分数；`seed_entity_ids` 是按检索顺序给出的种子实体。

### 14.4 其他

**Q：响应里有很多不认识的字段，可以忽略吗？**

可以。`pkId`、`esIndexName`、`tableName`、`schemaObj` 等是 UI/实现字段，不属于对外契约，可能随版本变化。

**Q：为什么 `Accept-Language: zh` 返回英文？**

语言匹配口径：只有 `zh-CN`（以及 `*`）映射中文；`zh`、`zh-TW` 等返回英文。需要中文请显式发 `zh-CN`。

**Q：接口支持浏览器跨域调用吗？**

服务端未启用 CORS。浏览器集成需与平台同源，或由网关/反向代理处理跨域。


## 附录 A：curl 速查

```bash
# 环境变量
export BASE="https://rag.example.com/api/co-knowledge/v1"
export KEY="ragk_1a2b3c4d_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export KB="0123456789abcdef0123456789abcdef"
export WF="RAG_Workflow_xxxx"

# 健康检查
curl -sS "$BASE/health"

# Agent：列库
curl -sS "$BASE/agent/knowledge-bases" -H "Authorization: Bearer $KEY"

# Agent：检索
curl -sS "$BASE/agent/search" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"如何配置检索编排？\",\"knowledge_base_ids\":[\"$KB\"],\"mode\":\"auto\",\"top_k\":5}"

# Agent：问答
curl -sS "$BASE/agent/answer" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"如何配置检索编排？\",\"knowledge_base_ids\":[\"$KB\"],\"top_k\":5}"

# Agent：工作流查询（只取可用于 /query 的已发布工作流；创建/发布在控制台完成）
curl -sS "$BASE/agent/workflows?page=1&size=100&publishType=1" \
  -H "Authorization: Bearer $KEY"

# 本地登录（AUTH_MODE=local）
curl -sS -c cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"integration-user","password":"********"}' \
  "$BASE/auth/login"

# 知识库列表
curl -sS -b cookies.txt "$BASE/knowledge-bases?page=1&size=10&categories=1"

# 文档列表
curl -sS -b cookies.txt "$BASE/knowledge-bases/$KB/documents?page=1&size=50"

# 文档切片
curl -sS -b cookies.txt "$BASE/knowledge-bases/$KB/documents/<DOC_ID>/chunks?page=1&size=10"

# 文档检索
curl -sS -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"如何配置检索编排？\",\"type\":0,\"bases\":[{\"baseList\":[\"doc_$KB\"],\"priority\":1,\"top_k\":5,\"score_threshold\":0}]}" \
  "$BASE/retrieval"

# 图谱检索
curl -sS -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d '{"query":"Alice","embedding":"Qwen3-Embedding-0.6B","bases":["graph_<GRAPH_KB_ID>"],"seed_k":5,"depth":1,"limit":100}' \
  "$BASE/retrieval/graph"

# 编排问答（非流式）
curl -sS -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"如何配置检索编排？\",\"conversation_id\":\"d-001\",\"workflow_id\":\"$WF\",\"include_retrieval\":true}" \
  "$BASE/query"

# 编排问答（SSE）
curl -sS -N -b cookies.txt \
  -H "Origin: https://rag.example.com" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"如何配置检索编排？\",\"conversation_id\":\"d-002\",\"workflow_id\":\"$WF\",\"stream\":true}" \
  "$BASE/query"

# 编排问答（Agent Key，需要 workflow:run）
curl -sS \
  -H "Authorization: Bearer $KNOWLEDGE_STUDIO_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"如何配置检索编排？\",\"conversation_id\":\"d-003\",\"workflow_id\":\"$WF\"}" \
  "$BASE/agent/query"
```


## 附录 B：机器可读契约

| 契约 | 位置 | 说明 |
|---|---|---|
| Agent OpenAPI | `GET /api/co-knowledge/v1/agent/openapi.json` | OpenAPI 3.0.2，公开，可导入 Dify/Coze |
| Agent OpenAPI 快照 | `openapi/agent-api.yaml`（本目录） | 当前快照（6 paths，含 `GET /agent/workflows`、`POST /agent/query`） |
| MCP 工具描述 | `/mcp` 的 `tools/list` | 以服务端实时返回为准 |

> 完整 REST OpenAPI 包含管理面，未随本文交付。本文所列原生 REST 接口的字段与语义以本文为准。


## 附录 C：错误码总表（集成面）

| HTTP | `code` | 出现位置 | 说明 |
|---|---|---|---|
| 400 | `bad_request` | 原生 REST | 请求无法处理 |
| 400 | `malformed_request` | 原生 REST | JSON 畸形/字段类型错误 |
| 400 | `invalid_request` | Agent | 参数业务校验失败（如可访问库过多） |
| 400 | `no_accessible_knowledge_bases` | Agent | Key 没有可访问文档库 |
| 401 | `unauthorized` | Agent / 原生 REST | 未认证或凭据无效 |
| 401 | `session_expired` | 原生 REST | 会话已过期/被撤销 |
| 401 | `invalid_credentials` | 登录 | 用户名或密码错误 |
| 403 | `permission_denied` | 原生 REST | 无权限 |
| 403 | `forbidden_scope` | Agent | Key 缺少所需 scope |
| 403 | `knowledge_base_forbidden` | Agent | 知识库不在 Key 白名单 |
| 403 | `csrf_rejected` | 登录 / 原生 REST | 来源校验失败 |
| 403 | `account_disabled` | 登录 | 账号被禁用 |
| 403 | `password_change_required` | 登录 | 首次登录必须改密 |
| 404 | `knowledge_base_not_found` | 多处 | 知识库不存在或不是文档库 |
| 404 | `directory_not_found` | 原生 REST | 目录不存在（部分端点用全 null 对象代替） |
| 404 | `file_not_found` | 原生 REST | 文档不存在 |
| 404 | `not_found` | 原生 REST | 路径不存在 |
| 404 | `published_workflow_not_found` | `/query` | 工作流未发布/不存在 |
| 409 | `conflict` | 原生 REST | 状态冲突 |
| 409 | `auth_not_enabled` | 登录 | 当前不是 local 模式 |
| 413 | `payload_too_large` | 登录 | 请求体超过 8KB |
| 415 | `unsupported_media_type` | 原生 REST | Content-Type 不支持 |
| 422 | `validation_failed` | 多处 | 参数/语义校验失败 |
| 422 | `graph_query_not_ready` | 图查询 | 图谱仍在构建 |
| 422 | `graph_query_failed` | 图查询 | 图谱构建失败 |
| 429 | `rate_limited` | 多处 | 超过限流 |
| 429 | `login_rate_limited` | 登录 | 登录失败次数过多 |
| 500 | `internal_error` | 多处 | 服务内部错误 |
| 502 | `retrieval_failed` | Agent | 检索整体失败 |
| 502 | `answer_failed` | Agent | 生成失败 |
| 502 | `upstream_unavailable` | 图谱检索 / `/query` | 上游失败 |
| 502 | `knowledge_base_unavailable` | `/query` | 知识库服务失败 |
| 502 | `knowledge_graph_unavailable` | `/query` | 图谱服务失败 |
| 502 | `llm_unavailable` | `/query` | 生成模型失败 |
| 502 | `llm_gateway_unavailable` | `/query` | 生成网关失败 |
| 502 | `model_gateway_unavailable` | `/query` | 模型网关失败 |
| 502 | `llm_empty_content` | `/query` | 模型返回空内容 |
| 502 | `llm_empty_content_truncated` | `/query` | 模型输出被截断 |
| 503 | `answer_unavailable` | Agent | 没有可用生成模型/问答关闭 |
| 503 | `configuration_error` | Agent | 服务端配置缺失（如 pepper） |
| 503 | `agent_key_store_unavailable` | Agent | Key 存储不可用 |
| 503 | `knowledge_base_not_imported` | `/query` | 知识库未导入 |
| 503 | `no_llm_available` | `/query` | 没有可用 LLM |
| 503 | `rerank_endpoint_not_configured` | `/query` | 重排端点未配置 |
| 503 | `rerank_model_not_configured` | `/query` | 重排模型未配置 |


*文档结束。本文对应契约版本 2.3.0，当前版本。*
