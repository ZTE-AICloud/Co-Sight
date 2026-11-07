# 验收脚本

可重复执行的验收脚本，补充单测覆盖不到的真实链路（需要运行中的栈或真实模型端点）。
全部脚本只依赖 Python 3 标准库（个别需要 `requests` / `PyYAML`，见各脚本头部）。

> 验收分层、错误分支判据、边界夹具与缺陷回归闭环见
> [`docs/acceptance-handbook.md`](../../docs/acceptance-handbook.md)。脚本只覆盖接口层，
> 页面反馈、错误恢复、视觉与版本可追溯由该手册统一定义。

## 契约与质量门禁

| 脚本 | 验的是 | 依赖 |
|---|---|---|
| `generate-rkb-openapi.py` | 从 FastAPI 全量路由生成 `contracts/openapi/rkb-api.yaml`；`--check` 只比对不写文件 | PyYAML；可直接 import 主应用 |
| `verify-agent-openapi.py` | 运行时 Agent OpenAPI 与 `contracts/openapi/agent-api.yaml` 逐字段比对 | PyYAML；可直接 import 子应用 |
| `exposure-audit.py` | 入口暴露审计：前端文件/路由可达性、后端端点消费方、废弃 API 封装、注释/开关/TODO | 标准库；后端端点审计需能 import 主应用 |
| `style-parity.py` | 前端样式与 5173 原型对齐：组件内重复的全局规则、私有 token 词汇（`--ux-*`/`--ds-*`）、全局样式文件差异；`--pairs` 附加成对文件的规则差异 | 标准库；需本地 `rag-studio-ui-demo/src` |

```bash
python3 tools/verify/generate-rkb-openapi.py --check
python3 tools/verify/exposure-audit.py --check
```

样式对齐体检（`--demo` 指向本地 5173 原型工程）：

```bash
python3 tools/verify/style-parity.py --demo ../rag-studio-ui-demo/src
python3 tools/verify/style-parity.py --demo ../rag-studio-ui-demo/src --pairs
```

硬性失败只有两类：**组件里整条复制了全局已提供的规则**，以及**使用未定义的私有
token 词汇（`--ux-*`/`--ds-*`）或在组件内重定义 `--rs-*`**。全局样式文件的差异只
打印（base/tables/workspaces 允许带注释的增量）。
⚠️ 原型工程以 `rag-studio-ui-demo` 的 **git HEAD** 为准（0.1.12+；
`package.json` 里的 0.1.9 是旧值），线上已实现到 0.1.13。`--pairs` 的成对差异
对原型尚未覆盖的新页面只作参考，不要据此回改线上。

`exposure-audit.py` 的白名单在 `exposure-allowlist.txt`（每行
`kind | key | 理由 | review-by`）；过期或未命中的条目会让 `--check` 失败。

## 接口与编排

| 脚本 | 验的是 | 依赖 |
|---|---|---|
| `verify-orchestration.py` | 建流 → 存画布 → 发布 → `POST /query`（改写→检索→重排→合成）+ 反向用例 | 运行中的栈；标准库 |
| `verify-workflow-templates.py` | 顺序 / 混合 / 条件三种模板：建流 → 画布体检 → 模拟保存 → 发布 → `/query` | 运行中的栈；标准库 |
| `verify-multi-turn.py` | 同一 `conversation_id` 的追问接上上文；换新会话问同一句应答非所问（对照组） | 运行中的栈；标准库 |
| `verify-model-registry.py` | 模型注册、连接测试、启停与保存即生效 | 运行中的栈 + 真实模型端点 |
| `verify-startup-lifecycle.py` | 启动/停机、后台任务与健康检查 | 容器环境 |
| `verify-empty-bootstrap.sh` | 空卷首次启动：建库、建管理员、健康检查 | docker compose |

## Agent

| 脚本 | 验的是 | 依赖 |
|---|---|---|
| `verify-agent-api.py` | 401/403/422/404、列库、检索引用、answer、未知路径 404 problem | `requests` + 运行中的栈 + 测试 Key |
| `verify-agent-mcp.py` | initialize / tools/list / 五个工具 / 无 Key 401 | 容器内 `mcp` 客户端 |
| `verify-agent-admin.py` | Key 管理接口：建 → 用 → 停用 → 启用 → 编辑 → 删除；含过期/未知 scope 负例 | `requests` |
| `bootstrap-agent-key.sh` | 用容器内 CLI 创建一个测试 Key 并导出环境变量 | 运行中的栈 |

## 图谱

| 脚本 | 验的是 | 依赖 |
|---|---|---|
| `verify-graph-extract-e2e.py` | 抽图全链路（建库 → 抽取 → 实体/关系落库） | 容器内 Python + 模型端点 |
| `verify-graph-vector-retrieval.py` | 图谱向量检索：`graph_<uuid>_vector` → `POST /retrieval/graph` | 容器内 Python |
| `verify-graph-workflow-chat-e2e.py` | 建流绑图谱库 → 发布 → 问答 → 带历史的追问 | 容器内 Python |
| `verify-graph-write-path.py` | 实体/边写接口与查询同步 | 运行中的栈 |

## 存储

| 脚本 | 验的是 | 依赖 |
|---|---|---|
| `verify-minio-storage-e2e.py` | MinIO 后端上传 / 下载 / 删除 | `--profile minio` 起的栈 |

> `verify-orchestration.py` 自己拼一份手写画布去验编排链路（模板坏了也照样过）；
> `verify-workflow-templates.py` 不写画布，只验建流模板播种出来的默认画布。
> 改模板时跑后者，改编排时跑前者。
