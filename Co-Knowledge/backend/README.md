# rag-knowledge-base（后端）

FastAPI 服务，监听 **8091**；对外路由统一挂在 **`/api/co-knowledge/v1`** 下
（`src/shared/prefixes.py` 是前缀的单点定义）。负责知识库、文档解析与切片、
检索、知识图谱、检索编排、问答、模型注册表、Agent 接入与本地账号鉴权。

完整架构见 [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)，技术说明见
[`docs/TECHNICAL-GUIDE.md`](../docs/TECHNICAL-GUIDE.md)，接口契约见
[`docs/api-reference.md`](../docs/api-reference.md)。

## 系统要求

- Python **3.11.18**（镜像固定该 patch 版本）
- PostgreSQL 16 + pgvector 0.8.7（业务表、向量表与图谱 JSONB 表）
- OpenSearch 2.19.6 + `analysis-ik`（关键词与全文索引）
- 一个 OpenAI 兼容的 embedding 端点；问答另需生成端点（重排可选）

## 本地运行

```bash
pip install -r requirements.lock
export PYTHONPATH=$PWD/src
export RKB_DB_PASSWORD=...
python src/main.py
```

主要环境变量（完整清单见 [`deploy/.env.example`](../deploy/.env.example)，逐项说明见
[`docs/TECHNICAL-GUIDE.md`](../docs/TECHNICAL-GUIDE.md) §6）：

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `KNOWLEDGE_BASE_PORT` / `KNOWLEDGE_BASE_HOST` | 监听端口 / 地址 | `8091` / `0.0.0.0` |
| `STORAGE_MAIN_PATH` | 运行期数据根目录 | `<服务目录>/data` |
| `LOG_DIR` | 日志目录 | `<work_dir>/logs` |
| `RKB_DB_HOST` / `RKB_DB_PORT` / `RKB_DB_NAME` | 业务库地址 / 端口 / 库名 | compose 注入 `postgresql` / `5432` / `rag_studio` |
| `RKB_DB_USER` / `RKB_DB_PASSWORD` | 业务库用户 / 口令 | 空 / 空 |
| `RKB_ES_HOST` / `RKB_ES_PORT` / `RKB_ES_USERNAME` / `RKB_ES_PASSWORD` | OpenSearch 连接 | `opensearch` / `9200` / 空 / 空 |
| `RKB_KBASE_STORAGE_PATH` | 知识库文件域本地卷根 | `/data/kb` |
| `RKB_STORAGE_BACKEND` | 文件域后端 | `local`（可选 `minio`） |
| `AUTH_MODE` | `local` / `gateway` / `none` | compose 为 `local`；代码未设置时 `none` |
| `RKB_SECRET_KEY` / `RKB_SECRET_KEY_FILE` | 模型注册表凭据加密密钥 / 密钥文件 | 空 / `/data/rkb/secret.key` |
| `RKB_AGENT_KEY_PEPPER` | Agent API Key 的 pepper | 空（使用 Agent 接口时需设置） |
| `SENSITIVE_WORDS_FILE` | 敏感词表路径 | `config/sensitive_words.txt` |

模型端点通过 `MODEL_GATEWAY_URL` / `GENERATION_GATEWAY_URL` / `RERANK_URL`
等变量注入，运行期也可在「模型管理」页注册并覆盖。

## 测试

```bash
# 纯单测（不需要数据库 / 搜索引擎）
PYTHONPATH=src pytest -q

# 全仓（前端 vitest + 后端 pytest，容器内跑）
bash ../tools/run-tests.sh
```

当前基线：**2,261 passed / 7 deselected**（本机约 70s）。`pytest.ini` 的
`testpaths = tests`；`src/ingestion/tests` 是需要真实解析链与沙箱子进程的集成用例，
不随默认套件收集。

## 项目结构

```text
src/
├── main.py / app.py / http_api.py / startup.py   # 入口与应用装配
├── infrastructure/   # 配置、数据库、HTTP、日志、存储、搜索
├── shared/           # 前缀、problem、错误、切片模型、i18n
├── knowledge_base/   # 知识库、目录、文档、切片、任务队列
├── graph/            # 图谱 schema、抽取、导入、查询、导出、图谱检索
├── operators/        # 算子注册、导入、模板、沙箱、系统算子
├── operator_api/     # 算子插件接口（operator_api）
├── workflow/         # 工作流画布、校验、发布、模板
├── engine/           # RAG 运行时（改写 → 检索 → 重排 → 合成）
├── chat/             # /query、SSE、多轮会话、证据、查询轨迹
├── model/            # 模型注册表、网关客户端、思考配置
├── agent/            # Agent REST / MCP / API Key
├── auth/             # 本地账号、会话与 CLI
├── ingestion/        # 解析 → 清洗 → 切分 → 抽图管线
├── parsing/          # 纯格式解析库（pdf/docx/pptx/excel/md/html/txt）
└── system/           # 健康检查与系统信息
```

自定义算子的公开导入面是 `operator_api`（`types/logging/storage/llm/graph`）；
沙箱实现位于 `operators/sandbox`，详见 [`docs/operator-interface.md`](../docs/operator-interface.md)。
