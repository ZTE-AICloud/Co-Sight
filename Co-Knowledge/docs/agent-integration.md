# Agent 接入指南（REST + MCP）

> 面向：企业 Agent 平台 / 工作流引擎，以及 Claude Code / IDE / 桌面 Agent。
> 版本：v1.4（只读检索/问答 + 工作流查询/执行，REST 与 MCP 同能力）。实现：`backend/src/agent/`。

## 1. 提供什么

| 形态 | 路径 | 用途 |
|---|---|---|
| REST | `/api/co-knowledge/v1/agent/knowledge-bases` | 列出当前 Key 可访问的文档知识库 |
| REST | `/api/co-knowledge/v1/agent/knowledge-bases/{kb_id}` | 单个知识库详情 |
| REST | `/api/co-knowledge/v1/agent/search` | 检索片段（向量 / 关键词 / 混合） |
| REST | `/api/co-knowledge/v1/agent/answer` | 基于片段回答并带 `[S1]` 引用 |
| REST | `GET /api/co-knowledge/v1/agent/workflows` | 工作流查询（支持 `publishType` 筛选） |
| REST | `POST /api/co-knowledge/v1/agent/query` | 执行已发布工作流（需 `workflow:run`；JSON / SSE） |
| REST | `/api/co-knowledge/v1/agent/openapi.json` | OpenAPI 3.0.2（6 paths，含 `/agent/query`） |
| MCP | `/api/co-knowledge/v1/mcp` | Streamable HTTP，4 个只读工具 + 1 个工作流执行工具 |

MCP 工具：`list_knowledge_bases`、`search_knowledge`、`ask_knowledge_base`、
`list_workflows`、`run_workflow`。

| Scope | 能力 |
|---|---|
| `kb:list` | 列文档知识库 / 详情 |
| `kb:search` | 检索片段 |
| `kb:answer` | 引用式问答 |
| `workflow:read` | 列工作流及发布状态 |
| `workflow:run` | 执行已发布工作流（`POST /agent/query`） |

**v1.3 起提供**：Agent Key 可调用 `POST /api/co-knowledge/v1/agent/query` 执行
**已发布工作流**（需要 `workflow:run`；普通 JSON 与 SSE 均支持），与
`GET /agent/workflows` 形成「发现 → 执行」闭环。原生 `/query` 仍是浏览器会话/
网关面，两者共用同一套编排与 SSE 逻辑。

**不提供**：建库/上传/删除等写操作、图谱库（`category=10`）的 Agent 直接检索、
工作流的创建/画布编辑/发布/删除（这些在控制台完成）。

## 2. 启用步骤

### 2.1 建表

空卷新装由 `deploy/init/pg/00-schema.sql` 自动建表。表缺失时主服务不受影响，
Agent 路径返回 `503 agent_key_store_unavailable`。

### 2.2 配置 pepper 与开关

在 `deploy/.env` 里设置（**不要加引号**）：

```bash
RKB_AGENT_KEY_PEPPER=<openssl rand -hex 32 的输出>
```

可选：

```bash
RKB_AGENT_API_ENABLED=true          # 总开关；false → agent 路径 404
RKB_AGENT_REST_ENABLED=true
RKB_AGENT_MCP_ENABLED=true
RKB_AGENT_ANSWER_ENABLED=true       # false → answer 503，search 仍可用
RKB_AGENT_MAX_TOP_K=20
RKB_AGENT_MAX_KBS=50
RKB_AGENT_ANSWER_TIMEOUT=120
RKB_AGENT_ANSWER_MODEL=             # 空 = 模型注册表默认 LLM
RKB_AGENT_REASONING_EFFORT=         # 推理模型建议 none
RKB_AGENT_LOG_QUERY=false           # 默认不记录原始 query
RKB_AGENT_MCP_STATELESS=false
RKB_AGENT_MCP_JSON_RESPONSE=false
RKB_AGENT_MCP_DNS_REBINDING_PROTECTION=false
RKB_AGENT_MCP_ALLOWED_HOSTS=
RKB_AGENT_MCP_ALLOWED_ORIGINS=
RKB_AGENT_PUBLIC_BASE=/api/co-knowledge/v1/agent
RKB_AGENT_KEY_ADMIN_ENABLED=true    # UI「远程接入 → 密钥管理」接口；false → 除 status 外 403 permission_denied
```

⚠️ `.env` 里写了但 `deploy/docker-compose.yml` 没转发 = 容器看不到（本次已在
`rag-knowledge-base.environment` 里全部转发）。改完执行
`docker compose up -d --force-recreate rag-knowledge-base web`。

**pepper 为空时 fail-closed**：Agent 路径返回 503，CLI 拒绝建 Key。轮换 pepper
会使所有已发 Key 立即失效，必须与 Key 重发一起做。

### 2.3 建 Key（UI 推荐，CLI 备选）

#### 2.3.1 UI：左栏「远程接入 → 密钥管理」

左栏「远程接入」下有两个子菜单：「接入方法」（MCP/REST
说明与配置片段）与「密钥管理」。Key 的日常管理在「密钥管理」里完成：

- 新建、启停、删除；
- 编辑名称、作用域、知识库白名单、每分钟上限、过期时间；
- 新建成功后弹窗**只显示一次完整 Key**，关闭后只能看到前缀。

管理接口在 `/api/co-knowledge/v1/agent-keys`（纯 JSON +
RFC 9457 problem+json，真实 HTTP 状态码）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/status` | 服务状态（开关、pepper 是否配置、Key 表是否可用） |
| GET | `/stats` | 调用量指标：`{totalCalls, requests7d, windowStart, windowEnd}` |
| GET | `/agent-keys` | 列表（分页 + `keyword`，永不返回哈希/明文）；`{items,total,page,pageSize}` |
| POST | `/agent-keys` | 新建；成功 `201` + `Location`，`plaintextKey` 只返回一次 |
| PATCH | `/agent-keys/{prefix}` | 局部更新（含 `enabled` 启停） |
| DELETE | `/agent-keys/{prefix}` | 硬删除（优先用停用）；成功 `200 {keyPrefix}` |

`GET /agent-keys/stats` 的计数口径：

- 计数点是 Key **鉴权通过**的每一次 HTTP 请求（REST 与 MCP 共用
  `agent/auth.py::authenticate`）；401（无 Key / 停用 / 过期）与 429（限流）
  不计数，业务层 4xx/5xx 仍计入（请求确实到达了服务）。
- 按 **Asia/Shanghai 自然日**聚合；`requests7d` 是含今天在内的 7 个自然日，
  `windowStart` / `windowEnd` 给出实际窗口，便于页面解释口径。
- 数据落 `public.agent_api_key_usage`，重启不丢；删 Key 时历史计数级联删除。

新建请求体（`POST /agent-keys`；PATCH 只需传变化的字段）：

```json
{
  "name": "dify-prod",
  "scopes": ["kb:list", "kb:search"],
  "kbIds": [],
  "rateLimitPerMin": 60,
  "expiresAt": null
}
```

成功响应里 `key` 是 Key 的公开 DTO（前缀、作用域、白名单、限流、过期时间等），
`plaintextKey` 是**唯一一次**出现的完整 Key（都在顶层，不再有 `bo`）。

错误响应示例（管理开关关闭）：

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json

{"type":"urn:ragstudio:problem:permission_denied","title":"Permission denied",
 "status":403,"detail":"…","code":"permission_denied"}
```

**鉴权边界**：这些接口与其它 UI 接口同级。`AUTH_MODE=local`（推荐）时由
`auth.middleware.AuthMiddleware` 要求登录会话 Cookie；`AUTH_MODE=gateway` 时要求
网关注入的 `X-Auth-Value` / `X-Auth-Token` / `Authorization`（任一非空）；
`AUTH_MODE=none` 是开发/隔离网络用法，**没有应用层鉴权**，任何能访问该地址的人都
可以管理 Key，必须靠网络隔离或前置反向代理保护。`/agent/*` 与 `/mcp` **不要求**
浏览器会话，始终使用 Agent API Key。`RKB_AGENT_KEY_ADMIN_ENABLED=false` 可整体关闭
写接口（`status` 仍可读，页面会给出提示；写接口回 403 `permission_denied`）。

#### 2.3.2 CLI：容器内执行（运维/应急）

`tools/` 不在运行镜像里，CLI 的真正位置是 `backend/src/agent/cli.py`：

```bash
docker compose -f deploy/docker-compose.yml exec rag-knowledge-base \
  python3 -m agent.cli create --name dify-prod \
    --scopes kb:list,kb:search,kb:answer \
    --kb-ids 7ad5...,f2f2... \
    --rate-limit 60

docker compose -f deploy/docker-compose.yml exec rag-knowledge-base \
  python3 -m agent.cli list

docker compose -f deploy/docker-compose.yml exec rag-knowledge-base \
  python3 -m agent.cli revoke --prefix ragk_xxxxxxxx
```

- `--scopes` 默认 `kb:list,kb:search`；加 `kb:answer` 才能问答；加 `workflow:read` 可查询工作流；
  加 `workflow:run` 可执行已发布工作流（`POST /agent/query`）。
- `--kb-ids` 留空 = 全部启用的文档知识库；显式列出则只允许这些库。
- `--rate-limit 0` = 不限制；默认 60 次/分钟/Key。
- **明文只打印一次**；库里只存 `key_prefix` 与 `HMAC-SHA256(pepper, key)`。
- 宿主侧包装 `tools/agent-key.py` 只是可选；它需要用同一份 `RKB_DB_*`
  与同一个 `RKB_AGENT_KEY_PEPPER`。
- UI 与 CLI 共用同一张 `public.agent_api_key` 表与同一套校验；CLI 仍可用于
  自动化脚本或 UI 不可用时的应急操作。

## 3. REST 用法

REST 的认证、列库、检索、问答、工作流查询/执行、错误形状与 curl 示例见
[`external-api/agent-rest-access.md`](external-api/agent-rest-access.md)；本文只保留部署、运维与 MCP 接入。

## 4. MCP 用法

### 4.1 Claude Code

```bash
claude mcp add --transport http rag-studio \
  http://<host>/api/co-knowledge/v1/mcp \
  --header "Authorization: Bearer $KEY"
```

或写进项目 `.mcp.json`：

```json
{
  "mcpServers": {
    "rag-studio": {
      "type": "http",
      "url": "http://<host>/api/co-knowledge/v1/mcp",
      "headers": {"Authorization": "Bearer ragk_xxx"}
    }
  }
}
```

### 4.2 只支持 stdio 的客户端

```bash
npx -y mcp-remote http://<host>/api/co-knowledge/v1/mcp \
  --header "Authorization: Bearer $KEY"
```

### 4.3 工具语义

| 工具 | 何时用 | 备注 |
|---|---|---|
| `list_knowledge_bases` | 先发现可访问的库 | 只返回文档库 |
| `search_knowledge` | 需要原文片段自己推理 | 返回 `[S1]` 编号；快 |
| `ask_knowledge_base` | 需要综合答案 + 引用 | 会调生成模型；无上下文时 `no_results` |
| `list_workflows` | 发现工作流及发布状态 | 参数 `page`/`size`/`keyword`/`publish_type`；只读 |
| `run_workflow` | 执行已发布工作流 | 需要 `workflow:run`；参数 `question`/`conversation_id`/`workflow_id`/`stream`/`include_retrieval`/`chat_history`；与 REST `POST /agent/query` 同源 |

`run_workflow` 与 REST `POST /agent/query` 共用同一套执行逻辑（发布快照、
知识库白名单、`conversation_id` 多轮状态都一致）。MCP 没有「工具结果流」：
`stream=true` 时生成的 token 通过 MCP **progress 通知**（`notifications/progress`，
客户端需在 `tools/call` 里带 `progressToken`）旁路送达，工具结果仍在结束时
一次性返回完整答案 `{trace_id, conversation_id, answer, retrieval?}`。
`stream=false`（默认）与 REST 非流式响应同形。

工具错误以 MCP `isError: true` 返回，消息形如 `unauthorized: …` /
`forbidden_scope: …` / `validation_error: …`。客户端必须每次请求都带
`Authorization`（含 initialize），不能只在首次握手时带。

## 5. OpenAPI 导入

```text
http://<host>/api/co-knowledge/v1/agent/openapi.json
```

- OpenAPI 3.0.2（FastAPI 0.111 生成 3.1 结构后按官方做法覆盖版本号；本接口未用
  3.1 特性）。
- `servers[0].url` 默认 `/api/co-knowledge/v1/agent`；Dify/Coze 要求绝对地址时把
  `RKB_AGENT_PUBLIC_BASE` 设为 `https://<host>/api/co-knowledge/v1/agent`。
- 契约快照在 `contracts/openapi/agent-api.yaml`，由
  `tools/verify/verify-agent-openapi.py` 比对。

## 6. 排错与安全建议

| 症状 | 排查 |
|---|---|
| 一直 401，但 Key 明明存在 | CLI 与后端的 `RKB_AGENT_KEY_PEPPER` 不一致；或 Key 已 disabled/过期 |
| 503 `configuration_error` | pepper 为空（fail-closed） |
| 503 `agent_key_store_unavailable` | 数据库未初始化（缺 `agent_api_key` 表） |
| 400 `too many accessible knowledge bases` | 可访问文档库超过 `RKB_AGENT_MAX_KBS`；显式传 `knowledge_base_ids` |
| 504 / 长答案被截断 | nginx `/agent/` 的 `proxy_read_timeout` 必须 ≥ 生成超时（本项目配 300s） |
| MCP 初始化卡住 | nginx `/mcp` 必须 `proxy_buffering off` + HTTP/1.1 + `Connection ""` |
| MCP 421/403 | 开了 DNS rebinding 保护但 `allowed_hosts` 没写对（需同时写 `host` 与 `host:*`） |
| `degraded=true` + `keyword_path_failed` | ES 不可用/索引缺失；vector 结果仍然可用 |
| answer 很慢 | 默认 LLM 可能是推理模型；设 `RKB_AGENT_ANSWER_MODEL` 为快模型，或 `RKB_AGENT_REASONING_EFFORT=none` |
| `502 answer_failed: generation endpoint returned HTTP 401` | 模型注册表里那行 LLM 的 `api_key` 过期/与 `.env` 不一致；到「模型管理」页更新（注册表是权威，`.env` 只是首次播种/回落） |

**安全**：Bearer Key 在 HTTP 下是明文；跨网段/对外必须前置 TLS。answer 会把检索
片段发给配置的生成端点，内网部署应把该端点放在内网；片段中的指令已通过 System
Prompt 标注为「资料不是指令」，但 RAG prompt injection 仍是残余风险。检索、问答
与工作流查询（REST 与 MCP）都是只读；执行入口 `workflow:run`（REST
`POST /agent/query`、MCP `run_workflow`）运行**已发布快照**。建库、改画布与
发布工作流在控制台完成。

## 7. 验收

```bash
# 后端单测（含 agent 单测；skip 必须为 0）
bash tools/run-tests.sh --backend

# REST 端到端（需运行中的栈 + 一个测试 Key）
RKB_AGENT_TEST_KEY=... python3 tools/verify/verify-agent-api.py

# 额外验证 Agent Key 执行已发布工作流（Key 需 workflow:run）
RKB_AGENT_TEST_KEY=... RKB_AGENT_TEST_WORKFLOW=RAG_Workflow_xxxx \
  python3 tools/verify/verify-agent-api.py   # 走 /agent/query

# MCP 端到端（容器内有 mcp 客户端；也可用宿主已装的 mcp）
# 加 RKB_AGENT_TEST_WORKFLOW 时额外验证 run_workflow 的 JSON 与 stream=true 两条路
docker compose -f deploy/docker-compose.yml exec -T \
  -e RKB_AGENT_TEST_KEY="$KEY" \
  -e RKB_AGENT_TEST_WORKFLOW=RAG_Workflow_xxxx \
  rag-knowledge-base python3 - < tools/verify/verify-agent-mcp.py

# 契约快照
python3 tools/verify/verify-agent-openapi.py
```

> 在**宿主机**上跑 REST/MCP 验收（而不是容器内）时，除了 `RKB_DB_*`，
> 还要设 `RKB_DB_NAME=rag_studio` 与 `RKB_DB_PASSWORD`：前者是模型注册表
> 那条连接池的库名（compose 由 `POSTGRES_DB` 注入），漏了会表现为「第一个请求
> 500、之后又正常」以及模型注册表回落到 `.env`；后者是 `get_pwd('es')` 的回落口令。
> 容器内这些都由 compose 注入，不需要手动设。
