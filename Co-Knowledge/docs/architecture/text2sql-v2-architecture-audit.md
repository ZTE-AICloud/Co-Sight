# Text2SQL V2 架构审计与技术路线差距分析

> 审计对象：`ragstudio-opensource`，HEAD `b4b1d83f`（`feat(text2sql): 运行中按真实阶段点亮查询流水线`）
> 数据库基准：**V2 17 表 DDL**（`deploy/init/pg/18-text2sql.sql` + `20-text2sql-index.sql` + `22-text2sql-cardinality.sql`）
> 审计性质：只读审计。除本文件外未修改任何业务代码、Migration、配置与前端页面。
> 取证方式：静态通读 + **干净实例 DDL 执行**（一次性 `pgvector/pgvector:0.8.7-pg16` 容器）+ **真实运行探针**（本机 Docker 栈，容器镜像 `Created 2026-11-12T12:14:44Z`，与 HEAD 同步）
> 会话交叉验证：审计期间仓库从 `8f088d2f` 前进到 `b4b1d83f`（新增 SSE 流水线）。本报告全部结论以 **`b4b1d83f` 工作树**为准；运行探针跑在该版本编译出的容器上，静态行号亦按该版本核对。

---

## 1. 审计口径

1. **V2 是唯一基准。** 目标描述的 17 张表全部存在于 `text2sql` schema；`text2sql_index` 是第 18 张（向量副本，不属于 V2 的 17 张）。
2. **区分三层完整性**：DDL 设计完整性、代码实现完整性、真实运行验证结果。本报告每个结论标注属于哪一层。
3. **不假设「表在 = 功能在」。** 17 张表全部落地，但其中 `t2s_metric`、`t2s_relation_column`、`t2s_knowledge`（METRIC/NOTE 部分）、`t2s_query_run` 的部分字段能力**没有进入生成链路**，只在存储层存在。
4. **V2 DDL 本身也要被审计。** 本报告单列 §6.4「V2 DDL 设计问题」，共 9 项，其中 3 项是「DDL 结构上无法表达目标能力」，不是代码没写。
5. **仓库在审计期间被并发修改。** 审计开始时 HEAD 为 `8f088d2f`，中途前进到 `b4b1d83f`（新增 SSE 流水线）；审计收尾时 `frontend/src/pages/text2sql/Text2SQLPage.vue` 又出现**未提交**改动（流水线面板 UI，2026-11-12 20:30 写入，非本次审计产生）。本报告的结论以**后端 `b4b1d83f`** 为准；前端相关判断基于已提交状态，不包含那笔进行中的 UI 改动。该文件未被我触碰。

---

## 2. 执行摘要

### 2.1 六维结论

| 维度 | 评级 | 一句话依据 |
|---|---|---|
| **V2 数据库设计落地程度** | **A（17/17）** | 干净实例上 18/20/22 全量执行成功；17 张表、11 个函数、13 个触发器、复合外键、状态机 CHECK 全部就位 |
| **Config Version / 原子发布** | **A-** | 实测：READY 不可变、知识冻结、版本不可删、并发发布幂等、软删数据源被 CHECK 拦住。扣分项是「发布不 bump revision」导致语义靠 UNIQUE 兜底，以及无版本 GC |
| **Schema RAG 实际成熟度** | **C（不合格）** | 知识对象齐备，但**检索结果不进 Prompt**；无 BM25 / RRF / Reranker / Column Retriever / Relation Expansion；上下文是「全量快照 + 字符截断」 |
| **Metric 能力成熟度** | **D（字段级，非语义级）** | `aggregation_behavior` 能存能改能索引，但**生成 Prompt 只带 key/名称/表达式**，可加性、时间字段、单位、过滤条件、统计归属全部丢弃；无任何代码消费 NON_ADDITIVE |
| **安全性** | **D** | 正则 Guard；实测 `query_to_xml()` 绕过白名单读系统表；无结果字节上限；数据源 CRUD 无授权（SSRF）；只读账号不校验 |
| **生产可用性** | **C-** | 3 表 12 行演示库可稳定运行；规模化路径（ANN、增量索引、版本 GC、上下文预算、Token 计量）全部缺失 |
| **通用 Operator 扩展能力** | **E（无抽象）** | 不存在 Query Operator 接口、Logical Plan、Semantic Planner；`operators/` 是文档处理沙箱算子，与查询无关 |

### 2.2 一句话定性

**「数据层已经做到 V2，执行层还停在 V1。」**

V2 的 DDL 是一份质量很高的设计（复合外键把 `datasource_id` 绑进每一级父引用、版本不可变触发器、发布审计、状态机 CHECK），代码也确实照着它落库了。但**查询侧真正影响答案的只有三件事：全量 Schema 文本、LLM、正则 Guard**。V2 引入的 Metric、Relation Column、Version Snapshot、Knowledge 索引，在生成链路里**没有一个进入 Prompt**。

### 2.3 最大的五个差距

1. **检索旁路化**：`query_service.py:120` 取 `hits`，`:126` 用 `build_context(snapshot)` —— 命中结果只进「答案依据」UI。
2. **Metric 语义在 Prompt 前被截断**：`sql_guard.py:485-491` 只输出 `key`、`businessName`、`expressionSql`；`aggregationBehavior` / `unit` / `timeColumn` / `filterDefinition` / `attributionDescription` 全丢。**`COUNT(DISTINCT user_id)` 的 NON_ADDITIVE 语义永远到不了模型。**
3. **Relation 只做文本平铺**：`t2s_relation_column` 的列对确实进了 Prompt（`sql_guard.py:456`），但没有 BFS / 最短路径 / 可信度过滤；`verified` 字段零消费者；复合关系的展示视图只取第一列对（`query_service.py:617`）。
4. **安全边界是外部库账号，不是 Guard**：实测绕过 + 无字节上限 + 无授权。
5. **可观测性是骨架**：8 个阶段里 `columns`/`values`/`relations`/`validation` 恒 0ms（SSE 实测逐帧确认），`usage` 恒 `null`，最终 Prompt 不落库，相对时间范围不存绝对起止。

---

## 3. 第一阶段：代码盘点

### 3.1 技术栈实况

| 关注点 | 实际情况 | 证据 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI；阻塞调用走 `run_in_threadpool` | `api.py:22-49` |
| 前端 | Vue 3.5.26 + Vue CLI 5（webpack 5）+ Element Plus 2.14.7 | `frontend/package.json` |
| 业务库 | PostgreSQL 16.15 + pgvector 0.8.7 | 实测 `pg_extension` |
| **连接池** | **无独立池**。`text_to_sql/db.py:12-27` 复用 `infrastructure.db.pool._db_pool.get_db_conn()`，但该函数每次新建 psycopg2 连接（`infrastructure/db/pool.py:19-28`），用完即关 | 代码 |
| **ES 客户端** | 仓内有 `infrastructure/search/elasticsearch.py:26-59`（单例）+ `es_restful.py`；**Text2SQL 零引用** | grep 全模块无 `opensearch\|elasticsearch\|infrastructure.search` |
| **Vector Store 适配器** | 文档侧 `retrieval/repository/vector_store.py`（`kb_index` 动态表）、图谱侧 `graph/repository/graph_index_store.py`（HNSW）；Text2SQL 自建 `text2sql_index.t2s_knowledge_vector`（无 ANN） | 三套并行 |
| **Embedding** | ✅ 复用 `model.gateway.embed_many` / `embed_query`；实测 `Qwen3-Embedding-0.6B` / 1024 维 | `indexer.py:14-23`、`query_service.py:101` |
| **Reranker** | 仓内有 `engine/post_retriever/external_model_reranker.py`、`llm_reranker.py`；**Text2SQL 零引用** | grep |
| **RRF** | 仓内有 `engine/retriever/fusion_retriever.py`（k=60）；**Text2SQL 零引用** | grep |
| **LLM Provider** | ✅ 复用 `model.resolver.resolve('llm')` + `model.operator_client.invoke_llm` | `query_service.py:420-470` |
| **任务队列** | 仓内有 `infrastructure/tasks/pg_queue.py`（`FOR UPDATE SKIP LOCKED` + NOTIFY，`task_center.task`）；**Text2SQL 未接入**，索引构建在 HTTP 线程内同步完成 | `service.py:382-417` |
| **权限体系** | 共享 `AuthMiddleware`（none/local/gateway）；`_require_admin` 仅 3 处 | `api.py:505`（调用点 :182 / :248 / :287） |
| **日志/Trace** | 请求级 `request_id` 落 `t2s_query_run`；无跨阶段 trace、无 Token | `18-text2sql.sql:315` |

### 3.2 模块清单

| 模块 | 实际路径 | 核心类/函数 | 真实功能 | 完成度 |
|---|---|---|---|---|
| API 层 | `backend/src/text_to_sql/api.py`（510 行） | `build_router`，**45 条路由** | REST + problem+json；含 **SSE `/query/stream`**（`:309-384`） | 95%（缺授权） |
| 数据源/目录服务 | `text_to_sql/service.py` | `Text2SqlService`（18 方法） | 校验→仓库→扫描→版本构建/发布 | 90%（同步构建） |
| 查询编排 | `text_to_sql/query_service.py`（762 行） | `Text2SqlQueryService.run_query` + `on_stage` 回调 | 检索→生成→校验→执行→落库 | 60%（检索旁路） |
| 入参/出参 | `text_to_sql/models.py`（920 行） | `parse_*` / `*_to_api` | 手工校验 + DTO | 95% |
| Schema Loader | `text_to_sql/scanner.py`（422 行） | `scan_database` / `_read_tables|columns|constraints|foreign_keys|value_profiles` | pg_catalog 只读扫描 + 低基数采样 | 90%（不采索引） |
| 目录持久化 | `text_to_sql/repository_pg.py`（684 行） | `apply_scan` / `_upsert_column` / `_apply_relations` | 增量 upsert + tombstone + **不覆盖人工语义** | 95% |
| 关系/值/指标 CRUD | `text_to_sql/catalog_repository.py`（582 行） | `create_relation` / `values` / `metrics` | 全量 CRUD + 验证状态 | 95% |
| Knowledge Builder | `text_to_sql/knowledge.py`（314 行） | `build_snapshot` / `build_knowledge` | 冻结快照 → 5 类知识对象（无 NOTE） | 85% |
| 向量化 | `text_to_sql/indexer.py` | `embed_texts` | 薄封装 | 100% |
| 版本/索引任务 | `text_to_sql/version_repository.py`（508 行） | `create_version` / `prepare_build` / `finish_build` / `publish_version` | 三段事务 + 向量写入 | 80%（同步、无 GC） |
| **Schema Retriever** | `text_to_sql/query_repository.py:81-98` | `search_knowledge` | pgvector 余弦，`version_id` 过滤，`LIMIT 24` | **25%（仅 Vector，未接生成）** |
| SQL 生成 | `query_service.py:479-529` | `_generate_sql` | 硬编码 system prompt + JSON 提取 | 70% |
| SQL Guard | `text_to_sql/sql_guard.py`（495 行） | `validate_sql` / `_mask_literals` / `_validate_table_scope` | 正则 + token + 表白名单 | **50%（非 AST）** |
| SQL Executor | `sql_guard.py:274-341` | `execute_readonly` | 只读事务 + timeout + 行上限 + EXPLAIN | 70% |
| 值解析 | `text_to_sql/value_resolver.py`（450 行） | `resolve_and_rewrite` | 查询时回库改写字面量 | 95% |
| **Context Builder** | `sql_guard.py:409-495` | `build_context` | **全量快照 + 24k 截断** | **20%** |
| 查询历史 | `query_repository.py:104-239` | `create_run` / `finish_success|failure` | 不可变运行快照 | 80%（缺 Prompt/Token/绝对时间） |
| 前端 | `frontend/src/pages/text2sql/Text2SQLPage.vue` + `features/text2sql/` | 4 工作区 + SSE 阶段条 | 查询/历史/数据源/验证反馈 | 85% |

### 3.3 真实调用链（当前 HEAD）

```text
POST /text2sql/datasources/{id}/query          api.py:300-307
POST /text2sql/datasources/{id}/query/stream   api.py:309-384  （SSE，同样落到下面）
  → Text2SqlQueryService.run_query             query_service.py:57
      emit('tables','running')                 :110
      get_active_context (版本+冻结快照)         :59
      create_run / mark_running                :97 / :103
      embed_query                              :112
      search_knowledge(version, vec, 24)       :120  ──┐ 仅用于展示
      build_context(snapshot)                  :126  ←─┘ 全量快照
      _value_hints(snapshot, question)         :132
      _generate_sql → invoke_llm               :147
      validate_sql                             :159
      value_resolver.resolve_and_rewrite       :161
      validate_sql（改写复检）                   :164
      execute_readonly(+on_phase)              :176
      finish_success/failure                   :230 / :286
```

**SSE 实测（curl 逐帧）**：`tables 67ms → columns 0ms → values 0ms → relations 0ms → llm 752ms → validation 0ms → explain 2ms → execute 0ms`。其中 `columns`、`values`、`relations`、`validation` 是纯内存操作，`relations` 阶段**没有任何代码执行**。

---

## 4. V2 数据库一致性矩阵

### 4.1 干净实例执行结果

在一次性 `pgvector/pgvector:0.8.7-pg16`（`--network none`）上按顺序执行：

| 文件 | 结果 | 说明 |
|---|---|---|
| `18-text2sql.sql` | **成功**（单事务） | 17 表 + 11 函数 + 24 触发器；循环依赖（`t2s_datasource ↔ t2s_config_version`）通过表创建后再 `ALTER TABLE ADD CONSTRAINT` 解决，顺序正确 |
| `20-text2sql-index.sql` | 首次**失败**：`type "vector" does not exist` | 依赖 `00-schema.sql:15` 的 `CREATE EXTENSION vector`；单独执行 18→20 会失败 |
| `CREATE EXTENSION vector` 后重跑 20 | **成功** | `text2sql_index` schema + 1 表 + 2 索引 |
| `22-text2sql-cardinality.sql` | **成功**（幂等） | `ADD COLUMN IF NOT EXISTS` + 守卫式 CHECK |
| 合计表数 | **18**（`text2sql` 17 + `text2sql_index` 1） | 与 V2 设计一致 |

> **结论**：DDL 本身可用、可重复部署；唯一硬约束是 `20` 不能脱离 `00` 单独执行。`docs/database-schema.md:846-850` 让已有部署「手工执行 18 和 20」，若目标库没启用 `vector` 扩展会直接失败，这是文档级隐患（见 §6.4 D9）。

### 4.2 逐表矩阵（17 张全列）

| # | 表 | V2 设计 | 当前实现 | 差距 | 优先级 |
|---|---|---|---|---|---|
| 1 | `t2s_datasource` | 多库类型、凭据引用、schema 范围、业务主题、维护人、时区、查询策略、config_revision、active_version_id、软删 | **全部齐备**。实测：软删时 CHECK 强制 `active_version_id` 先置空（V2 设计生效）。`db_type` CHECK 允许 5 种库，应用层只放行 postgresql（`models.py:15`）。`connection_options` 列**全仓零引用** | 扩展能力在 DDL 有、代码无；死列 1 个 | P2 |
| 2 | `t2s_table` | 原始注释/业务语义分离、默认不进范围、消失检测、Schema Hash、复合约束元数据、复合外键 | **全部齐备**。`enabled` 默认 `false`；`schema_hash` + `missing_since` + `constraints_metadata` 均在 `apply_scan` 维护 | 无 | — |
| 3 | `t2s_column` | 同上 + `semantic_type` + 基数 | **齐备**。`_upsert_column`（`repository_pg.py:578-605`）只更新结构列，**不覆盖** `business_name/description/aliases/semantic_type` | `last_seen_at` 无此列但 DTO 读取（`models.py:335` 恒 `None`） | P3 |
| 4 | `t2s_relation` | FK/MANUAL/INFERRED、基数、验证人/时间、复合外键、自关联 | **齐备**。实测自关联允许；`verified` 三元组 CHECK 生效 | `verified` 无任何代码消费（检索/生成都不用） | P1 |
| 5 | `t2s_relation_column` | 真实列映射、顺序、复合外键 | **齐备且强**。实测：跨数据源挂列、源列属于错误表，**均被复合外键拒绝** | 复合关系在「答案依据」只显示第一列对（`query_service.py:617`） | P2 |
| 6 | `t2s_value` | 业务值 + 别名 + 来源类型 | **齐备**。扫描自动收录 LOW 基数（≤20），人工值优先 | 无独立 Value Retriever | P1 |
| 7 | `t2s_metric` | 表达式、过滤 AST、时间字段、时区、单位、可加性、依赖字段/关系、审核 | **存储齐备**。实测 `APPROVED` 缺验证人 → CHECK 拒绝；编辑后触发器清空审核状态 | **语义不进 Prompt**（见 §5.6） | **P1** |
| 8 | `t2s_metric_column` | 指标→字段依赖 + 角色 | 表存在，CRUD 有（`catalog_repository.py:507-511`） | 仅存储，无消费者 | P2 |
| 9 | `t2s_metric_relation` | 指标→关系依赖 | 同上 | 仅存储，无消费者 | P2 |
| 10 | `t2s_config_version` | 快照、revision、内容 Hash、Embedding 模型/维度、5 状态、READY 不可变 | **全部实测通过**：PENDING 时切 READY 被拒；全 INDEXED 后成功；READY 后改 snapshot/dims/model 全部被拒；DELETE 被拒 | 无失败原因列；无 GC | P1 |
| 11 | `t2s_publication` | 发布历史 | **齐备**。由 `log_publication` 触发器在 `active_version_id` 变更时自动写入 | 无 | — |
| 12 | `t2s_knowledge` | 6 类型、版本隔离、统一 ID、Vector Namespace/Document ID、索引状态、内容 Hash | **5/6 类型实现**（`build_knowledge` 只产 TABLE/COLUMN/RELATION/VALUE/METRIC，**从不产 NOTE**）；`UNIQUE(version_id, object_type, object_key)` 防重 | `index_status` **只有一个**，无法表达 ES/Vector 双索引（DDL 层缺陷） | P0/P2 |
| 13 | `t2s_index_job` | 幂等键、attempt、worker、heartbeat、进度、失败、不可变 | **表齐备**；实测「必须从 PENDING 开始」「删除被拒」「COMPLETED 要求 processed=total」全部生效 | `idempotency_key` 含随机串、`attempt` 恒 1、无 worker 循环 | P2 |
| 14 | `t2s_query_run` | 全生命周期 + 各阶段快照 | **状态机齐备**（实测 PENDING→RUNNING→SUCCEEDED/FAILED；终态不可变）；落 `retrieval/validation/explain/result` 快照 | 无 `context_snapshot`（最终 Prompt）；`usage` 恒空；`CANCELLED` 从不产生；相对时间范围无绝对起止；历史响应不回带 versionId | P1 |
| 15 | `t2s_favorite` | 收藏 + 验证版本 + 相对/固定时间 | **齐备**。实测 `fixed` 缺 `fixed_time_range` 被 CHECK 拒绝；修改问题后触发器清空验证 | 无 | — |
| 16 | `t2s_feedback` | 反馈 + 处理状态 + 解决版本 | **齐备**（`OPEN/REVIEWING/RESOLVED` 三态 CHECK） | 前端无处理入口（只读列表） | P2 |
| 17 | `t2s_workspace` | 用户草稿与偏好 | **齐备**（`actor_id` 主键，只存草稿不存历史） | 无 | — |
| +1 | `text2sql_index.t2s_knowledge_vector` | （不在 17 表内）向量副本 | 表存在；`embedding vector` 无维度、无 ANN、`datasource_id/version_id` 无外键、`content` 重复存储 | 见 §6.4 | P1 |

**矩阵结论**：17 张表 **17/17 落地**，其中 13 张表「设计与实现一致」，4 张表（`t2s_metric`、`t2s_knowledge`、`t2s_query_run`、`t2s_relation`）存在「字段在、语义未生效」的实现层差距。

---

## 5. Schema RAG 深度审计

### 5.1 Knowledge Builder

| 检查项 | 结论 | 证据 |
|---|---|---|
| TABLE 知识 | ✅ | `knowledge.py:191-204`，标题 `schema.table`，正文含类型/DB 注释/业务名/描述/别名/字段摘要 |
| COLUMN 知识 | ✅ | `:206-221`，含类型、主键/唯一标记、DB 注释、业务语义、`semanticType` |
| RELATION 知识 | ✅ | `:223-234`，含类型、基数、列对全文、说明 |
| VALUE 知识 | ✅ | `:236-250`，含业务名、同义词、说明 |
| METRIC 知识 | ✅ | `:252-273`，含说明、表达式、过滤条件、时间字段、单位、**可加性**、统计归属、基础表 |
| **NOTE 知识** | ❌ **从不生成** | `build_knowledge` 只有 5 个 `object_type=` 分支；DDL 的 `NOTE` 类型与 CHECK 空置 |
| Object Key | ✅ | 一律对象 UUID（`table['id']` 等），避开点号拼接歧义 |
| Content Hash | ✅ | `content_hash(draft.content)`，SHA-256 |
| 版本隔离 | ✅ | 每版本一套知识行，`UNIQUE(version_id, object_type, object_key)` |
| 更新策略 | ⚠️ 全量重建 | 每个 revision 生成全新知识集，不 diff 不增量 |
| 删除策略 | ⚠️ 级联靠版本 | 旧版本不可删，知识随版本永久保留（实测 `Versions are retained`） |

**关键发现**：**METRIC 知识对象的内容是全链路里最完整的语义载体**（`knowledge.py:252-273` 把可加性、时间字段、单位、过滤条件都写进了正文），但它的消费路径（向量检索）**不参与生成**。与此同时，生成 Prompt 走的是另一条路（`build_context`），那条路把 Metric 语义裁到只剩三字段。**同一个指标，两条路径，一条丢信息、一条不生效。**

### 5.2 Table Retriever

| 能力 | 目标 | 实现 | 结论 |
|---|---|---|---|
| BM25 | 有 | 无 | ❌ |
| Vector | 有 | 有（精确余弦，无 ANN） | ⚠️ |
| RRF | 有 | 无 | ❌ |
| Reranker | 有 | 无 | ❌ |
| Datasource Filter | 有 | **无**（SQL 只过滤 `version_id`，`query_repository.py:94`） | ❌ |
| Version Filter | 有 | 有 | ✅ |
| Enabled Filter | 有 | 间接（快照只含 enabled 表） | ✅ |

### 5.3 Column Retriever

**不存在。** 列只作为 `object_type='COLUMN'` 的知识行混在同一个 top-24 池里（`query_repository.py:88-97` 无 `object_type` 过滤）。没有「在候选表范围内检索列」，没有同名字段消歧，没有主键/时间字段补全。实测：提问「用户所在城市和订单所属用户的所在城市」时，模型直接产出 `city_id` 两义性 SQL，系统没有任何 Schema Linking 介入。

### 5.4 Relation Retriever

| 能力 | 实现 | 结论 |
|---|---|---|
| 真实 FK 提取 | ✅ `scanner.py:395-422`，含复合键（`unnest(conkey)` + `unnest(confkey)` 按 `ord` 对齐） | ✅ |
| 人工定义 | ✅ `relation_type='MANUAL'`，扫描时**跳过不覆盖**（`repository_pg.py:621-622`） | ✅ |
| 推断关系 | DDL 允许 `INFERRED`，**无任何代码生成** | ❌ |
| 验证 | ✅ `verify_relation` + 触发器 `invalidate_dependency_verification` 在列对变更时清空 | ✅ |
| 基数 | ✅ 扫描按唯一约束判 `ONE_TO_ONE`，否则 `MANY_TO_ONE` | ✅ |
| 复合外键 + 顺序 | ✅ `t2s_relation_column.ordinal_position`；实测跨数据源/错表均被拒 | ✅ |
| 自关联 | ✅（实测允许） | ✅ |
| **多跳路径搜索** | **无 BFS、无最短路径** | ❌ |
| **JOIN 路径合理性** | 无校验 | ❌ |
| 跨数据源关系 | DB 层不可表达（复合外键） | ✅ |
| **`t2s_relation_column` 是否参与 JOIN 生成** | **是，但仅作为 Prompt 文本**：`sql_guard.py:453-462` 渲染成 `源schema.源表.源列 = 目标schema.目标表.目标列` 写进「表关联」段。**不参与 AST 校验、不参与 JOIN 路径规划、不做验证状态过滤** | ⚠️ |

> **对「relation_column 是否真正参与 JOIN 生成」的明确回答**：参与的是「让模型看到真实列对」，不参与「系统保证 JOIN 正确」。二者的区别在于：模型可以无视它，系统也不会发现。

### 5.5 Value Retriever

| 能力 | 实现 | 结论 |
|---|---|---|
| 精确值匹配 | ✅ 查询时回库 `=` 匹配并改写（`value_resolver.py:399-414`） | ✅ |
| 业务别名 | ✅ `business_name` + `aliases`，四级匹配（精确→ilike→去行政区后缀→包含） | ✅ |
| BM25 | ❌ | ❌ |
| Vector | ⚠️ VALUE 知识行参与向量池，但结果不进 Prompt | ❌ |
| 低基数字段 | ✅ 扫描期 `pg_stats.n_distinct` 估算，≤20 才取样 | ✅ |
| 敏感字段保护 | ❌ 无敏感列识别，低基数即全量收录 | ❌ |
| 真实库值验证 | ✅ 零命中明确报 `VALUE_NOT_FOUND`，多命中报候选 | ✅ |

**实测**：`city_name = '西安'` → 改写 `'西安市'`；`IN ('西安','咸阳')` → 两条都改写；`LIKE '西安%'` 不动；不存在的城市 → `VALUE_NOT_FOUND`。实测历史错误分布中 `VALUE_NOT_FOUND` 占失败主因（6/7）。

### 5.6 Metric Retriever

| 检查项 | 结论 |
|---|---|
| 创建/名称/别名/描述/表达式 | ✅ 全有 |
| 过滤 AST | ⚠️ `filter_definition` 是自由 JSONB，无结构校验、无消费者 |
| 时间字段 + 时区 | ✅ 存储；**Prompt 不带** |
| 单位 | ✅ 存储（实测 `元` / `人`）；**Prompt 不带** |
| ADDITIVE / SEMI_ADDITIVE / NON_ADDITIVE | ✅ 存储 + 知识正文；**Prompt 不带、无任何代码消费** |
| 依赖字段 / 依赖 Relation | ✅ 存储（两张依赖表）；**无消费者** |
| 审核/批准 | ✅ CHECK 约束 + 编辑自动失效（触发器） |
| 进入 Schema RAG 检索 | ⚠️ 作为 METRIC 知识行进向量池（实测 38 条 INDEXED），但检索结果不进 Prompt |
| **`COUNT(DISTINCT)` 是否被识别为 NON_ADDITIVE** | **不会自动识别**。`models.py:524` 默认 `ADDITIVE`；`_aggregation` 只校验取值，不推断语义。实测库中 `paid_users=COUNT(DISTINCT order_info.user_id)` 被标成 `NON_ADDITIVE`，**是人工设的**，不是系统推导的 |

**决定性证据（Prompt 侧）**：

```python
# sql_guard.py:485-491
metrics = snapshot.get('metrics') or []
if metrics:
    lines.append('')
    lines.append('指标定义（优先复用）：')
    for metric in metrics:
        lines.append(f"- {metric.get('key')} {metric.get('businessName')}："
                     f"{metric.get('expressionSql')}")
```

模型看到的是：
```
- paid_users 付费用户数：COUNT(DISTINCT order_info.user_id)
```
看不到 `NON_ADDITIVE`、看不到单位「人」、看不到时间字段、看不到过滤条件。

**判定**：Metric 目前是**「带语义标签的 SQL 片段库」**，不是**「业务指标语义系统」**。`COUNT(DISTINCT)` 的自解释性让它在多数情况下侥幸正确，但系统层面没有任何机制阻止把不同月份的 `paid_users` 相加——既没有 Prompt 约束，也没有 Validator 校验，也没有结果后处理。

### 5.7 四选一判定

> 题目要求判断属于 A / B / C / D。

**判定：B（Schema-aware Text2SQL），且是 B 的下限。**

| 选项 | 是否满足 | 证据 |
|---|---|---|
| A 普通 RAG + SQL Prompt | 已超越 | 有 5 类结构化知识对象、冻结快照、版本发布，不是把 DDL 丢进 Prompt |
| **B Schema-aware Text2SQL** | **满足** | Schema/关系/枚举/指标全部结构化后进 Prompt；表名白名单来自冻结快照 |
| C Hybrid Schema RAG | 不满足 | 无 BM25、无 RRF、无 Reranker；**检索 hits 不进 Prompt**（`query_service.py:120` vs `:126`） |
| D Metric-aware Schema RAG | 不满足 | Metric 语义在 Prompt 前被裁到只剩表达式（`sql_guard.py:485-491`），且无任何可加性消费 |

**距离 C 的差距不是「加三个组件」，而是先把「检索 → Context」这条线接上。**

### 5.8 ES 与 Vector 双索引：12 问逐条

| # | 问题 | 答案 | 证据 |
|---|---|---|---|
| 1 | ES 是否有独立索引映射 | **否** | `deploy/opensearch/` 只有镜像构建；全仓无 `t2s*` ES 索引 |
| 2 | ES 是否有独立索引状态 | **否** | `t2s_knowledge` 只有一个 `index_status` |
| 3 | ES 与 Vector 是否分别校验成功 | **否** | `finish_build` 只判 `index_status='INDEXED'`（`version_repository.py:346-362`） |
| 4 | 是否共享统一 knowledge_id | **仅 Vector 有**（`vector_document_id` = 知识行自身 UUID） | `version_repository.py:331` |
| 5 | 是否支持独立失败重试 | **否**。重试=新建 `EMBEDDING` 任务，`attempt` 恒 1 | `version_repository.py:283` |
| 6 | 是否支持部分失败恢复 | **是**（`pending` 只取非 INDEXED，`prepare_build:268-272`），但仅限 Vector | 代码 |
| 7 | 是否支持批量 Upsert | **否**。逐行 `INSERT ... ON CONFLICT` | `version_repository.py:316-328` |
| 8 | 是否支持删除同步 | **否**。版本不可删，无删除同步路径 | 实测 `Versions are retained` |
| 9 | 是否支持模型切换 | **是**（换模型=新 revision=新版本=新维度），但旧向量永久保留 | `service.py:456-467` |
| 10 | 是否支持双版本并存 | **是** | `t2s_config_version` + `version_id` 隔离 |
| 11 | 是否支持索引对账 | **否**。无任何对账/巡检 | — |
| 12 | READY 发布是否保证两套索引可用 | **否，只保证 Vector** | `guard_config_version:449-457` |

**明确结论：当前实现不需要「保守地假设 ES 也存在」——它根本没有 ES。但如果目标是双索引（BM25 必须依赖倒排），则 V2 DDL 本身不足以表达：`t2s_knowledge` 只有一个 `index_status`，无法记录「Vector 成功、ES 失败」。**

> **是否需要独立 ES Index Binding：需要。** 但不要为此改写 `t2s_knowledge` 的既有列。建议新增一张 `t2s_knowledge_binding`（`knowledge_id, store_kind['VECTOR'|'ES'], state, external_id, error, indexed_at`），`t2s_knowledge.index_status` 退化为「汇总态」，READY 判定改为「每种 store 至少一条 SUCCESS」。这与 §9 的 `ke_index_binding` 是同一抽象，可在 Text2SQL 内先落地再上提。

### 5.9 Context Builder

**当前实现 = 全量快照 + 24,000 字符硬截断**（`sql_guard.py:409-495`）。

离线实测（12 列/表，带业务描述）：

| 表数 | 字符数 | 是否截断 | 结果 |
|---|---|---|---|
| 3 | 2,899 | 否 | 全部进入 |
| 10 | 9,535 | 否 | 全部进入 |
| 20 | 19,275 | 否 | 全部进入 |
| 30 | 24,012 | **是** | **静默丢 5 张表**，截断点落在列定义中间（`...    co`） |

缺失能力：Token 预算、Minimal/Balanced/Full 分级、按表边界截断、省略清单、相关性优先级、必需字段补齐（JOIN 键）。

---

## 6. 版本管理专项报告

### 6.1 Config Version：13 问逐条（含实测）

| # | 检查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 配置修改时 `config_revision` 递增 | ✅ | `repository_pg.py:174-180`（`_REVISION_FIELDS` 命中才 +1）；表/列语义变更在 `_update_catalog_row:326-329` |
| 2 | 生成完整配置快照 | ✅ | `build_snapshot` 收敛 tables/relations/values/metrics/datasource + embedding 元信息 |
| 3 | DRAFT → BUILDING → READY | ✅ | 状态机触发器；实测非法跃迁被拒 |
| 4 | READY 不可修改 | ✅ **实测** | 改 snapshot / dims / model 均 `Terminal version is immutable` |
| 5 | 索引在独立版本中构建 | ✅ | 每版本独立 `version_id` 隔离 |
| 6 | 构建失败保留旧版本 | ✅ **由构造保证** | 失败不调用 publish，`active_version_id` 不变 |
| 7 | 检查知识对象数量 | ✅ **实测** | `expected_knowledge_count` 与实际条数不等 → 拒绝 READY |
| 8 | 检查索引任务完成 | ✅ | READY 前拒绝存在 `PENDING/RUNNING` 任务 |
| 9 | 验证 ES 与 Vector 完整性 | ❌ | 只有 Vector（§5.8） |
| 10 | 事务安全发布 | ✅ | `publish_version` 内 `SELECT ... FOR UPDATE` |
| 11 | 防并发发布冲突 | ✅ **实测**（见 6.3） | 同版本并发发布幂等；异版本被 revision 检查拦住 |
| 12 | 记录发布历史 | ✅ | `log_publication` 触发器 |
| 13 | 查询固定使用 READY 版本 | ✅ | `get_active_context` + `run_query:73-77` 三条件校验 |

### 6.2 版本、知识、双索引、Index Job

| 项 | 结论 |
|---|---|
| 配置版本 | ✅ 完整 |
| 知识版本 | ✅ 版本内不可变（实测 READY 后增删知识均拒绝） |
| 双索引版本 | ❌ 单索引 |
| Index Job | ⚠️ 表与状态机完整，但**无 worker 循环**：`prepare_build` 立刻置 RUNNING，`finish_build` 在同一 HTTP 请求内收口；`worker_id` 恒为 `'api'`；`attempt` 恒 1 |
| 原子发布 | ✅ DDL 层扎实（见 6.3） |
| 查询版本固定 | ✅ 落 `version_id` + `source_snapshot`；⚠️ 但历史响应不回带 `versionId`，前端看不到「这条历史用的是哪版」 |
| 失败恢复 | ⚠️ `FAILED` 版本可重建（`FAILED → BUILDING`），但无自动重试、无退避 |
| 并发控制 | ✅ 见 6.3 |

### 6.3 原子发布与并发（干净实例实测）

| 场景 | 期望 | 实测 |
|---|---|---|
| 知识仍 PENDING 时切 READY | 拒绝 | ✅ `All expected knowledge objects must be indexed before READY` |
| 知识数与 `expected_knowledge_count` 不符 | 拒绝 | ✅ 同上 |
| 全部 INDEXED 后切 READY | 成功 | ✅ `READY` + `ready_at` |
| READY 后改 snapshot/dims/model | 拒绝 | ✅ `Terminal version is immutable` |
| READY 后增删知识 | 拒绝 | ✅ `Knowledge version ... is not writable` |
| 删除版本 | 拒绝 | ✅ `Versions are retained; cancel drafts instead` |
| 并发两次 publish（同版本、同 expected_revision） | 只生效一次 | ✅ 两次都返回成功，但 `log_publication` 只在 `active_version_id` 真变化时写审计，**只产生 1 条记录** |
| 用过期 expected_revision 发布 | 拒绝 | ✅ `Datasource missing or configuration changed` |
| 用不存在版本发布 | 拒绝 | ✅ `Only a READY version matching current configuration can be activated` |
| 软删数据源但 `active_version_id` 未清 | 拒绝 | ✅ `t2s_datasource_check` |

**并发安全为什么成立（重要）**：`publish_version` 用 `FOR UPDATE` 串行化，且**不递增 `config_revision`**；两个并发调用都能通过 revision 校验，但由于 `UNIQUE(datasource_id, revision)` 使得「同一 revision 只有一个版本」，所以两个调用必然指向同一版本，第二次是幂等的。**「两个管理员并发发布不同版本」在结构上不可能发生。**

> 这是一个**设计优于常规做法**的点：用唯一约束把并发冲突变成不可能，而不是靠版本号 CAS。代价是发布不再「一次性」，重复发布不会报错（可能掩盖误操作），但审计记录不重复，可接受。

### 6.4 V2 DDL 设计问题（9 项，含 3 项结构性缺陷）

| # | 问题 | 类型 | 说明 | 建议 |
|---|---|---|---|---|
| D1 | `t2s_knowledge` 只有一个 `index_status` | **结构性** | 无法表达 Vector/ES 双索引任一失败 | 新增 `t2s_knowledge_binding`（§5.8） |
| D2 | `t2s_knowledge` 无 `token_count` | 结构性 | Context Builder 做预算时无法预估 | `ADD COLUMN token_count INT` |
| D3 | `t2s_query_run` 无 `context_snapshot` | **结构性** | 无法复现「模型到底看到了什么」 | `ADD COLUMN context_snapshot JSONB` |
| D4 | `guard_config_version` 禁止 DELETE 且无归档表 | 设计取舍 | 版本永久保留 → 存储线性增长（实测 25 版本/610 知识/602 向量，活动版本仅 29 条） | 增加 `archived_at` 或允许删「非活动且无引用」版本 |
| D5 | `t2s_index_job.idempotency_key` 允许任意文本 | 设计弱点 | 应用层塞了 `uuid4().hex`，唯一键形同虚设；真正防重靠 partial unique index | 约定键为 `f'{job_type}:{version_id}'`；或把 `attempt` 纳入唯一键 |
| D6 | `t2s_column` 无 `last_seen_at` | 不一致 | `t2s_table` 有、`t2s_column` 没有；DTO 读取恒 `None`（`models.py:335`） | 补列或删 DTO 字段 |
| D7 | `t2s_datasource.connection_options` 无消费者 | 死列 | 全仓零引用 | 删除或接入（连接池/SSL/只读参数） |
| D8 | `t2s_metric.filter_definition` 是自由 JSONB | 设计弱点 | 无结构、无校验、无消费者；「过滤 AST」名不副实 | 定义 schema（`{columnId, op, value}` 数组）并在入参校验 |
| D9 | `20-text2sql-index.sql` 依赖 `00` 的 `vector` 扩展 | 部署顺序 | 单独执行 18→20 会失败（实测） | 在 20 顶部加 `CREATE EXTENSION IF NOT EXISTS vector;` |

**另外两项非 DDL 但同属「基准层」的问题**：

- `deploy/init/pg/*.sql` **只在空数据卷执行**，没有 `schema_migration` 表；`22-text2sql-cardinality.sql` 是后端硬依赖（`repository_pg.py:263,353` 无条件 SELECT）却未登记进 `docs/database-schema.md:846-850`。
- `17` 张表里 `t2s_metric_column` / `t2s_metric_relation` 目前是**纯存储表**，没有消费者。

---

## 7. SQL 生成与安全专项报告

### 7.1 SQL Generator

| 检查项 | 结论 | 证据 |
|---|---|---|
| 复用统一 LLM Provider | ✅ | `model.resolver.resolve('llm')` + `invoke_llm` |
| 模型切换 | ✅ 请求级 `model` 字段 | `models.py:788` |
| Prompt 模板 | ❌ 硬编码中文字面量 | `query_service.py:441-461` |
| Schema Context | ✅（全量） | — |
| Metric Context | ⚠️ 仅三字段（§5.6） | `sql_guard.py:485-491` |
| Relation Context | ✅（平铺全部） | `sql_guard.py:453-462` |
| 参数绑定 | ❌ 无（值直接进 SQL 字面量） | — |
| 多轮澄清 | ❌ `parentRunId` 只落库，无澄清协议、前端不发送 | `models.py:784` |
| SQL 解释 | ✅ `explanation` 字段 | — |
| Generated / Final 区分 | ✅ 两列分开落库 | `18-text2sql.sql:328-329` |
| 自修复重试 | ❌ 单次生成，失败即终态 | `query_service.py:159-180` |

### 7.2 SQL Validator（正则，非 AST）

| 检查项 | 实现 | 结论 |
|---|---|---|
| AST Parser | **无**（`_mask_literals` + 正则 + token 集合） | ❌ |
| 禁止多 Statement | ✅ `_split_statements` | ✅ |
| 禁止写操作 | ✅ `_FORBIDDEN_TOKENS`（24 个） | ✅ 但可绕过 |
| 表白名单 | ✅ 冻结快照 | ✅ 但可绕过 |
| **字段白名单** | **无** | ❌ 实测 `SELECT no_such_column` 通过校验 |
| **函数白名单** | **无**（只有 `pg_*` / `information_schema` / `sleep` 等 5 条模式） | ❌ |
| 跨 Schema 限制 | ⚠️ 仅对 `FROM/JOIN` 后的表名生效 | ⚠️ |
| CTE / 递归 | ⚠️ CTE 名字被收集进白名单（`_CTE_NAME`），**递归 CTE 无深度限制** | ⚠️ |
| SQL 注入 | ✅ 无字符串拼接用户输入；值改写正确转义 | ✅ |
| LIMIT | ✅ 外层包裹 `LIMIT max_rows+1` | ✅（只限行） |
| JOIN 路径校验 | ❌ | ❌ |
| Metric 表达式校验 | ❌ `expression_sql` 自由文本，入 Prompt 时不校验 | ❌ |
| 业务指标聚合规则 | ❌ | ❌ |

### 7.3 SQL Executor 与 Query Policy 强制执行

| 策略 | 是否真实强制 | 证据 |
|---|---|---|
| 只读数据库账号 | ❌ 不校验 | 连接用用户填写的账号 |
| 只读事务 | ✅ 强制 | `sql_guard.py:309` `set_session(readonly=True)` |
| `statement_timeout` | ✅ 强制 | `:290` 拼进 `options` |
| `connect_timeout` | ✅ 8s | `:36` |
| 最大返回行数 | ✅ `max_rows+1` + 截断标记 | `:323` |
| **最大结果字节数** | ❌ **无** | 实测 5 行 × 500KB = 2.5MB |
| EXPLAIN | ✅ 执行前跑 | `:313` |
| **EXPLAIN 失败保护** | ❌ 无 SAVEPOINT，事务被毒化 | 实测错误变成 `current transaction is aborted` |
| 查询取消 | ❌ （SSE 断连只 cancel asyncio 包装，线程里的 SQL 继续跑完） | `api.py:380-382` |
| 连接池 | ❌ 每查询新建连接（值解析还会再建一条） | `sql_guard.py:292`、`value_resolver.py:384-396` |
| 大结果集处理 | ⚠️ 行级流式读取，但全量进内存 JSON | `fetchmany` |
| 执行错误分类 | ✅ 7 类 psycopg2 异常映射 | `:318-333` |

**Query Policy 结论**：`max_rows` / `timeout_ms` 真强制；`read_only` **是死字段**（`models.py:116-123` 保存，`sql_guard.py:309` 恒 `True`，从不读 policy）。

### 7.4 实测安全探针（当前 HEAD 容器）

| 场景 | 结果 |
|---|---|
| `DELETE` / 多条语句 / `DROP` / CTE 内 `DELETE` / `SELECT INTO` / `FOR UPDATE` | ✅ 全部拦截 |
| `pg_catalog.pg_shadow` / `pg_read_file` / `pg_sleep` / `information_schema` / `lo_export` / `current_setting` | ✅ 全部拦截 |
| **`query_to_xml('SELECT count(*) FROM pg_catalog.pg_class', true, false, '')`** | ❌ **通过，返回 419 行** |
| **`set_config('search_path','pg_catalog, public', false)`** | ❌ 通过 |
| `current_database()/current_user/version()` | ❌ 通过（信息泄露） |
| **`SELECT no_such_column FROM order_info`** | ❌ 通过校验，执行期报错被 EXPLAIN 毒化掩盖 |
| **多列 `GROUP BY` / `ORDER BY`** | ❌ **误杀 4/4**（合法 SQL） |
| **`repeat('x',500000)` × 5 行** | ❌ 返回 2,500,030 字符 |
| `JOIN ... ON true` ×5（248,832 行，`total_cost=3.15e13`） | ❌ 通过，无成本阈值 |

**安全结论**：当前真实边界是**外部库账号的 PostgreSQL 权限**（`pg_shadow` 读取失败是因为 `t2s_reader` 无权，不是 Guard 起效）。Guard 是防呆层，不是安全层。

---

## 8. 可观测性与效果评测

### 8.1 Query Run 落库实况

| 字段 | 是否落库 | 备注 |
|---|---|---|
| request_id / actor / datasource / version / parent | ✅ | `version_id` 落库但**不进历史响应** |
| 问题 / 参数 / date_policy | ✅ | — |
| **绝对时间范围** | ⚠️ **仅 `fixed` 有** | 实测 `relative` 只存 `{policy, timezone, referenceDate}`，**无起止** |
| source_snapshot / retrieval_snapshot | ✅ | retrieval 只有命中列表，不含各 Retriever 候选数 |
| generated_sql / final_sql | ✅ | — |
| validation_snapshot / explain_snapshot / result_snapshot | ✅ | 结果预览无保留期清理任务（`result_expires_at` 列空置） |
| error_stage / error_code | ✅ | — |
| timing / stages | ✅ | 但 4 段恒 0（SSE 实测逐帧确认） |
| **Token Usage** | ❌ | `usage=None`（`query_service.py:236`）、`'usage': None`（`:543`）；实测 `t2s_query_run.usage` 全空 |

### 8.2 与推荐链路的对照

| 链路阶段 | 是否存在 | 证据 |
|---|---|---|
| Question | ✅ | — |
| Intent Understanding | ❌ | 无 |
| Table Retrieval | ⚠️ 有检索，不参与生成 | `query_service.py:120` |
| Column Retrieval | ❌ | 无 |
| Value Retrieval | ⚠️ 内存子串 + 查询期回库 | `query_service.py:132`、`value_resolver.py` |
| Metric Retrieval | ⚠️ 仅混在向量池 | — |
| Relation Expansion | ❌ | 无代码 |
| RRF Fusion | ❌ | 无 |
| Reranker | ❌ | 无 |
| Context Builder | ⚠️ 全量快照 | `sql_guard.py:409` |
| SQL Generator | ✅ | — |
| AST Validator | ❌（正则） | `sql_guard.py:129` |
| EXPLAIN | ✅ | — |
| SQL Executor | ✅ | — |
| Result | ✅ | — |

### 8.3 评测

**没有 Text2SQL Benchmark。** 唯一的自动化端到端是 `tools/verify/verify-text2sql-e2e.py`，断言 1 条问题（城市支付金额）+ 5 条 Guard 拦截。实测历史成功率（排除本次审计探针）为 **42/49 ≈ 86%**，失败中 `VALUE_NOT_FOUND` 6 次、`DATASOURCE_UNAVAILABLE` 1 次。

**缺失指标**：Table Recall@K、Column Recall@K、Relation Accuracy、Value Mapping Accuracy、Metric Accuracy、SQL Validity、Result Accuracy、Token Cost。当前唯一可测的是 Execution Success。

---

## 9. 通用 Knowledge Engine 扩展性评估

### 9.1 12 项检查

| # | 检查项 | 结论 | 说明 |
|---|---|---|---|
| 1 | Schema RAG 能否抽象为统一 Knowledge Retrieval | **部分** | `KnowledgeDraft`（`knowledge.py:18-26`）已是领域无关形状 |
| 2 | Knowledge Object 是否有领域无关基础字段 | **是** | `object_type/object_key/title/content/metadata/content_hash` |
| 3 | 领域元数据是否独立 | **是** | `metadata` JSONB + 五张链接列 |
| 4 | ES 与 Vector 能否统一接口访问 | **否** | 无 ES；Vector 三套并行 |
| 5 | Retriever 是否支持不同 Knowledge Type | **否** | 单一 kNN，无 `object_type` 过滤 |
| 6 | Context Builder 是否可独立 | **否** | 耦合在 `sql_guard.py`，签名只吃 `snapshot` |
| 7 | SQL Generator 与 Executor 是否解耦 | **是** | 纯函数分层 |
| 8 | Validator 能否抽象为领域 Policy | **部分** | 只读执行部分可参数化；SQL 特有的是 AST 分支 |
| 9 | 是否存在 Query Operator 接口 | **否** | `operators/` 是文档处理沙箱算子 |
| 10 | 是否存在统一 Logical Plan | **否** | — |
| 11 | 是否支持 Operator 注册 | **否**（查询侧） | — |
| 12 | 是否可从 Agent / MCP 直接调用 | **否** | `backend/src/agent/` 对 text2sql 零引用 |

### 9.2 关于新增 `ke_*` 表的判断

题目列出 5 张候选表，逐条给结论：

| 候选表 | 是否建议新增 | 理由 |
|---|---|---|
| `ke_source` | **暂不** | `t2s_datasource` / `knowledge_base` / `graph_schema` 的差异远大于共性；强行合并会立刻退化成 JSON 泥潭。先用**接口**抽象（`DataSourceProvider`），不建表 |
| `ke_object` | **不建议单独建表** | 会把 `t2s_knowledge` 与文档 chunk、图实体塞进一张万能表。已有 `KnowledgeDraft` 契约足够；跨域只共享**投影接口** |
| `ke_index_binding` | **建议**（Text2SQL 内先落地） | 这是真正缺的东西：一张 `(object_id, store_kind, state, external_id, error)` 表能同时解决 §5.8 的双索引状态与 §6.4 D1。可先建 `t2s_knowledge_binding`，成熟后上提 |
| `ke_operator` | **建议**（配置表，不存业务数据） | 只存算子注册元信息（`name/version/enabled/config`），不存领域数据 |
| `ke_query_run` | **不建议** | `t2s_query_run` 的字段（SQL/EXPLAIN/结果预览）是 SQL 专属；跨 Operator 只需共享 `request_id / operator / plan / trace` 四要素，可作为**基类视图或公共列**，不宜合并成一张表 |

**原则**：公共层只负责「知识对象投影、检索、索引绑定、算子注册」四件事；**领域数据一律留在 `text2sql`**。

### 9.3 五种 Operator 的复用判断

| Operator | 可复用度 | 需新增 | 需独立表 | 需独立 Runtime |
|---|---|---|---|---|
| **NL2SQL**（已实现） | — | 见 P0/P1 | 已有 | 已有 |
| **NL2Graph** | **高** | `graph/` 已有 schema/抽取/pgvector/图查询；补 graph query validator | 否 | 有 |
| **NL2Search** | **高** | `infrastructure/search/` 已成熟；补 index mapping 知识对象 + Query DSL 校验 | 否 | 有（只读 ES） |
| **NL2API** | 中 | OpenAPI 解析 + 参数绑定 + HTTP Runtime | 是（`t2a_*`） | 是 |
| **NL2DSL** | 低 | 类型化 AST + 编译器 | 是 | 是 |

**建议顺序：Graph → Search → API → DSL**（按底层成熟度，不按题目顺序）。

### 9.4 Query Operator 契约建议

```python
class QueryOperator(Protocol):
    knowledge_types: ClassVar[tuple[str, ...]]   # NL2SQL: TABLE/COLUMN/RELATION/VALUE/METRIC
    def retrieve(self, question: str, ctx: RetrieveContext) -> OperatorContext: ...
    def plan(self, question: str, ctx: OperatorContext) -> QueryPlan: ...
    def validate(self, plan: QueryPlan, ctx: OperatorContext) -> ValidatedPlan: ...
    def execute(self, plan: ValidatedPlan, ctx: RuntimeContext) -> ResultSet: ...
```

Text2SQL 可以直接映射：`retrieve`=分层检索、`plan`=SQL 生成、`validate`=AST Guard、`execute`=只读执行。**SQL 特有的是 `validate` 的 AST 分支与 `execute` 的方言，接口本身通用。**

---

## 10. 真实运行验证记录

### 10.1 已执行

| # | 项目 | 结果 |
|---|---|---|
| 1 | Text2SQL 后端单测（`tests/test_text_to_sql_*.py`） | **67 passed** |
| 2 | 后端全量单测 | **2536 passed / 7 deselected**（65.74s） |
| 3 | 干净实例执行 `18` | **成功**，17 表 / 11 函数 / 24 触发器 |
| 4 | 干净实例执行 `20`（无 vector 扩展） | **失败**：`type "vector" does not exist` |
| 5 | 干净实例执行 `20`（有 vector） | **成功** |
| 6 | 干净实例执行 `22` | **成功**（幂等） |
| 7 | 复合外键：跨数据源挂列 | **拒绝**（FK violation） |
| 8 | 复合外键：源列属于错误表 | **拒绝**（FK violation） |
| 9 | 自关联关系 | **允许** |
| 10 | 版本 READY 三条前置（数量/全索引/无进行中任务） | **逐条生效** |
| 11 | READY 不可变（snapshot/dims/model） | **全部拒绝** |
| 12 | READY 后增删知识 | **全部拒绝** |
| 13 | 删除版本 | **拒绝** |
| 14 | 发布 + 审计行 | **成功**，`t2s_publication` +1 |
| 15 | 过期 expected_revision 发布 | **拒绝** |
| 16 | 不存在版本发布 | **拒绝** |
| 17 | 软删数据源但 active_version 未清 | **拒绝**（CHECK） |
| 18 | 并发发布（同版本 ×2） | **幂等**，只 1 条审计 |
| 19 | `t2s_metric` APPROVED 缺验证人 | **拒绝**（CHECK） |
| 20 | `t2s_favorite` fixed 缺范围 | **拒绝**（CHECK） |
| 21 | SSE `/query/stream` 逐帧 | **16 个 stage 帧 + result + done**，首帧 67ms，总 752ms（LLM 主导） |
| 22 | 自然语言 5 问（已配置模型） | 4 成功 / 1 被误杀（多列 GROUP BY） |
| 23 | 防护探针 20 条 | 16 拦截 / 2 通过（`query_to_xml`、`set_config`） |
| 24 | 前端单测 | 992 passed / 102 files（上一轮基线，本轮未重跑） |
| 25 | 前端构建 | 通过（`module.text2sql-legacy` 167.67 KiB / gzip 45.88 KiB） |

### 10.2 未验证（环境不具备）

| 项 | 原因 |
|---|---|
| 大表 `statement_timeout` 真实触发 | 演示库无大表；`JOIN ON true` 仅 248,832 行未超时 |
| 索引部分失败后重建 | 需构造 embedding 服务故障 |
| Index Job 多 worker 抢占 | 无 worker 循环，无法验证 |
| MySQL / Oracle / SQL Server | 应用层直接拒绝（`models.py:15`） |
| 跨租户越权读取 | 需两个数据源指向同一外部库 |
| 前端视觉回归 | 本轮为架构审计 |

### 10.3 测试覆盖盲区

67 条单测全绿，但漏掉了本次全部 S1/S2 问题：

- 无「多列 GROUP BY / ORDER BY」正向用例 → 误杀未被发现；
- 无 `query_to_xml` / `set_config` 函数级用例 → 绕过未被发现；
- 无结果字节上限用例；
- 无「执行失败错误码应可辨识」用例 → EXPLAIN 毒化未被发现；
- 无列级白名单用例；
- 端到端用例 monkeypatch 了 `_repo` 与 `_llm` → **无法暴露「检索不参与生成」**；
- SSE 用例只断言帧顺序，不断言「阶段是否真的做了事」。

### 10.4 后端全量单测

`pytest -q`（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）：**2536 passed, 7 deselected, 32 warnings in 65.74s**。
其中 Text2SQL 专属 67 条全部通过。**全绿不等于无缺陷**——见 §10.3 的盲区清单。

---

## 11. 关键代码问题清单

> 严重度：**S1** 数据泄露/越权/资源耗尽/危险执行；**S2** 正确性（错结果或错拒绝）；**S3** 可维护性。

### S1-01 SQL Guard 可被 `query_to_xml()` 绕过

```text
问题编号：S1-01        严重程度：S1
文件：backend/src/text_to_sql/sql_guard.py
函数：validate_sql(:129) / _mask_literals(:160) / _validate_table_scope(:227)
代码位置：:160-220（掩码）、:227-256（表名抽取）、:45-52（禁用模式）
当前实现：单引号字面量在掩码阶段被整体替换为空格；表名与禁用函数
          都只在掩码文本上匹配。
问题原因：任何接受 SQL 文本参数的函数，把内嵌 SQL 藏进被掩码的字面量。
          实测 SELECT query_to_xml('SELECT count(*) FROM pg_catalog.pg_class',
          true, false, '') → HTTP 200，返回 419。白名单与 pg_ 禁令同时失效。
推荐方案：引入 pglast（PostgreSQL 官方语法树）解析，遍历 RangeVar 与 FuncCall；
          函数白名单；禁止「参数为字符串且可求值 SQL」的函数族。
          保留现有正则作快速前置过滤。
验收标准：①上述探针被拒 ②「读 pg_catalog」全部被拒 ③既有 67 条单测全绿
          ④新增 ≥20 条 AST 用例 ⑤正常查询零回归
```

### S1-02 无结果字节上限

```text
问题编号：S1-02        严重程度：S1
文件：backend/src/text_to_sql/sql_guard.py:274-341
函数：execute_readonly
代码位置：:323 fetchmany(max_rows+1)；:340 全量 JSON 序列化
当前实现：只限行数，不限字节。
问题原因：实测 repeat('x',500000) × 5 行 → 2,500,030 字符响应体。
          默认 max_rows=1000 时可放大到数百 MB。
推荐方案：行数 + 字节双上限；超限截断并置 byte_truncated；
          max_bytes 进 query_policy。
验收标准：上述探针被截断并标记；1000 行正常查询不受影响。
```

### S1-03 数据源与目录 CRUD 无授权（SSRF）

```text
问题编号：S1-03        严重程度：S1
文件：backend/src/text_to_sql/api.py
函数：create_datasource(:74-80) / test_connection_payload(:82-86) / scan(:113-115)
代码位置：_require_admin(:505) 仅用于 :182 / :248 / :287 三处
当前实现：数据源建/改/删/扫描/连接测试全部只要求「已登录」。
问题原因：POST /datasources 接受任意 host/port，connection-test 由服务端发起 TCP。
          可用于内网探测、访问云元数据端点。无数据源归属模型。
推荐方案：①写操作限管理员 ②连接前解析主机名，拒绝 127/8、10/8、172.16/12、
          192.168/16、169.254/16、::1、fc00::/7 ③t2s_datasource 增 owner_id
验收标准：非管理员建源 → 403；host=169.254.169.254 → 400；正常内网数据源仍可用。
```

### S1-04 只读账号未强制（结合 S1-01 等于以该账号读全库）

```text
问题编号：S1-04        严重程度：S1
文件：backend/src/text_to_sql/service.py
函数：test_connection(:86) / scan(:144)
当前实现：连接使用用户填写的账号；仅靠 set_session(readonly=True) 提供会话只读。
问题原因：演示库 t2s_reader 是人为约定；本机另一个数据源直接用 rag 账号。
          配合 S1-01，可读该账号可见的任意表。
推荐方案：连接测试与扫描前执行
          SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user
          高权限账号拒绝；结论写入 t2s_datasource 供审计。
验收标准：高权限账号连接测试 → 409；只读账号通过；已有数据源下次扫描时被拦截。
```

### S1-05 `queryPolicy.read_only` 是死配置

```text
问题编号：S1-05        严重程度：S2（配置欺骗）
文件：backend/src/text_to_sql/models.py:111-123；sql_guard.py:309
当前实现：read_only 被校验、保存、回显，但 execute_readonly 恒设 readonly=True，
          从不读该字段。
推荐方案：从契约与前端移除；或断言不为 False，否则 409。
验收标准：契约中不再有 read_only；或关闭它会被拒。
```

### S2-01 逗号连接正则误杀多列 GROUP BY / ORDER BY

```text
问题编号：S2-01        严重程度：S2（直接阻断核心场景）
文件：backend/src/text_to_sql/sql_guard.py:154
代码：if re.search(r'\bFROM\b[^()]*?,', masked, re.IGNORECASE): raise ...
当前实现：正则不认识子句边界。
问题原因：实测 4/4 合法查询被拒：
            GROUP BY status, user_id                                   → 拒绝
            ORDER BY user_id, pay_amount                               → 拒绝
            JOIN + GROUP BY r.city_name, o.status                      → 拒绝
            GROUP BY status ORDER BY n DESC, status                    → 拒绝
          真实提问「用户所在城市和订单所属用户所在城市，分别有多少用户」
          生成的纯显式 JOIN SQL 同样被误杀（run 记录可复核）。
推荐方案：随 S1-01 的 AST 改造消除；过渡期移除该规则（逗号连接不构成安全风险）。
验收标准：上述 4 条通过；真正的逗号连接仍可被接受（或由 AST 判定）。
```

### S2-02 EXPLAIN 失败毒化事务

```text
问题编号：S2-02        严重程度：S2
文件：backend/src/text_to_sql/sql_guard.py:311-320
当前实现：EXPLAIN 包在 try/except 里，但异常后未回滚到保存点。
问题原因：psycopg2 语句错误会把事务置为 aborted。实测 SELECT no_such_column
          → 返回 "current transaction is aborted" 而非「列不存在」。
推荐方案：SAVEPOINT t2s_explain / ROLLBACK TO SAVEPOINT / RELEASE。
验收标准：未知列 → SQL_UNKNOWN_COLUMN；正常查询 EXPLAIN 结果不变。
```

### S2-03 无列级与函数级白名单

```text
问题编号：S2-03        严重程度：S2
文件：backend/src/text_to_sql/sql_guard.py:227-256
当前实现：只比对 FROM/JOIN 后的表名。
问题原因：实测 SELECT no_such_column FROM order_info 通过校验（stage=execute）。
推荐方案：AST 收集 ColumnRef 按作用域解析后比对；FuncCall 比对白名单。
验收标准：臆造列在 validation 阶段报 SQL_UNKNOWN_COLUMN；正常列零误杀。
```

### S2-04 生成无自修复回路

```text
问题编号：S2-04        严重程度：S2
文件：backend/src/text_to_sql/query_service.py:159-180
当前实现：生成一次 → 校验一次 → 失败即 QueryFailure。
推荐方案：有界重试（N=2），把 SqlGuardError.code/message 回灌下一轮；
          attempts 数组落 stages/timing。
验收标准：误杀类失败可由重试恢复；attempt 可在历史中查看。
```

### S2-05 Metric 语义在 Prompt 前被截断

```text
问题编号：S2-05        严重程度：S1（业务正确性）
文件：backend/src/text_to_sql/sql_guard.py:485-491
当前实现：指标段只输出 "- {key} {businessName}：{expressionSql}"。
问题原因：aggregationBehavior / unit / timeColumn / filterDefinition /
          attributionDescription 全丢。实测库中 paid_users 已正确标 NON_ADDITIVE，
          但模型看不到；系统也没有任何代码阻止把月度去重人数相加。
          Count(DISTINCT) 也不自动推导 NON_ADDITIVE（models.py:524 默认 ADDITIVE）。
推荐方案：①Prompt 补齐可加性/单位/时间字段/过滤条件
          ②`expression_sql` 含 DISTINCT 而 aggregation_behavior=ADDITIVE 时
            在创建时告警或强制推导
          ③Validator 增加「非可加指标禁止跨期聚合」检查（至少告警）
验收标准：Prompt 中出现「可加性：NON_ADDITIVE」；月度去重相加的 SQL
          被 Validator 标记；创建 COUNT(DISTINCT) 指标默认 NON_ADDITIVE。
```

### S2-06 检索结果不进入生成

```text
问题编号：S2-06        严重程度：S1（架构核心）
文件：backend/src/text_to_sql/query_service.py:120 / :126
当前实现：hits = search_knowledge(...) 后，build_context(snapshot) 用全量快照；
          hits 只在 :568 的 _retrieval_view 里用于展示。
问题原因：Schema RAG 的全部投入（知识对象、向量索引、版本发布）对生成零贡献。
          3 表演示库放得下所以功能测试全绿；30 表时 Prompt 静默丢表。
推荐方案：build_context(snapshot, hits)；按 hits 选表 → 选列 → 扩展关系 →
          过滤值/指标 → Token 预算。
验收标准：同一问题在「无关问题」与「相关问题」下 Prompt 表集合不同；
          30 表库不再丢表；Context 体积下降且答案正确率不降。
```

### S2-07 上下文硬截断静默丢表

```text
问题编号：S2-07        严重程度：S2
文件：backend/src/text_to_sql/sql_guard.py:493-494
当前实现：len(text) > 24000 即切字符串，不感知表边界。
问题原因：离线实测 30 表触发截断，丢 table_025–table_029，截断点落在列定义中间。
推荐方案：按表分组累加；超预算停止并显式列出省略表名；优先保留命中表。
验收标准：30 表时 Prompt 显式包含「已省略：xxx」；不再出现半行截断。
```

### S2-08 版本与向量无限累积

```text
问题编号：S2-08        严重程度：S2
文件：deploy/init/pg/18-text2sql.sql:426-464（禁止 DELETE）；version_repository.py
当前实现：版本不可删；每次 revision 全量重建知识与向量。
问题原因：实测一个 3 表演示库已 25 版本 / 610 知识 / 602 向量，
          活动版本只用 29 条。
推荐方案：保留最近 N 个 READY + 活动版本 + 被 query_run 引用的版本；
          其余允许删（需放开 trigger）；向量靠 ON DELETE CASCADE 清理。
验收标准：版本数受控；活动版本与被引用版本不受影响；检索结果不变。
```

### S2-09 索引构建同步阻塞 HTTP，未接入 task_center

```text
问题编号：S2-09        严重程度：S2
文件：backend/src/text_to_sql/service.py:382-417
当前实现：prepare_build(worker_id='api') → 一次性 embed → finish_build，
          全在请求线程。
推荐方案：复用 infrastructure/tasks/pg_queue；注册 T2S_INDEX 任务；分批 embed。
验收标准：任务中心可见、可取消、可重试；大目录不超时。
```

### S2-10 复合关系只展示第一列对

```text
问题编号：S2-10        严重程度：S3
文件：backend/src/text_to_sql/query_service.py:617
代码：pair = (relation.get('columnPairs') or [{}])[0]
当前实现：「答案依据」的关系段只取第一列对。
推荐方案：遍历全部 pairs（Prompt 侧 build_context 已正确遍历）。
验收标准：复合外键关系在 UI 中显示全部列对。
```

### S2-11 相对时间范围无绝对起止

```text
问题编号：S2-11        严重程度：S2
文件：backend/src/text_to_sql/query_service.py:713-725（_resolved_time_range）
当前实现：policy='relative' 时只存 {policy, timezone, referenceDate}。
问题原因：实测 3 条历史均为 {"policy":"relative","timezone":"Asia/Shanghai",
          "referenceDate":"2026-11-12"}，无起止。
          复现窗口只能靠 referenceDate + SQL 里的字面量推断。
推荐方案：生成前把相对策略解析成绝对 [start, end)，与 policy 一并落库。
验收标准：历史详情能直接读到绝对起止；跨天回放结果一致。
```

### S2-12 CANCELLED 状态永不产生

```text
问题编号：S2-12        严重程度：S3
文件：backend/src/text_to_sql/；api.py:380-382
当前实现：query_run 状态机允许 CANCELLED，但无任何代码置它。
          SSE 断连只 cancel asyncio 包装，线程内 SQL 继续跑完。
推荐方案：先把「客户端断开」如实记为 CANCELLED（或新增 ABANDONED），
          再考虑真实语句取消（psycopg2 需另开连接 pg_cancel_backend）。
验收标准：断连后历史状态与实际执行一致；不出现「界面已取消、库里还在跑」。
```

### S2-13 Token 计量恒空

```text
问题编号：S2-13        严重程度：S3
文件：backend/src/text_to_sql/query_service.py:236 / :543
当前实现：usage=None；'usage': None。invoke_llm 的响应未解析 usage。
推荐方案：operator_client 回传 usage；透传落库。
验收标准：任一次生成 usage 非空；可汇总成本。
```

### S2-14 最终 Prompt 不落库

```text
问题编号：S2-14        严重程度：S2（可解释性）
文件：backend/src/text_to_sql/query_repository.py:132-156
当前实现：落 generated_sql / validation / explain / result，不落 schema_context。
推荐方案：t2s_query_run 增 context_snapshot（或落其 hash + 长度 + 命中列表）。
验收标准：任一历史可回放「模型当时看到的原文」。
```

### S2-15 `idempotency_key` 含随机串、`attempt` 恒 1

```text
问题编号：S2-15        严重程度：S3
文件：backend/src/text_to_sql/version_repository.py:217 / :282
当前实现：f'kb:{version_id}:{uuid4().hex}' / f'emb:{version_id}:{uuid4().hex}'
推荐方案：键改为稳定值；attempt 自增。
验收标准：同版本重复构建命中同一幂等键（或明确新建 attempt）。
```

### S2-16 `t2s_column.last_seen_at` 缺列

```text
问题编号：S2-16        严重程度：S3
文件：backend/src/text_to_sql/models.py:335
当前实现：column_to_api 读 row.get('last_seen_at')，但表无此列 → 恒 None。
推荐方案：补列或删 DTO 字段。
```

### S2-17 `connection_options` 无消费者

```text
问题编号：S2-17        严重程度：S3
文件：deploy/init/pg/18-text2sql.sql（列）；全仓无引用
推荐方案：删除，或接入连接参数（SSL/只读/应用名）。
```

### S3-01 SSE 点亮了不存在的阶段

```text
问题编号：S3-01        严重程度：S2（对外呈现失真）
文件：backend/src/text_to_sql/query_service.py:110-180
当前实现：emit('columns'|'values'|'relations') 三处，实测均 0ms；
          'relations' 阶段无任何代码执行。
问题原因：SSE 让「8 阶段流水线」从 Debug 表格变成实时进度条，
          用户会认为系统真的做了列检索/值检索/关系扩展。
推荐方案：P1 实现分层检索后再点亮；在此之前阶段收敛为
          retrieval / llm / validation / explain / execute。
验收标准：UI 展示的阶段与真实步骤一一对应。
```

---

## 12. P0 / P1 / P2 / P3 改造计划

### P0：安全和正确性

| # | 任务 | 涉及模块 | 验收条件 |
|---|---|---|---|
| P0-1 | SQL Guard 改 AST（pglast） | `sql_guard.py` + 新增 `sql_guard_ast.py` | `query_to_xml` 等探针被拒；多列 GROUP BY 通过；67 条单测全绿；新增 ≥20 条 AST 用例 |
| P0-2 | 结果字节上限 | `sql_guard.py`、`models.py:_query_policy` | `repeat('x',500000)×5` 被截断；正常查询不受影响 |
| P0-3 | EXPLAIN SAVEPOINT | `sql_guard.py:311-320` | 未知列报 `SQL_UNKNOWN_COLUMN` |
| P0-4 | 数据源授权 + 私网拒绝 | `api.py`、`service.py` | 非管理员建源 403；元数据地址 400 |
| P0-5 | 只读账号校验 + 移除 `read_only` 假开关 | `service.py:test_connection`、`models.py`、前端表单 | 高权限账号 409；契约无 read_only |
| P0-6 | **Metric 语义进 Prompt** | `sql_guard.py:485-491`、`models.py:524` | Prompt 含可加性/单位/时间字段；`COUNT(DISTINCT)` 默认 NON_ADDITIVE；跨期聚合被 Validator 标记 |

### P1：Text2SQL 效果

| # | 任务 | 验收条件 |
|---|---|---|
| P1-1 | **`build_context(snapshot, hits)` 接线** | 无关/相关问题 Prompt 表集合不同 |
| P1-2 | Context Builder 重写（预算/分级/表边界/省略清单） | 30 表不丢表；Context 体积下降 |
| P1-3 | Column Retriever（候选表内检索列 + 同名字段消歧） | 同名 `city_id` 场景正确解析 |
| P1-4 | Relation Expansion（≤2 跳 BFS / 最短路径 / verified 优先） | 两跳问题自动补中间表；未验证关系不进上下文 |
| P1-5 | BM25 + RRF（建议先 `pg_trgm` 同库混合） | 关键词类问题召回提升，有对照数据 |
| P1-6 | Reranker 接入（复用 `engine/post_retriever`） | top-8 命中率有对照提升 |
| P1-7 | 生成自修复（有界重试） | 误杀类失败可恢复；attempt 可见 |
| P1-8 | 落库补全：context_snapshot / usage / 真实阶段耗时 / 绝对时间范围 | 任一次运行可完整回放 |
| P1-9 | 版本 GC | 版本数受控；活动与被引用版本不受影响 |
| P1-10 | Text2SQL Benchmark（≥50 条，覆盖题目 15 个场景） | 产出 Table/Column Recall、Relation Accuracy、Value Mapping、Metric Accuracy、SQL Validity、Result Accuracy、Latency、Token |
| P1-11 | SSE 阶段与真实步骤对齐 | UI 不展示未实现的阶段 |

### P2：架构完善

| # | 任务 | 验收条件 |
|---|---|---|
| P2-1 | `t2s_knowledge_binding`（Vector/ES 双索引状态） | 两套 store 独立状态；READY 要求每种 store 全绿 |
| P2-2 | 抽公共 `knowledge_engine/`（KnowledgeObject + HybridRetriever + Reranker + ContextBuilder） | Text2SQL 与文档 RAG 共用同一 Retriever 接口 |
| P2-3 | Query Operator 协议 + Text2SQL 适配 | `retrieve/plan/validate/execute` 四段；既有行为不变 |
| P2-4 | Policy Guard 骨架（只读/超时/行/字节/AST 钩子） | 至少两个 Operator 复用 |
| P2-5 | 索引构建迁 task_center | 任务中心可见、可取消、可重试 |
| P2-6 | ANN 索引（固定维度 + HNSW） | 1 万向量检索 <50ms |
| P2-7 | Migration runner + `schema_migration` 记录 | 18/20/22 执行状态可查、可重复执行 |
| P2-8 | 前端：关系编辑、反馈处理、检索调试（RRF/Rerank 分） | 关系可增删改验证；反馈可流转 |
| P2-9 | `t2s_metric_column/relation` 消费者（依赖驱动上下文） | 指标依赖的列/关系必进上下文 |
| P2-10 | 结果保留期清理（`result_expires_at`） | 过期结果被清空、历史仍可读 |

### P3：未来扩展

| # | 任务 | 前置 |
|---|---|---|
| P3-1 | NL2Graph（复用 `graph/`） | P2-2 / P2-3 |
| P3-2 | NL2Search（复用 `infrastructure/search/`） | P2-1 / P2-3 |
| P3-3 | NL2API（OpenAPI 知识 + HTTP Runtime） | P2-3 / P2-4 |
| P3-4 | NL2DSL（类型化 AST + 编译器） | P2-3 |

---

## 13. 最终建议

### 13.1 当前真实架构

```text
前端 Text2SQLPage（查询/历史/数据源/验证反馈 + SSE 阶段条）
        │ 45 条 REST 路由（3 处 admin 校验）
        ▼
   api.py ──► query_service / service
        │
        ├── 生成主链（真正影响答案）
        │     get_active_context（版本 + 冻结快照）
        │       → build_context(全量快照)      ← 24k 字符硬截断
        │       → _value_hints(全量值子串匹配)
        │       → LLM 生成（单次）
        │       → 正则 Guard（表白名单，无列/函数白名单）
        │       → 值解析回写（回库改字面量，设计好）
        │       → 只读执行（超时/行上限，无字节上限）
        │
        └── 向量检索（旁路）embed → pgvector 余弦 top-24（无 ANN/BM25/RRF/Rerank）
                │
                └──► 仅用于「答案依据」UI

知识层：冻结快照 → 5 类知识对象（无 NOTE）→ 逐行 embed → 版本隔离
数据库：text2sql 17 表（复合外键隔离 + 不可变触发器 + 发布审计，质量高）
        text2sql_index 1 表（vector 无维度、无 ANN、无外键）
外部库：只读事务；真实边界＝该账号的 PostgreSQL 权限
```

### 13.2 目标架构（最小改造，不重写）

```text
RAGStudio → Knowledge Engine
  ├─ Unified Knowledge Retrieval（BM25 ∥ Vector → RRF → Rerank，Metadata Filter）
  ├─ Context Builder（Token 预算 + 分级 + 表边界 + 必需字段补齐）
  ├─ Semantic Planner（意图/实体/度量 + 澄清协议）
  ├─ Query Operator（retrieve / plan / validate / execute）
  ├─ Policy Guard（只读/超时/行/字节/成本/AST 钩子）
  └─ Execution Runtime
        └─ NL2SQL Operator（Schema Linking + Relation Expansion + AST Guard + 自修复）
```

### 13.3 最大的五项差距

1. **检索不参与生成**（`query_service.py:120` vs `:126`）。
2. **Metric 语义在 Prompt 前被裁剪**（`sql_guard.py:485-491`），可加性/单位/时间/过滤全丢。
3. **Guard 是正则**，可绕过、有误杀、无列/函数白名单（`sql_guard.py:154`）。
4. **Relation 无扩展**：列对进了 Prompt，但没有多跳、没有可信度过滤、`verified` 零消费。
5. **可观测性与评测缺失**：Prompt 不落库、Token 恒空、4 个阶段是空的、无 Benchmark。

### 13.4 最值得优先修改的五项

1. **AST Guard**（同时解决绕过 S1-01 与误杀 S2-01）。
2. **Metric 语义进 Prompt + `COUNT(DISTINCT)` 推导 NON_ADDITIVE**。
3. **`build_context(snapshot, hits)` 接线 + Context Builder 重写**。
4. **结果字节上限 + EXPLAIN SAVEPOINT + 数据源授权**（三件小而确定的事）。
5. **Column Retriever + Relation Expansion**（Schema Linking 的两条腿）。

### 13.5 是否适合进入下一阶段

**适合。** 理由：

- 数据库层 17/17 落地，版本与发布机制经实测可信，**不需要重构数据模型**；
- 知识对象契约已经领域无关，具备上提公共层的基础；
- 主要缺陷集中在「检索→上下文→校验」这一段，边界清晰、可增量修；
- 已有 67 条单测 + 真实 E2E 脚本 + 可运行的演示数据源，回归成本低。

**不适合**的部分：在 P0 完成前不宜扩到真实生产库 —— 当前的 `query_to_xml` 绕过 + 无字节上限 + 无授权，三者叠加在「数据源账号权限较高」时等于可读全库。

### 13.6 下一阶段任务拆分

| 迭代 | 周期 | 内容 | 出口标准 |
|---|---|---|---|
| 1 | 2 周 | P0-1 ~ P0-6 | 安全探针全部反转；Metric 语义进 Prompt；回归全绿 |
| 2 | 2 周 | P1-1 / P1-2 / P1-3 / P1-4 | 同一问题在相关/无关提问下上下文不同；同名与多跳场景正确 |
| 3 | 3 周 | P1-5 ~ P1-9 / P1-11 | 有对照的召回/准确率提升；版本可控；阶段真实 |
| 4 | 2 周 | P1-8 / P1-10 / P2-7 | 可回放、可评测、可迁移 |
| 5 | 4 周 | P2-1 ~ P2-6 / P2-8 ~ P2-10 | 双索引绑定、公共层、Operator 协议 |
| 6 | — | P3-1 → P3-2 → P3-3 → P3-4 | 按 Graph → Search → API → DSL |

---

## 14. 附：V2 设计中值得保留的部分（不应改动）

1. **复合外键把 `datasource_id` 绑进每一级父引用** —— 实测跨数据源挂列在 DB 层被拒，这是「不可能写错」级别的一致性保证。
2. **版本不可变 + 知识冻结 + 发布审计** —— 实测 READY 后改快照/维度/模型、增删知识、删版本，全部被拒。
3. **并发发布用唯一约束化解** —— 同一 revision 只有一个版本，使「并发发布不同版本」在结构上不可能；比 CAS 更简单。
4. **扫描不覆盖人工语义** —— `_upsert_column` 只更新结构列；`_apply_relations` 遇 `MANUAL` 跳过。
5. **表默认 `enabled=false`** —— 扫描不会自动把整库暴露给查询。
6. **查询时值解析** —— 开放维度不需要预索引，且零命中会明确报错而不是返回误导性的 0。
7. **凭据加密 + AAD 隔离 + 接口从不回传密码**。
8. **`t2s_query_run` 的不可变快照** —— 问题/版本/检索/校验/结果都冻结，历史可精确解释（唯一缺的是 Prompt 本身）。

---

*报告生成：2026-11-12。审计期间仓库由 `8f088d2f` 前进到 `b4b1d83f`，本报告全部结论以 `b4b1d83f` 为准。干净实例容器 `t2s-ddl-audit` 为一次性环境，审计结束后已移除。运行探针产生的查询历史可通过 `DELETE /text2sql/runs` 清理。*
