# Knowledge Studio 对外 API 参考（v1）

> 权威入口。实现见 `backend/src/knowledge_base/api.py`、`backend/src/workflow/router.py`、
> `backend/src/model/router.py`、`backend/src/agent/`。
> 路径前缀只有一个：**`/api/co-knowledge/v1`**。
> 机器可读契约：`contracts/openapi/rkb-api.yaml`（**全量生成**，覆盖所有运行时 REST
> 路由，含各写接口的 `requestBody` schema；生成器
> `tools/verify/generate-rkb-openapi.py`，快照测试
> `backend/tests/test_rkb_openapi_snapshot.py`）；Agent 单独见
> `contracts/openapi/agent-api.yaml`。

> **契约（2.3.0）**：不使用 `{code,bo,other}` 信封；成功体是纯 JSON，分页为
> `{items,total,page,pageSize}`，错误是真实状态码 + RFC 9457 `application/problem+json`。
> 图谱检索 `/retrieval/graph`、Agent REST `/agent/*` 与编排问答 `/query` 同样走这套契约；
> `/query` 的流式模式用标准 SSE 具名事件，`/mcp` 保持 MCP 协议。
> 链路 ID 响应头是 `X-Request-Id`；传入合法值（`[A-Za-z0-9._-]`、1–64 字符）原样沿用，
> 缺失或不合法时由服务端生成。

## 1. 约定

- **资源命名**：复数名词、kebab-case（`/knowledge-bases`、`/graph-schemas`）。
- **HTTP 语义**：`GET` 读、`POST` 创建/执行、`PUT` 整体替换、`PATCH` 局部更新、
  `DELETE` 删除。不再用 `POST /xxx/delete/{id}` 这类动作式路径。
- **归属嵌套**：目录、文档、切片、图谱内容都挂在 `/knowledge-bases/{kb_id}` 下；
  跨库资源（图谱模板、工作流、算子、模型）是顶层集合。
- **成功响应**：**没有信封**，body 就是资源本身。
  - 单资源：对象；
  - 分页：`{items, total, page, pageSize}`；
  - 非分页集合：JSON 数组；
  - 创建：`201 Created` + `Location`（相对路径）；
  - 异步：`202 Accepted`，body 为 `{taskId}` 或 `{accepted: true}`；
  - 删除/无返回：`204 No Content`；
  - 下载/导出：`application/octet-stream`。
- **分页**：请求参数 `page`（从 1 开始）、`size`；响应 `{items, total, page, pageSize}`
  （单文档切片额外带 `nameChain`）。
- **排序**：`sort=key:asc,key2:desc`。
- **筛选**：简单字段用查询参数；集合字段逗号分隔（如 `categories=1,10`）。
- **请求体**：写接口（`POST`/`PUT`/`PATCH`）的请求体见各节下的「请求体」小节。
  JSON 接口要求 `Content-Type: application/json`；`multipart/form-data` 接口会注明
  表单字段名（如上传文档是 `files` + `metadata`）。表中「必填」指字段必须出现且非空。
- **错误响应**：真实 HTTP 状态码 + RFC 9457 `application/problem+json`：

  ```json
  {
    "type": "urn:ragstudio:problem:knowledge_base_not_found",
    "title": "Knowledge base not found",
    "status": 404,
    "detail": "知识库不存在",
    "instance": "/api/co-knowledge/v1/knowledge-bases/nope",
    "code": "knowledge_base_not_found"
  }
  ```

  `title` 是稳定英文；`detail` 按 `Accept-Language` 本地化。客户端按 `code` 分支，
  不要依赖 HTTP 200 里的业务码（旧 `{code,bo,other}` 信封已于 2.0.0 移除）。
  常见状态码：`400` 绑定/畸形请求、`401/403` 鉴权、`404` 不存在、`409` 冲突、
  `413` 过大、`415` 媒体类型、`422` 语义校验、`429` 限流、`500` 服务器、
  `502` 上游、`503` 暂不可用。
- **鉴权**：
  - `AUTH_MODE=none`（开发默认）：由网络隔离承担鉴权；
  - `AUTH_MODE=local`（推荐）：除 `GET /health`、`GET /auth/status`、
    `POST /auth/login`、`POST /auth/logout` 外，所有 REST 端点都要求
    `ragstudio_session`（HttpOnly Cookie）。未登录/会话过期返回 `401`
    + problem+json（`code` 为 `unauthorized` 或 `session_expired`）；
    首次登录强制改密期间只放行 `/auth/me`、`/auth/password`，其余返回
    `403 password_change_required`；
  - `AUTH_MODE=gateway`：由前置网关校验并注入身份头（`X-Auth-Value` /
    `X-Auth-Token` / `Authorization` 任一非空即放行）。
  - Agent 侧 `/agent/*` 与 `/mcp` 始终使用 API Key，不受浏览器会话影响。
- **健康检查**：`GET /health` 返回纯文本 `ok`。
- **协议端点（不属于 REST 错误契约）**：`/mcp` 按 MCP Streamable HTTP 标准处理
  （JSON-RPC / `isError` 语义），`/health` 固定返回 `text/plain: ok`。这是协议本身
  的规定，与 REST 错误契约分开处理。`POST /retrieval/graph`、`/agent/*` 与
  `POST /query` 都走统一 REST 契约；请求 ID 在 `X-Request-Id` 响应头里（与请求头同名）。
- **SSE（`POST /query`，`stream=true` 或 `Accept: text/event-stream`）**：
  标准具名事件，每帧一个 JSON `data:`：
  `event: retrieval` → `{conversation_id,evidence}`；`evidence` 含
  `{query,items,stats}`，可选 `timings`（`understandingMs` / `retrievalMs` /
  `vectorRetrievalMs` / `keywordRetrievalMs` / `rerankMs`，毫秒，未启用的阶段缺 key；
  `retrievalMs` 是检索合计，后两个是混合检索的分项；详见 `docs/query-trace-persistence.md`）；
  `event: token` → `{conversation_id,content}`；
  `event: done` → `{conversation_id,finish_reason}`（终态）；
  `event: error` → RFC 9457 problem + `conversation_id`（终态；HTTP 已是 200）。
  出第一字节前的失败仍是真实状态码 + problem+json。心跳是注释行（`: keep-alive`）。

## 2. 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 全栈唯一健康检查（纯文本 `ok`） |
| GET | `/system/info` | 部署信息：`{deployedBy, ais}` |
| GET | `/system/embedding-models` | 可用 embedding 注册名列表 `["..."]` |
| GET | `/system/llm-models` | 可用大模型 `[{value, label}]` |
| GET | `/system/rerank-models` | 可用重排模型 `[{value, label, isDefault}]`（画布「重排模型」下拉；与运行期解析同源） |
| GET | `/system/file-size-limits?category=1` | 上传大小/数量上限 |

## 3. 知识库

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/knowledge-bases` | 列表/检索。参数：`page`、`size`、`keyword`、`categories`、`embeddingModel`、`sort` |
| GET | `/knowledge-bases/stats` | 按分类汇总（指标卡用）：`{categories:[{category,total,fileTotal,statusCounts}]}`；参数 `categories=1,10` |
| POST | `/knowledge-bases` | 建库；图谱库加 `?type=graph` |
| GET | `/knowledge-bases/{kb_id}` | 文档库详情 |
| PATCH | `/knowledge-bases/{kb_id}` | 改名称/描述等元数据 |
| DELETE | `/knowledge-bases/{kb_id}` | 删库（成功 204；库内仍有文件时 409 `knowledge_base_not_empty`） |
| GET | `/knowledge-bases/{kb_id}/graph` | 图谱库详情 `{schemaInfo, data, fileInfo, stats}`；`stats` 为全量 `{entityCount, edgeCount}` |
| PUT | `/knowledge-bases/{kb_id}/graph` | 重抽/更新图谱库内容（multipart） |

### 3.1 建库 `POST /knowledge-bases`

文档库与图谱库共用同一个 DTO，**服务端链路由查询参数决定**：

- `POST /knowledge-bases`（不带参数）→ 文档库（v1 链路，`category` 固定按 1 处理，
  请求体里的 `category` 被忽略）；
- `POST /knowledge-bases?type=graph` → 图谱库（v2 链路，**必须同时传 `category: 10`**；
  漏了会建成 `category=1` 的库，画布上的图谱检索器就查不到它）。

```json
{
  "name": "product-manual",
  "description": "产品手册",
  "headIcon": "",
  "kbtype": "document",
  "category": 1,
  "props": {"embeddingModel": "Qwen3-Embedding-0.6B"}
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 2–30 字符；允许中文、字母、数字、`_ . -` 与空白；不能全空白。同名规则见下 |
| `description` | string \| null | 否 | ≤ 1000 字符 |
| `headIcon` | string \| null | 否 | ≤ 255 字符 |
| `kbtype` | string | 否 | 子类型标识，默认 `document`；不用于区分文档库/图谱库 |
| `category` | integer | 图谱库必填 | `1` 文档库、`10` 图谱库（默认 1） |
| `props` | object | **是** | 建库属性；只认 `props.embeddingModel`（其余键被丢弃） |
| `props.embeddingModel` | string | **是** | embedding 注册名，决定向量维度 |

**同名规则**：文档库链路下，同名且**该库没有文件**时直接复用（连同向量表与索引），
只有「同名且有文件」才返回 `409 knowledge_base_exists`；图谱库链路同理，
但复用前会校验 `category` 与表名前缀一致。

**缺 `props` 不是 422**：建库时解引用 `props`，缺失走 NPE 路径，返回
`500 internal_error`。文档库成功返回完整 `KbaseVO`；图谱库（v2）返回窄 VO——
26 个键都在场，但只有 `id` / `pkId` / `name` / `headIcon` / `type` 有值。

> 图谱库不建 ES 索引、不建默认目录；文档库两者都会建。

### 3.2 更新 `PATCH /knowledge-bases/{kb_id}`

```json
{"name": "product-manual-v2", "description": "新版产品手册", "headIcon": ""}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 否 | 出现且非空白才更新；约束与建库相同；与其它库重名 `409 knowledge_base_exists` |
| `description` | string \| null | 否 | 出现即更新；空串表示清空；≤ 1000 |
| `headIcon` | string \| null | 否 | 出现即更新；≤ 255 |

三个字段都不出现时接口返回成功但不改任何行。成功返回 `204 No Content`。

## 4. 内容（目录 / 文档 / 切片）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/knowledge-bases/{kb_id}/directories` | 目录后代；参数：`parentId`、`type`、`sort` |
| POST | `/knowledge-bases/{kb_id}/directories` | 建目录，body `{title, parentId}` |
| GET | `/knowledge-bases/{kb_id}/directories/{directory_id}` | 目录详情 |
| GET | `/knowledge-bases/{kb_id}/documents` | 整库文档分页；参数：`keyword`、`page`、`size`（≤100） |
| POST | `/knowledge-bases/{kb_id}/documents` | 上传文档（multipart：`files` + `metadata`） |
| DELETE | `/knowledge-bases/{kb_id}/documents/{document_id}` | 删除文档 |
| GET | `/knowledge-bases/{kb_id}/documents/{document_id}/content` | 下载原文件 |
| GET | `/knowledge-bases/{kb_id}/documents/{document_id}/chunks` | 单文档切片（含 `nameChain`） |
| GET | `/knowledge-bases/{kb_id}/chunks` | 全库切片分页；参数：`keyword`、`page`、`size` |
| POST | `/knowledge-bases/{kb_id}/chunks` | 手工新增切片，body `{documentId, content, supplement}` |

### 4.1 建目录 `POST /knowledge-bases/{kb_id}/directories`

```json
{"title": "手册", "parentId": "0f3c…"}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 是 | 2–30 字符；允许中文、字母、数字、`_ . -` 与空白；不能全空白 |
| `parentId` | string \| null | 否 | 父目录 ID；省略/空串 = 根目录 |

- 同一父目录下重名 → `409 directory_exists`；同级文件夹数或层级超限 → `422 limit_exceeded`。
- 成功 `201` + `Location`。

### 4.2 改目录名 `PATCH /knowledge-bases/{kb_id}/directories/{directory_id}`

```json
{"title": "新目录名"}
```

`title` 出现且非空、与原名不同才更新；空名或同名直接返回当前对象（不报错）。
只能改 `type=folder` 的节点。

### 4.3 上传文档 `POST /knowledge-bases/{kb_id}/documents`

`multipart/form-data`，两个表单字段：

| 表单字段 | 必填 | 说明 |
|---|---|---|
| `files` | 是 | 文件，可重复出现（支持一次传多个） |
| `metadata` | 是 | JSON **字符串**，键见下表 |

`metadata` 内层：

| 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `directoryId` | string | 是 | 目标目录 ID；空 → `422`（聚合校验文案）；不存在 → `404 directory_not_found` |
| `kType` | string | 是 | 文件类型，通常是 `outer-document` |
| `splitType` | string | 是 | 切分方式，前端默认 `system` |
| `kbaseId` | string | — | 会被路径里的 `{kb_id}` **覆盖**，传不传都一样 |
| `coverFlag` | boolean | 否 | `true` 时同名文件覆盖；默认 `false`（同名 `409 file_name_conflict`） |
| `splitOperator` | object | 是 | 切分算子配置；整个键缺失走 NPE 路径（`500`） |
| `parseOperator` | object | 否 | 解析算子配置 |
| `category` | integer | 否 | 知识库分类；图谱库（`10`）跳过算子校验 |

```bash
curl -sS -b cookies.txt \
  -F 'files=@overview.md' \
  -F 'metadata={"directoryId":"<DIR_ID>","kType":"outer-document","splitType":"system","kbaseId":"<KB_ID>","coverFlag":false,"splitOperator":{"args":[]}}' \
  "$BASE/knowledge-bases/<KB_ID>/documents"
```

成功返回 `{文件名: fileId}`；上传后由后台任务解析/切分（见 `GET /knowledge-bases/{kb_id}/documents` 的 `status`）。

### 4.4 移动文档 `PATCH /knowledge-bases/{kb_id}/documents`

```json
{"ids": ["<DOC_ID_1>", "<DOC_ID_2>"], "parentId": "<TARGET_DIR_ID>"}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ids` | string[] | 是 | 文档 ID 列表；去重后不能为空 |
| `parentId` | string | 是 | 目标文件夹 ID；不存在 → `404 directory_not_found` |

成功返回 `{"moved": 2}`；目标目录已有同名文档 → `409 file_name_conflict`。

### 4.5 手工新增切片 `POST /knowledge-bases/{kb_id}/chunks`

```json
{"documentId": "<DOC_ID>", "content": "切片正文", "supplement": "补充文本"}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `documentId` | string | 是 | 所属文档 ID |
| `content` | string | 是 | 切片正文；用于生成向量 |
| `supplement` | string | 否 | 补充/展开文本；缺省回落 `content` |

成功 `201` + `Location`，body `{"chunkId": "…"}`。

## 6. 检索

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/retrieval` | 向量/关键词/混合检索（可跨多个库） |
| POST | `/retrieval/graph` | 图谱向量检索（种子节点 + 深度传播）；成功体为结果对象 `{base_results,...}` |
| POST | `/query` | 编排问答；默认纯 JSON 回答；`stream=true` 时标准 SSE（token/retrieval/done/error） |
| GET | `/query-traces` | 查询链路耗时列表；过滤 `workflowId/conversationId/traceId/orgId/status/from/to`，分页 `page/size` |
| GET | `/query-traces/stats` | 按 `bucket=hour|day` 聚合 P50/P95/P99、命中率；默认最近 7 天 |
| GET | `/query-traces/{id}` | 单条查询追踪明细（内部 bigint id） |

`/query-traces*` 只返回指标（阶段耗时、命中数/来源数/最高分、状态），不返回问题/
答案/证据正文；date-only 边界按 Asia/Shanghai 解释、`to` 为开区间。数据保留 30 天，
由 `tools/ops/prune-query-traces.py` 清理。详见 `docs/query-trace-persistence.md`。

### 6.1 文档检索 `POST /retrieval`

```json
{
  "question": "如何配置检索编排？",
  "type": 0,
  "model": "Qwen3-Embedding-0.6B",
  "bases": [
    {
      "baseList": ["doc_0123456789abcdef0123456789abcdef"],
      "priority": 1,
      "top_k": 8,
      "score_threshold": 0.0
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 检索问题，不能为空白 |
| `type` | integer | 否 | `0` 向量（默认）、`1` 关键词；显式传 `null` → `422` |
| `model` | string | 否 | embedding 注册名；向量路使用，缺省用部署默认模型 |
| `bases` | array | 是 | 检索分组，不能为空数组 |
| `bases[].baseList` | string[] | 是 | base 名列表；文档库格式 `doc_<kb_id>` |
| `bases[].priority` | integer | 否 | 0–10；按优先级从高到低。**缺失不会报错**，但分组失败导致返回空数组 |
| `bases[].top_k` | integer | 否 | 每个 base 条数，1–80，默认 8 |
| `bases[].score_threshold` | number | 否 | 0–1，仅向量路生效，默认 0 |

- 成功返回数组 `[{baseName, docs:[{chunkId, content, score, sourceDocId, metadata}]}]`。
- 内部异常被收敛成 `200 + []`（与「没命中」同形），**不会**返回 5xx；需要区分
  「部分失败」请用 `/agent/search`（带 `degraded` 与 `warnings`）。
- 绑定/校验失败才是真错误：`400 malformed_request`、`415 unsupported_media_type`、
  `422 validation_failed`。

### 6.2 图谱检索 `POST /retrieval/graph`

```json
{
  "query": "Alice",
  "embedding": "Qwen3-Embedding-0.6B",
  "bases": ["graph_0123456789abcdef0123456789abcdef"],
  "seed_k": 5,
  "depth": 1,
  "limit": 1000,
  "score": 0.0,
  "labels": ["Person", "Knows"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 自然语言查询，不能为空白 |
| `embedding` | string | 是 | embedding 注册名，不能为空白 |
| `bases` | string[] | 是 | 图谱 base 名，格式 `graph_<kb_id>`；不能为空 |
| `seed_k` | integer | 否 | 种子节点数，1–50，默认 5 |
| `depth` | integer | 否 | 传播深度，1–10，默认 1 |
| `limit` | integer | 否 | 返回实体数上限，1–1000，默认 1000 |
| `score` | number | 否 | 种子相似度阈值，0–1，默认 0 |
| `labels` | string[] | 否 | 实体/边标签前置过滤，最多 10 个非空字符串 |

成功返回 `{base_results: [...], total_entities, total_edges, base_count}`；
校验失败 `422`，embedding 失败 `502 upstream_unavailable`，图存储失败 `500`。

### 6.3 编排问答 `POST /query`

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

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 用户问题，不能为空 |
| `conversation_id` | string | 是 | 会话 ID；同一 ID 共享多轮上下文。缺失 → `422` |
| `workflow_id` | string | 实际必填 | **已发布**工作流 ID；默认值 `default_workflow_id` 通常不存在 |
| `stream` | boolean | 否 | `true` 时返回 SSE（也可用 `Accept: text/event-stream` 触发） |
| `include_retrieval` | boolean | 否 | `true` 时返回本轮检索依据（非流式的 `retrieval` / SSE 的 `retrieval` 事件） |
| `chat_history` | array | 否 | 显式多轮历史，元素 `{question, answer}`；优先级高于服务端进程内记忆 |
| `kwargs` | object | 否 | 运行时高级参数，支持 `question_length_limit`（正整数） |

- 只接受已发布快照；未发布/不存在 → `404 published_workflow_not_found`。
- 非流式成功体 `{conversation_id, answer, placeholder, citation, retrieval?}`；
  `stream=true` 时按标准 SSE 事件 `retrieval` / `token` / `done` / `error` 输出（见 §1）。
- 机器对机器建议改用 `POST /agent/query`（API Key + `workflow:run`，响应更精简）。

## 7. 图谱

### 7.1 模板（schema）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/graph-schemas` | 模板列表 |
| POST | `/graph-schemas` | 新建模板 |
| POST | `/graph-schemas/import` | 导入模板文件 |
| GET | `/graph-schemas/{schema_id}` | 模板详情 |
| PATCH | `/graph-schemas/{schema_id}` | 更新模板 |
| DELETE | `/graph-schemas/{schema_id}` | 删除模板 |

**请求体（`POST /graph-schemas`、`PATCH /graph-schemas/{schema_id}` 同形）：**

```json
{
  "schema_id": "General_Schema",
  "schema_name": "General_Schema",
  "schema_desc": "通用图谱模板",
  "entities": [
    {
      "entity_type": "Person",
      "entity_desc": "人",
      "properties": [
        {"name": "entity_name", "type": "STRING", "desc": "名称", "is_primary": true, "is_embedding": true, "is_index": true}
      ]
    }
  ],
  "edges": [
    {
      "edge_type": "Knows",
      "edge_desc": "认识",
      "direction": "directed",
      "source_entity": "Person",
      "target_entity": "Person",
      "properties": [
        {"name": "relationship_description", "type": "STRING", "desc": "关系描述", "is_embedding": true, "is_index": false}
      ]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_id` | string | 建模板时实际必填 | 模板 ID；创建时**不传会 500**（INSERT 绑的是 DTO 的空值，撞 NOT NULL） |
| `schema_name` | string | 是 | 模板名；重名在创建/改名时都是 `409` |
| `schema_desc` | string | 是 | 描述，1 字符以上且不能全空白 |
| `entities` | array | 是 | 实体类型，**不能为空数组**；元素 `entity_type`、`entity_desc`、`properties[]` |
| `entities[].entity_desc` | string | 是 | 实体类型描述 |
| `entities[].properties[]` | array | 是 | 属性非空；`name`、`type`（`STRING` / `INTEGER` / `FLOAT` …）、`desc`、`is_primary`、`is_embedding`、`is_index`；至少一个 `is_primary: true` |
| `edges` | array | **必须出现** | 可为 `[]`，但**不能缺键**（缺失走 NPE → `500`）；元素 `edge_type`、`edge_desc`、`direction`、`source_entity`、`target_entity`、`properties[]` |
| `edges[].edge_desc` | string | 是 | 边类型描述 |
| `edges[].source_entity` / `target_entity` | string | 是 | 必须已在 `entities` 中声明 |

`entities` 缺失或为空都返回 `422 validation_failed`；`edges` 则**必须出现**——
缺键会走 NPE 路径返回 `500`，空数组 `[]` 才是合法的「没有边类型」。
创建成功返回 `{"schema_name": "..."}`；`PATCH` 时路径里的 `schema_id` 会覆盖请求体同名字段。

**导入（`POST /graph-schemas/import`）：** `multipart/form-data`，表单字段
`schema_file`（JSON 文件）。

### 7.2 建库与导入

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/graph-extractions` | 抽图建库（multipart：`file` + `data`） |
| POST | `/graph-imports` | 导入图谱数据包（multipart：`file`） |

**`POST /graph-extractions` 的表单字段：**

| 表单字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | 源文件，可重复（一次多份） |
| `data` | 是 | JSON **字符串**，结构见下 |

`data` 内层：

```json
{
  "name": "product-graph",
  "description": "产品知识图谱",
  "category": 10,
  "props": {"embeddingModel": "Qwen3-Embedding-0.6B"},
  "operatorId": 12,
  "schemaId": "General_Schema",
  "coverFlag": true,
  "kwargs": {}
}
```

| 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 库名，约束同建库 |
| `description` | string | 否 | ≤ 1000 |
| `category` | integer | 是（实际） | 建图谱库传 `10` |
| `props` | object | 是 | `{embeddingModel}`；`props: {}` 会落到默认模型 |
| `operatorId` | integer | 是 | 抽图算子 ID；不存在或超长 → `422` |
| `schemaId` | string | 是 | 图谱模板 ID；不存在 → `422` |
| `kwargs` | object | 否 | 算子动态参数（LLM 配置等） |
| `coverFlag` | boolean | 否 | 默认 `false` |
| `fileFormat` / `regexList` / `pythonPath` / `diskFileKey` / `kbtype` | — | 否 | 兼容字段，普通调用不需要 |

成功 `202` + `Location: /api/co-knowledge/v1/knowledge-bases/{id}/graph`；
`data` 解析失败是 `422 validation_failed`（`detail` 为 JSON 解析文案），不是 400。

**`POST /graph-imports`**：表单字段 `file`（图谱数据包 zip），成功 `202`。
**`PUT /knowledge-bases/{kb_id}/graph`**（重抽）：表单字段 `data`（JSON 字符串，
结构同上）、`deleteFiles`（JSON 数组字符串）、`localFiles`（JSON 数组字符串）三者必填，
`files` 可选（可重复）；成功 `202`。更新只改名称/描述/props，`category` 不会改库分类。

### 7.3 单库图内容

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/knowledge-bases/{kb_id}/graph/query` | 图查询（entity/edge/path/sub_graph） |
| POST | `/knowledge-bases/{kb_id}/graph/entities` | 新建实体 |
| PATCH | `/knowledge-bases/{kb_id}/graph/entities/{entity_id}` | 更新实体 |
| DELETE | `/knowledge-bases/{kb_id}/graph/entities/{entity_id}?entityType=` | 删除实体 |
| POST | `/knowledge-bases/{kb_id}/graph/edges` | 新建边 |
| PATCH | `/knowledge-bases/{kb_id}/graph/edges/{edge_id}` | 更新边 |
| DELETE | `/knowledge-bases/{kb_id}/graph/edges/{edge_id}?edgeType=` | 删除边 |
| GET | `/knowledge-bases/{kb_id}/graph/export` | 导出图谱 zip |

**详情里的全量计数：** `GET /knowledge-bases/{kb_id}/graph` 返回的 `stats` 是
`{entityCount, edgeCount}`，直接数 `graph_<id>_vertex` / `graph_<id>_edge` 的物理行，
**不受查询类型、关键词或 `limit` 影响**。文档库、图谱表尚未建立或计数失败时为 `null`；
图谱已建但为空时是 `{entityCount: 0, edgeCount: 0}`。

**图查询 `POST /knowledge-bases/{kb_id}/graph/query`：**

```json
{
  "query_type": "entity",
  "filters": [{"entity_type": ["Person"], "properties": {"name": ["Alice"]}}],
  "depth": 1,
  "direction": "both",
  "limit": 100,
  "offset": 0,
  "keyword": "Ali"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query_type` | string | 是 | `entity` / `edge` / `path` / `sub_graph` |
| `filters` | array | 否 | 过滤条件；元素键见下（同时接受 snake_case 与 camelCase） |
| `depth` | integer | 否 | 子图深度，1–100 |
| `direction` | string | 否 | 子图方向，默认 `both`；`both` / `in` / `out` |
| `limit` | integer | 否 | 1–1000，默认 100 |
| `offset` | integer | 否 | ≥ 0，默认 0 |
| `cursor` | string | 否 | 游标分页，优先于 `offset` |
| `keyword` | string | 否 | 按实体名称/ID/描述模糊匹配（本项目扩展字段） |

`filters[]` 可用键：`entity_type`、`edge_type`、`properties`、`start_entity_type`、
`start_entity_properties`、`start_entity_rid`、`path_entity_type`、
`path_entity_properties`、`path_edge_type`、`path_edge_properties`。类型类字段必须是
**数组**（传字符串 → `422`）；属性过滤的值也可以是数组（任一匹配）。
成功返回 `{entities, edges, paths, entity_num, edge_num, total, has_more, offset, limit, next_cursor}`。

**新建实体 `POST /knowledge-bases/{kb_id}/graph/entities`：**

```json
{
  "entityId": "Person_1",
  "entityType": "Person",
  "properties": {"entity_name": "Alice", "age": 34},
  "edgeInfo": {
    "edgeId": "Knows_1",
    "edgeType": "Knows",
    "currentEntityId": "Person_2",
    "direction": "out",
    "properties": {"since": "2024"}
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `entityId` | string | 是 | 格式 `{实体类型}_{序号}`；与类型不匹配 → `422` |
| `entityType` | string | 是 | 必须是模板里声明过的实体类型 |
| `properties` | object | 是 | 实体属性；`entity_name` 通常必填（模板 `is_primary`） |
| `edgeInfo` | object | 否 | 建实体的同时建一条边；`edgeId`、`edgeType`、`currentEntityId`、`direction`、`properties` |

成功 `201`，返回 `{success, msg, entityId, entityType, ...}` 形状的结果对象。

**更新实体 `PATCH /knowledge-bases/{kb_id}/graph/entities/{entity_id}`：**

```json
{"entityType": "Person", "properties": {"age": 35}}
```

`entityId` 由路径给出；`entityType` 与 `properties` 必填，只更新给出的属性键。

**新建边 `POST /knowledge-bases/{kb_id}/graph/edges`：**

```json
{
  "edgeId": "Knows_1",
  "edgeType": "Knows",
  "sourceId": "Person_1",
  "targetId": "Person_2",
  "properties": {"since": "2024"}
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `edgeId` | string | 是 | 格式 `{边类型}_{序号}` |
| `edgeType` | string | 是 | 必须已声明；`source_entity` / `target_entity` 需与两端类型一致 |
| `sourceId` / `targetId` | string | 是 | 两端实体 ID；实体必须已存在 |
| `properties` | object | 是 | 边属性（可按模板为空对象） |

**更新边 `PATCH /knowledge-bases/{kb_id}/graph/edges/{edge_id}`：**
`{"edgeType": "Knows", "properties": {"since": "2025"}}`；`edgeId` 来自路径。

> 实体/边写操作成功后，已发布/发布中的库（`status` 为 6/7）会被标成
> 「已发布后有改动」（`status=8`）；其它状态保持不变。工作流要重新发布才会用上新数据。

## 8. 算子

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/operators` | 分页列表；参数：`page`、`size`、`keyword`、`module`、`visibility`、`format` |
| POST | `/operators` | 导入算子包（multipart：`file`） |
| GET | `/operators/types` | 算子类型枚举 |
| GET | `/operators/template?type=` | 下载算子模板 |
| GET | `/operators/available?module=&format=` | 按格式取「已发布 + 系统」算子（建库快速配置） |
| GET | `/operators/supported?module=` | 按环节取可运行算子（画布） |
| GET | `/operators/{operator_id}` | 算子详情 |
| DELETE | `/operators/{operator_id}` | 删除算子 |
| POST | `/operators/{operator_id}/publish` | 发布 |
| DELETE | `/operators/{operator_id}/publish` | 取消发布 |
| PUT | `/operators/{operator_id}/visibility` | 可见性，body `{public: true|false}` |
| GET | `/operators/{operator_id}/export` | 导出算子包 |

**导入算子 `POST /operators`：** `multipart/form-data`，表单字段 `file`（算子包 zip）。
成功 `201` + `Location`，返回算子详情（含新 `id`）。同名算子返回 `409 operator_name_conflict`，
非 zip → `415 unsupported_media_type`，超过导入大小上限 → `413 payload_too_large`。

**可见性 `PUT /operators/{operator_id}/visibility`：**

```json
{"public": true}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `public` | boolean | 是 | `true` 公开、`false` 私有；不是布尔 → `422` |

成功 `204 No Content`（发布/取消发布两条端点同样返回 `204`，无请求体）。

## 9. 工作流

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/workflows` | 分页列表；参数：`page`、`size`、`keyword`、`publishType`（0/1/2） |
| POST | `/workflows` | 创建工作流（建流即播种默认画布） |
| GET | `/workflows/knowledge-bases` | 画布/对话页的知识库下拉（`{running, dev}`） |
| PATCH | `/workflows/{workflow_id}` | 更新名称/描述等 |
| DELETE | `/workflows/{workflow_id}` | 删除工作流 |
| GET | `/workflows/{workflow_id}/flow` | 读取画布草稿 |
| PUT | `/workflows/{workflow_id}/flow` | 保存画布草稿 |
| POST | `/workflows/{workflow_id}/validate` | 保存前校验 |
| GET | `/workflows/{workflow_id}/publication` | 读取已发布快照 |
| POST | `/workflows/{workflow_id}/publication` | 发布 |
| GET | `/workflows/{workflow_id}/export` | 导出画布 JSON |

`GET /workflows/{workflow_id}/flow` 的响应在画布字段之外带 `publishType`
（0 未发布 / 1 已发布 / 2 发布后修改）：画布据此提示「保存只更新草稿，
对话测试运行的是已发布快照」。保存草稿不改变已发布快照，改完要再发布一次。

### 9.1 建流 `POST /workflows`

```json
{
  "workFlowId": "RAG_Workflow_1a2b",
  "name": "产品手册问答",
  "template": "Sequential",
  "knowledgeType": "knowledgeBase",
  "description": "客服机器人",
  "boundInfo": {
    "running": [
      {
        "name": "product-manual",
        "type": "document",
        "tableName": "doc_0123456789abcdef0123456789abcdef",
        "embeddingModel": "Qwen3-Embedding-0.6B"
      }
    ],
    "dev": []
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `workFlowId` | string | 是 | 也可用 `workflowId` / `appId`；**大写 F**；≤128 且只允许 `[A-Za-z0-9_]`；重复 → `409 workflow_exists` |
| `name` | string | 是 | 工作流名称，≤255，不能全空白 |
| `template` | string | 是 | `Sequential` / `Blended` / `Conditional`；≤64；空值 → `422 validation_failed`（不支持的名字 → `unsupported_template`） |
| `knowledgeType` | string | 否 | 通常 `knowledgeBase` |
| `description` | string | 否 | 描述，≤1000 |
| `boundInfo` | object | **是（实际）** | 绑定的知识库，按分组 `running` / `dev` 放数组；元素至少带 `tableName`、`embeddingModel`、`type` |

**建流即播种默认画布**（四段算子 + 连线）。以下组合会**直接失败**，不会建出跑不起来的流：

- 一个知识库都没绑 → `422 validation_failed`（`detail` 为「画布未绑定知识库」）；
- 绑了结构化库 → `422 unsupported_knowledge_base_type`；
- 混选不同 embedding 模型的库 → `422 embedding_model_conflict`；
- 取不到 `embeddingModel` → `422 unknown_embedding_model`；
- `Sequential` / `Conditional` 绑图谱库 → `422 unsupported_knowledge_base_type`
  （模板里没有图谱检索节点）；`Blended` 绑图谱库会自动切到
  `Blended_graph` / `Blended_normal_graph` 变体。

成功 `201` + `Location`，返回工作流 VO。

### 9.2 更新 `PATCH /workflows/{workflow_id}`

```json
{"name": "产品手册问答 v2", "template": "Blended", "knowledgeType": "knowledgeBase", "description": "新描述"}
```

`name` 必填；**`boundInfo` 不在这里更新**（不传不等于清空，传了也无效）——绑定关系随画布保存。

### 9.3 保存画布 `PUT /workflows/{workflow_id}/flow`

```json
{
  "flowType": "workflow",
  "version": 3,
  "nodeConfigDTOList": [
    {
      "id": "9ff1431c-d75b-488c-ac35-a07a65d1a9d7",
      "data": {
        "type": "displayData",
        "variables": {
          "retriever": [
            {
              "id": "9ff1431c-d75b-488c-ac35-a07a65d1a9d7_4f1",
              "operator": "FusionRetriever",
              "package": "core.rag.retriever.fusion_retriever",
              "kwargs": {"top_k": 30, "embedding": "Qwen3-Embedding-0.6B"}
            }
          ]
        }
      },
      "label": "RE-a42",
      "ports": {"items": []},
      "position": {"x": 120, "y": 80},
      "size": {"width": 264, "height": 346}
    }
  ],
  "otherNodeConfigList": [
    {
      "componentType": "QUERY_ENGINE",
      "variables": {
        "queryengine": {
          "id": 0,
          "operator": "BlendedQueryEngine",
          "package": "core.rag.query_engine.blended_query_engine",
          "kwargs": {}
        }
      },
      "inputVariables": []
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `flowType` | string | 否 | 画布类型，通常 `workflow` |
| `version` | integer | 否 | 前端回传的版本号；**保存草稿不使用它**（只有发布推进版本） |
| `nodeConfigDTOList` | array | 是 | 可视节点；**不能为空**。每个节点是前端 X6 结构，`data.variables` 内放算子 `{id, operator, package, kwargs}` |
| `otherNodeConfigList` | array | **是（实际）** | 非可视节点；必须包含查询引擎（`componentType: "QUERY_ENGINE"`），否则 `422 validation_failed` |

- 最省事的做法：把 `GET /workflows/{workflow_id}/flow` 的结果改完原样回传。
- 保存**只做结构性校验**，不拦「跑不起来」；画布为空或超过大小上限都是 `422 validation_failed`。
- 成功返回 `{"version": n}`（草稿版本号，不推进）。

### 9.4 保存前校验 `POST /workflows/{workflow_id}/validate`

请求体与保存画布**同形**。返回：

```json
{"success": false, "message": "画布缺少可运行的检索器"}
```

`success=false` **不是错误**（HTTP 200）：结构错误才是 `4xx/5xx`，运行期风险只作为提示，
前端据此弹「仍然保存？」。

### 9.5 发布 `POST /workflows/{workflow_id}/publication`

无请求体。把当前草稿写成**不可变快照**（`GET .../publication` 可读），版本号 +1，
`publishType` 置 1。跑不起来的画布在这里被硬拒（`422`）；成功 `201` + `Location`。

## 10. 模型注册表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/models` | 列表（`kind`/分页） |
| POST | `/models` | 新建 |
| GET | `/models/thinking-presets` | 思考配置预设 |
| POST | `/models/test` | 测试未保存的配置 |
| GET | `/models/{model_id}` | 详情 |
| PUT | `/models/{model_id}` | 更新 |
| DELETE | `/models/{model_id}` | 删除 |
| POST | `/models/{model_id}/test` | 测试已保存模型 |

### 10.1 新建 `POST /models`

```json
{
  "modelKind": "llm",
  "modelName": "qwen3-32b",
  "displayName": "Qwen3 32B",
  "apiModel": "qwen3-32b",
  "baseUrl": "https://llm.example.com/v1",
  "apiKey": "sk-…",
  "chatPath": "/chat/completions",
  "dimension": null,
  "maxTokens": 4096,
  "temperature": 0.2,
  "timeout": 120,
  "isReasoning": true,
  "thinkingMode": "auto",
  "isDefault": false,
  "enabled": true,
  "remark": ""
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `modelKind` | string | 是 | `llm` / `embedding` / `rerank` |
| `modelName` | string | 是 | 注册名（同 kind 下唯一，重名 `409 model_name_conflict`） |
| `displayName` | string | 否 | 展示名；缺省同 `modelName` |
| `apiModel` | string | 否 | 上游真实模型名；缺省按 `modelName` 调上游 |
| `baseUrl` | string | 是 | 上游 base URL（http/https）；非法 → `422` |
| `apiKey` | string | 否 | 加密存储；读取接口永远不回明文 |
| `chatPath` | string | 否 | 默认 `/chat/completions` |
| `embeddingsPath` | string | 否 | 默认 `/embeddings` |
| `modelsPath` | string | 否 | 默认 `/models` |
| `rerankPath` | string | 否 | 默认 `/rerank` |
| `dimension` | integer | embedding 必填 | 向量维度；与库内向量表必须一致 |
| `maxTokens` / `temperature` / `timeout` | number | 否 | 生成参数与超时（秒；缺省回落部署的 `generation_timeout`） |
| `isReasoning` | boolean | 否 | 是否为推理模型 |
| `thinkingMode` | string | 否 | LLM 专用：`none`（默认）/ `auto` / `preset` / `custom` |
| `thinkingPreset` | string | `preset` 时必填 | 预设 ID，取自 `GET /models/thinking-presets` |
| `thinkingPayload` | object | `custom` 时必填 | 思考参数对象（非空 JSON） |
| `isDefault` | boolean | 否 | 是否默认模型；`enabled=false` 时会被强制忽略 |
| `enabled` | boolean | 否 | 默认 `true` |
| `remark` | string | 否 | 备注 |

成功 `201` + `Location`。

### 10.2 更新 `PUT /models/{model_id}`

**部分合并**语义：请求里出现的键才改。`modelKind` / `modelName` / `baseUrl` 仍按合并后的值校验。
`apiKey` 有两个特例：

- 缺席或空串 → **保持原值**（编辑页拿不到明文，不能把空当清空）；
- 显式 `{"clearApiKey": true}` → 清空。

成功返回更新后的模型对象（不含明文密钥）。

### 10.3 连接测试

**未保存配置 `POST /models/test`**：请求体与 `POST /models` 同形，但 `modelName` 可省略
（缺省用 `probe`）；`modelKind`、`baseUrl` 仍必填，embedding 仍要求 `dimension`。

**已保存模型 `POST /models/{model_id}/test`**：请求体可为空对象；也可带
`baseUrl` / `chatPath` / `embeddingsPath` / `modelsPath` / `rerankPath` / `apiKey` 覆盖。
**安全约束**：没有同时提供 `apiKey` 时，服务端会丢弃这四个路径与 `baseUrl`，
按库里的配置测试 —— 防止用已保存的密钥去请求任意主机。

响应（失败也不抛错，HTTP 200）：

```json
{
  "ok": true,
  "probed": true,
  "models": ["qwen3-32b"],
  "chatOk": true,
  "chatError": "",
  "rerankOk": null,
  "rerankError": "",
  "dimension": null,
  "dimensionMatches": null,
  "latencyMs": 812,
  "message": "model call succeeded; 12 model(s) reported by endpoint"
}
```

`ok` 只由真实调用决定（LLM 看 `chatOk`、rerank 看 `rerankOk`）；`probed` 表示端点是否
提供模型清单。`ok=false` **不是**拒绝保存的依据。

## 11. Agent 接入

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/agent-keys` | Key 列表 / 创建 |
| GET | `/agent-keys/status` | 管理面鉴权状态 |
| GET | `/agent-keys/stats` | 调用量指标：累计调用量 / 最近 7 天请求数 |
| PATCH/DELETE | `/agent-keys/{key_prefix}` | 更新 / 删除 Key |
| GET | `/agent/knowledge-bases` | Agent 视角的知识库列表（裸数组） |
| GET | `/agent/knowledge-bases/{kb_id}` | Agent 视角的知识库详情（对象） |
| POST | `/agent/search` | Agent 检索（成功体 `{query,mode,results,...}`） |
| POST | `/agent/answer` | Agent 问答（成功体 `{answer,citations,...}`） |
| GET | `/agent/workflows` | 工作流分页列表（`page`/`size`/`keyword`/`publishType`；Scope `workflow:read`） |
| POST | `/agent/query` | 执行已发布工作流（Scope `workflow:run`；JSON / SSE） |
| — | `/mcp` | MCP Streamable HTTP（4 个只读工具 + 1 个工作流执行工具 `run_workflow`） |

Agent REST 与本节其它端点共用错误契约（`application/problem+json` + 真实状态码）；
`X-Request-Id` 只在响应头（与请求头同名），成功/错误 body 都不再包 `trace_id`/`data`。

### 11.1 创建 Agent Key `POST /agent-keys`

```json
{
  "name": "ci-bot",
  "description": "CI 集成",
  "scopes": ["kb:list", "kb:search", "kb:answer"],
  "kbIds": [],
  "rateLimitPerMin": 60,
  "expiresAt": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | ≤128，不能全空白 |
| `description` | string | 否 | ≤200 |
| `scopes` | string[] | 是 | 至少一个，取值见下；未知 scope → `422` |
| `kbIds` | string[] | 否 | 知识库白名单；`[]`/省略 = 全部文档库 |
| `rateLimitPerMin` | integer | 否 | 每分钟请求上限，缺省 60；`0` 表示不限，最大 100000 |
| `expiresAt` | string \| null | 否 | ISO 8601 或 `YYYY-MM-DD`（表示当天结束，UTC）；`null`/省略 = 永不过期；过去时间 → `422` |

可用 scope：`kb:list`、`kb:search`、`kb:answer`、`workflow:read`、`workflow:run`。

成功 `201` + `Location: /api/co-knowledge/v1/agent-keys/{keyPrefix}`：

```json
{
  "key": {
    "keyPrefix": "ragk_5eee8626",
    "name": "ci-bot",
    "description": "CI 集成",
    "scopes": ["kb:list", "kb:search", "kb:answer"],
    "kbIds": [],
    "rateLimitPerMin": 60,
    "enabled": true,
    "expiresAt": null,
    "expired": false,
    "lastUsedAt": null,
    "createdAt": "2024-01-01T00:00:00+08:00",
    "createdBy": "admin"
  },
  "plaintextKey": "ragk_…"
}
```

**明文 `plaintextKey` 只在创建响应里出现这一次**，之后任何接口都只回前缀。

### 11.2 更新 Agent Key `PATCH /agent-keys/{key_prefix}`

部分更新，只改出现的键，可用的键是建 Key 的全部字段再加 `enabled`：

```json
{"enabled": false, "rateLimitPerMin": 120, "expiresAt": "2027-01-01T00:00:00+08:00"}
```

- `expiresAt: null` 表示**清空过期时间**（与「不传」不同）；
- 未知键直接 `422 validation_failed`（管理面拒绝未知字段）；
- 成功返回更新后的 Key 对象（不含明文）；删除 Key 返回 `200 {"keyPrefix": "…"}`。

### 11.3 检索 / 问答 / 执行工作流

| 端点 | 请求体 |
|---|---|
| `POST /agent/search` | `{query, knowledge_base_ids?, mode?, top_k?, score_threshold?}` |
| `POST /agent/answer` | `{question, knowledge_base_ids?, mode?, top_k?, model?}` |
| `POST /agent/query` | `{question, conversation_id, workflow_id, stream?, include_retrieval?, chat_history?}` |

**`POST /agent/search`：**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 1–2000 字符 |
| `knowledge_base_ids` | string[] | 否 | 省略/空 = 全部可访问文档库；去重、去空白 |
| `mode` | string | 否 | `auto`（默认）/ `hybrid` / `vector` / `keyword` |
| `top_k` | integer | 否 | 默认 8，上限部署可配（默认 20） |
| `score_threshold` | number | 否 | 0–1，仅向量路生效 |

**`POST /agent/answer`：** 字段同上，把 `query` 换成 `question`，`top_k` 表示来源数，
另可传 `model`（已注册 LLM 名；部署强制模型时忽略）。

**`POST /agent/query`：**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 1–2000 字符 |
| `conversation_id` | string | 是 | 会话 ID，≤255；同一 ID 多轮共享上下文 |
| `workflow_id` | string | 是 | **已发布**工作流 ID；不存在/未发布 → `404` |
| `stream` | boolean | 否 | `true` 返回 SSE（事件同原生 `/query`） |
| `include_retrieval` | boolean | 否 | 返回本轮检索依据 |
| `chat_history` | array | 否 | 元素 `{question, answer}` |

三个端点都拒绝未声明字段（多传 → `422 validation_failed`）；非流式成功体分别是
`{query, mode, results, degraded, warnings}`、`{answer, citations, model, usage, no_results, reason, warnings}`、
`{conversation_id, answer, retrieval?}`。

## 11.5 本地账号登录（`/auth`）

仅 `AUTH_MODE=local` 生效；`none`/`gateway` 下登录与改密返回 `409 auth_not_enabled`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/auth/status` | 公开：`{mode, initialized, authenticated, user}`；前端据此决定是否启用登录守卫 |
| POST | `/auth/login` | `{username, password}` → `200 {user}` + `Set-Cookie` |
| POST | `/auth/logout` | 撤销会话并清 Cookie；幂等 `204` |
| GET | `/auth/me` | 当前用户；未登录 `401` |
| POST | `/auth/password` | `{currentPassword, newPassword}` → `204`；撤销其它会话 |

**请求体：**

```json
// POST /auth/login
{"username": "integration-user", "password": "********"}

// POST /auth/password
{"currentPassword": "********", "newPassword": "********"}
```

| 端点 | 字段 | 必填 | 说明 |
|---|---|---|---|
| `POST /auth/login` | `username` / `password` | 是 | `username` ≤255、`password` ≤1024；`Origin`（或 `Referer`）host 必须与 `Host` 一致，否则 `403 csrf_rejected` |
| `POST /auth/password` | `currentPassword` / `newPassword` | 是 | 新密码 8–128 字符、不能含控制字符；成功 `204` 并撤销其它会话 |
| `POST /auth/logout` | 无 | — | 幂等；无有效会话也返回 `204` |

`user = {username, displayName, email, role, mustChangePassword}`（永不含口令哈希）。
Cookie：`ragstudio_session`，`HttpOnly; Path=/; SameSite=Lax; Max-Age=<ttl>[; Secure]`。
登录/改密错误码：`invalid_credentials`(401)、`account_disabled`(403)、
`login_rate_limited`(429，带 `Retry-After`)、`auth_not_initialized`(503)、
`password_policy`/`invalid_current_password`(422)、`csrf_rejected`(403)。
`/auth/login` 与 `/auth/password` 的请求体上限 8KB（nginx `/auth/` 8k + 后端检查），
超出返回 `413 payload_too_large`。
对外部脚本，登录后拿不到 token（HttpOnly）；机器访问请使用 Agent API Key。
