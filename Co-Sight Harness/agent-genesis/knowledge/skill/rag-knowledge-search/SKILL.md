---
name: rag-knowledge-search
description: "基于 co-knowledge Agent API 的知识检索 skill：输入问题，返回带检索证据的答案。适用于系统操作、配置、故障排查等已被知识库覆盖的问题。"
---

# RAG 知识搜索 Skill

## 用途

通过 co-knowledge 的 Agent 查询接口检索领域知识，返回答案与检索证据。

适用于：

- 系统操作、配置说明
- 故障排查、告警处置
- 产品文档、流程规范等已入库内容

不适用于：通用聊天、代码生成、知识库覆盖范围之外的话题。

## 前置条件

- co-knowledge 服务可达，且已配置可用的 Agent API Key：
  - 首选：框架「知识库路由设置」中的生效路由（`routeUrl` + API Key），脚本自动读取；
  - 兜底：环境变量 `CO_KNOWLEDGE_BASE_URL` + `CO_KNOWLEDGE_API_KEY`；
  - 缺省地址 `http://localhost:4910`。
- `workflow_id` 对应的 RAG 工作流已在 co-knowledge 中**发布**（Agent API 只执行已发布工作流）。
- 本机 Python 3.9+（无第三方依赖，仅用标准库）。

## 调用方式

以子进程方式调用，stdin 传 JSON，stdout 收 JSON：

```bash
echo '{"question":"如何配置告警阈值？"}' \
  | python .claude/skills/rag-knowledge-search/scripts/execute.py
```

带多轮会话标识：

```bash
echo '{"question":"第二步具体怎么做？","conversation_id":"conv-001"}' \
  | python .claude/skills/rag-knowledge-search/scripts/execute.py
```

## 输入 Schema

```json
{
  "type": "object",
  "properties": {
    "question": {
      "type": "string",
      "description": "需要借助知识库回答的问题"
    },
    "conversation_id": {
      "type": "string",
      "description": "会话唯一标识，用于多轮上下文；未提供时脚本自动生成 UUID"
    },
    "dialogue_id": {
      "type": "string",
      "description": "已废弃：旧字段，作为 conversation_id 的别名兼容；新调用请用 conversation_id"
    },
    "workflow_id": {
      "type": "string",
      "description": "可选，覆盖注入的 RAG 工作流 id"
    }
  },
  "required": ["question"]
}
```

## 输出 Schema

```json
{
  "type": "object",
  "properties": {
    "success": {"type": "boolean", "description": "查询是否成功"},
    "answer": {"type": "string", "description": "基于检索知识生成的答案"},
    "conversation_id": {"type": "string", "description": "服务端返回的会话标识"},
    "dialogue_id": {"type": "string", "description": "已废弃：conversation_id 的别名，值相同"},
    "citations": {
      "type": "array",
      "description": "引用来源；服务端未返回引文时为空数组",
      "items": {
        "type": "object",
        "properties": {
          "source": {"type": "string"},
          "content_expand": {"type": "string"},
          "node_id": {"type": "string"}
        }
      }
    },
    "placeholder": {"type": "object", "description": "服务端占位信息，通常为空对象"},
    "error": {"type": ["string", "null"], "description": "失败原因；成功时为 null"},
    "retrieval": {
      "type": ["object", "null"],
      "description": "结构化检索证据（query/items/stats/timings）；服务端未返回时为 null"
    }
  },
  "required": ["success", "answer", "conversation_id", "dialogue_id", "citations", "placeholder", "error", "retrieval"]
}
```

`retrieval.items[]` 关键字段：`index`、`kind`、`kb`、`source`、`chunkId`、`score`、`text`、`truncated`。
单条 `text` 可能被服务端截断，引用时以 `source` 为准。

## 配置

地址与 API Key 逐字段解析，优先级从高到低：

| 字段 | 优先级 | 说明 |
|---|---|---|
| `base_url` | 函数参数 > 框架生效路由 `routeUrl` > `CO_KNOWLEDGE_BASE_URL` > `http://localhost:4910` | 可传根地址、`.../api/co-knowledge/v1`、`.../agent` 或完整的 `.../agent/query`，脚本自动归一 |
| `api_key` | 函数参数 > 框架生效路由 `apiKey` > `CO_KNOWLEDGE_API_KEY` > 空（报 `MISSING_API_KEY`） | 只进 `Authorization: Bearer` 头，不进 URL、日志或错误消息 |
| `workflow_id` | 函数参数 > `CO_KNOWLEDGE_WORKFLOW_ID` > 注入值 | 注入时写入；只允许 `[A-Za-z0-9_-]{1,128}` |
| `timeout` | 函数参数 > `CO_KNOWLEDGE_TIMEOUT` > `180` | 请求超时（秒） |

框架生效路由：`GET {FRAMEWORK_BASE_URL}/api/framework/v1/rag-knowledge/active`，用
`{COSIGHT_HOME}/.module-token` 的模块令牌鉴权。框架不可达或未配置时**静默**回落到环境变量。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `CO_KNOWLEDGE_BASE_URL` | `http://localhost:4910` | 知识库地址（框架路由缺失时使用） |
| `CO_KNOWLEDGE_API_KEY` | 空 | Agent API Key（框架路由缺失时使用） |
| `CO_KNOWLEDGE_WORKFLOW_ID` | 注入值 | 运行时覆盖工作流 id |
| `CO_KNOWLEDGE_TIMEOUT` | `180` | 请求超时（秒） |
| `FRAMEWORK_BASE_URL` | `http://127.0.0.1:4300` | 框架服务地址（读取生效路由） |
| `COSIGHT_HOME` | `~/.cosight-harness` | 模块令牌所在目录 |
| `FRAMEWORK_TIMEOUT_MS` | `2000` | 读取框架路由的超时（毫秒，范围 100–30000） |
| `CO_KNOWLEDGE_USE_PROXY` | `0` | 私网/本地地址默认绕过 HTTP 代理；设为 `1` 强制走代理 |

服务端调用固定为：`POST {base_url}/api/co-knowledge/v1/agent/query`，请求体：

```json
{"question": "...", "conversation_id": "...", "workflow_id": "RAG_Workflow_xxx", "stream": false, "include_retrieval": true}
```

## 失败处理

调用方（Agent）必须遵循：

1. `success=false` 时，把 `error` 原样或摘要后告知用户，**不得编造答案**。
2. 按错误前缀给出下一步建议：

| error 前缀 | 含义 | 建议 |
|---|---|---|
| `MISSING_API_KEY` | 未配置 Agent API Key | 在框架「知识库路由设置」配置 API Key，或设置 `CO_KNOWLEDGE_API_KEY` |
| `CONNECTION_ERROR` | 服务未启动或地址错误 | 确认 co-knowledge 已启动，检查 `CO_KNOWLEDGE_BASE_URL` |
| `TIMEOUT` | 请求超时 | 缩小问题范围，或调大 `CO_KNOWLEDGE_TIMEOUT` |
| `HTTP 401/403` | API Key 缺失、无效或无权限 | 检查框架生效路由中的 API Key 是否有效 |
| `HTTP 404` | 地址或工作流不存在 | 确认 `routeUrl` 路径正确、`workflow_id` 已在服务端发布 |
| `HTTP 422` | 请求参数不合法 | 按 `detail` 修正入参（如 `workflow_id`、`conversation_id`） |
| `HTTP 5xx` | 服务内部异常 | 稍后重试；持续失败请检查服务日志 |
| `CO_KNOWLEDGE_ERROR code=...` | 业务错误（HTTP 200 旧版网关形态） | 按 `message` 处理 |
| `INVALID_RESPONSE` | 响应非 JSON | 确认地址指向 co-knowledge，而非其他服务 |
| `INVALID_ARGUMENT` | 入参不合法 | 检查 `question` / `workflow_id` / `timeout` |

3. 工具本身不可用时，如实说明无法检索，不要用模型内置知识冒充检索结果。

## 实现文件

```
.claude/skills/rag-knowledge-search/
├── SKILL.md
└── scripts/
    ├── execute.py              # stdin/stdout 入口
    ├── rag_knowledge_search.py # 查询客户端（框架路由解析 + Agent API 调用）
    └── check_env.py            # 连通性自检（只读已发布工作流列表，不触发 LLM）
```

连通性自检：

```bash
python .claude/skills/rag-knowledge-search/scripts/check_env.py --json
```
