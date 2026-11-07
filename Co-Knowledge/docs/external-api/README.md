# Knowledge Studio 对外接口文档（集成面）

本目录是可直接交付给外部集成方的 API 文档包，覆盖**知识库只读、检索、问答、Agent REST 与 MCP**、**Agent 工作流查询**（`GET /agent/workflows`、MCP `list_workflows`）以及 **Agent Key 执行已发布工作流**（REST `POST /agent/query`、MCP `run_workflow`）。建库/上传/修改/删除、算子、工作流创建/画布编辑/发布/删除、模型注册、密钥管理等管理面操作由控制台提供。

其中 **REST 接入方式**另附一份可单独交付的《REST 接入指南》，对应控制台「远程接入 → 接入方法 → REST API」页面的内容。

## 文件

| 文件 | 用途 |
|---|---|
| `knowledge-studio-api.md` | 主文档源文件（Markdown），覆盖完整集成面 |
| `knowledge-studio-api.html` | **交付用**：单文件、离线可打开、带目录搜索与打印样式 |
| `agent-rest-access.md` | REST 接入指南源文件（Agent API，可单独交付） |
| `agent-rest-access.html` | REST 接入指南交付版：单文件、离线可打开 |
| `openapi/agent-api.yaml` | **交付用**：由 `contracts/openapi/agent-api.yaml` 生成的 Agent OpenAPI 3.0.2 快照，可导入 Dify/Coze 等平台 |

完整集成面发送 `knowledge-studio-api.html`；只需要 REST 接入方式时发送 `agent-rest-access.html`。需要二次编辑时改对应的 `.md` 后重新生成 HTML。浏览器打开 HTML 后可用「打印 / PDF」另存为 PDF。

## 重新生成 HTML

```bash
# 仓库根目录
node tools/docs/build-external-api-html.mjs
# 或指定文件
node tools/docs/build-external-api-html.mjs docs/external-api/knowledge-studio-api.md
node tools/docs/build-external-api-html.mjs docs/external-api/agent-rest-access.md
```

依赖 `frontend/node_modules/marked`（已在 `frontend/package.json` 声明）。生成器会把 CSS/JS 全部内联，HTML 不请求任何外部资源。

## 生成 Agent OpenAPI

交付包里的 `openapi/agent-api.yaml` 不手工维护，由契约源生成：

```bash
python3 tools/docs/build-external-agent-openapi.py
python3 tools/docs/build-external-agent-openapi.py --check   # 只校验
```

生成物只把 `info.description` 里的内部文档引用替换为对外表述，其余内容与
`contracts/openapi/agent-api.yaml` 一致。

## 契约版本

- 接口契约：`2.3.0`（`contracts/VERSION`）
- 文档版本：`2.3.0`
- Agent OpenAPI：`1.4.0`
- REST 接入指南：文档版本 `1.4.0`，对应 Agent 接口契约 `1.4.0`

## 管理面与配套文档

管理面操作（建库、上传、目录/文档/切片写操作、图谱抽取/导入/写实体、算子、工作流发布、模型注册、Agent Key 管理）由平台控制台提供；需要管理面接口时，由平台管理员在控制台操作或另行申请管理接口文档。

`/query-traces*` 返回查询链路聚合指标（P50/P95/P99 等），供运维与质量分析。

部署、运维与数据库 schema 见仓库根目录 [`README.md`](../../README.md)、[`docs/TECHNICAL-GUIDE.md`](../TECHNICAL-GUIDE.md) 与 [`docs/database-schema.md`](../database-schema.md)。
