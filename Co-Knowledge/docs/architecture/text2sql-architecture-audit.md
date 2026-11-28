# Text2SQL 架构审计与技术路线差距分析

> 审计对象：`ragstudio-opensource`（当前分支 `master`，HEAD `8f088d2f`，2026-11-12）
> 审计性质：只读架构审计。除本文件外，未修改任何业务代码、数据库结构与前端页面。
> 取证方式：静态代码通读 + 真实运行验证（本机 Docker 栈 `rag-studio-*`，PostgreSQL 16.15 / pgvector 0.8.7，`AUTH_MODE=local`）。
> 所有结论均标注 `文件:行号` 或实测输出。无法验证的项单独标注「未验证」。

---

## 0. 审计口径说明

本报告以**真实代码与真实运行结果**为准，不以设计文档为准。三点前置澄清：

1. **目标设计中的 7 张表是 V1 形态。** 仓库内 `backups/text2sql-v1-20261111/text2sql-v1.sql` 恰好是那 7 张表；当前运行的是 V2，共 18 张（`text2sql` 17 张 + `text2sql_index` 1 张）。因此「数据库与目标设计的差距」一节的主结论不是「缺表」，而是「**现有设计在多个维度上强于目标设计，不应回退**」。
2. **本仓库没有通用 migration runner。** `deploy/init/pg/*.sql` 只在空数据卷由 PostgreSQL 官方 entrypoint 按文件名字典序执行（`deploy/docker-compose.yml:81`），没有任何 `schema_migration` 版本表。下文「是否需要 Migration」均基于此前提。
3. **本次审计跑通了真实链路**，包括 5 条自然语言提问的完整 NL→SQL→执行，以及 30+ 条人工 SQL 的防护探针。所有探针均以只读方式执行（`SELECT`），未改动外部库数据；运行记录落在 `t2s_query_run`（业务历史表），可由 `DELETE /text2sql/runs/{id}` 清理。

---

## 1. 执行摘要

### 1.1 成熟度判定

**当前 Text2SQL 处于「可演示、可小范围试用」的 Schema-aware Text2SQL（B 级），尚未进入 Hybrid Schema RAG（C 级），也不具备 Query Operator 的架构基础。**

用一句话概括当前实现：**一个把外部库结构冻结成版本化知识对象、用 pgvector 做语义检索、但把检索结果只用于界面展示、把全量快照直接塞进 Prompt 的单体模块。**

判定为 B 级（而非 A 或 C）的证据：

| 维度 | 现状 | 说明 |
|---|---|---|
| Schema 知识对象 | **有** | TABLE/COLUMN/RELATION/VALUE/METRIC 五类，`knowledge.py:184-275`，object_key=UUID、content_hash、metadata 齐备 |
| Schema-aware Prompt | **有** | `sql_guard.py:386-472` 输出表/列/类型/主键/注释/业务语义/关系/枚举/指标 |
| 检索参与生成 | **否** | 检索命中只进 `_retrieval_view()` 做展示，从不进入 Prompt（见 §5.1） |
| BM25 / RRF / Reranker | **均无** | 纯余弦精确扫描，`query_repository.py:81-98` |
| Column / Value / Relation 独立检索 | **均无** | 无对应检索器，无候选表内列检索，无关系 BFS |

### 1.2 与目标架构的总体一致性

| 目标原则 | 达标 | 说明 |
|---|---|---|
| 1 复用 Embedding / Model Provider | ✅ | `model.gateway.embed_many` / `embed_query` / `invoke_llm` 均已复用 |
| 1 复用 ES / Reranker | ❌ | 完全未用；仓内已有 RRF 与 Reranker 实现但未接线 |
| 2 Schema 元数据与文档知识分离 | ✅ | 独立 `text2sql` schema，与 `kb_index` 零耦合 |
| 3 专用知识对象与专用 Retriever | ⚠️ | 知识对象有；专用 Retriever 只有一个向量 kNN 函数 |
| 4 元数据权威、索引为副本 | ✅ | `t2s_*` 权威，向量为可重建副本；冻结快照是唯一真值 |
| 5 BM25 + Vector + RRF + Reranker | ❌ | 仅 Vector |
| 6 Table/Column/Relation/Value 分别检索 | ❌ | 一个 `object_type` 字段混检，无分层检索 |
| 7 增量同步与索引版本管理 | ⚠️ | 目录层增量（upsert + tombstone）有；索引层全量重建，无 GC |
| 8 生成前 Schema Linking + Relation Expansion | ❌ | 无 |
| 9 生成与执行解耦 | ✅ | 纯函数分层，且支持手工 SQL 直执行 |
| 10 AST 校验 + 安全策略 + 只读执行 | ⚠️ | 只读执行到位；校验是正则而非 AST，已实测 2 处绕过 |
| 11 完整 Query Trace | ⚠️ | 落库字段很全，但最终 Prompt、Token、RRF/Rerank 全缺 |
| 12 可扩展其他 Operator | ❌ | 无任何 Query Operator 抽象 |

### 1.3 最大的三个架构问题

1. **检索与生成没有接线（已知且已记录的阶段性取舍，但现在是第一瓶颈）。** `query_service.py:107` 取回 `hits`，`:111` 用 `build_context(snapshot)` 拼 Prompt —— 两者互不影响。Schema RAG 的全部投入（知识对象、向量索引、版本发布）目前**对生成质量零贡献**，只影响界面上「答案依据」那一栏。需要说明：这是 2026-11-11 的**有意决策**（「本版本不引入 OpenSearch / 关键字检索，先做稳定」），当时的记录已把「top-N 命中参与选表」「上下文超 24k 时按相关度而非字典序截断」列为后续项。本审计的增量结论是：**这两项已从「优化项」升级为「规模化前的硬前置」**——实测 30 张表时 Prompt 已静默丢表，且丢失顺序与问题无关。
2. **安全边界不是 SQL Guard，而是外部库账号权限。** Guard 用正则做关键词与表名检查，无 AST、无函数白名单、无列白名单。实测 `query_to_xml()` 可执行任意内嵌 SQL 并绕过表白名单与 `pg_` 禁令（读取 `pg_catalog.pg_class` 成功返回 419）。真正拦住的是 `t2s_reader` 的 PostgreSQL 权限 —— 这属于「部署纪律」，不是「系统保证」。
3. **规模化路径缺失。** 无 ANN 索引、无增量索引、无版本 GC、无上下文预算、无结果字节上限、无 Token 计量。3 张表 12 行的演示库跑得很好；30 张表时 Prompt 已静默丢表（实测）。

### 1.4 最大的五个功能缺失

1. **Schema Linking / Column Retrieval** —— 不在候选表范围内检索列，靠全量表结构 + LLM 自己挑。
2. **Hybrid Retrieval（BM25 + RRF + Reranker）** —— 无关键词路，无融合，无重排。
3. **Relation Expansion（多跳 / 最短路径 / 可信度）** —— 所有关系恒等进 Prompt，`verified` 字段无任何代码消费。
4. **Context Builder（预算 / 分级 / 最小上下文）** —— 全量快照 + 24k 字符硬截断，无 Minimal/Balanced/Full。
5. **SQL 生成自修复回路** —— 校验失败即终态报错，不把违规原因回灌给模型重试（实测一条完全合法但含多列 GROUP BY 的 SQL 被误判后直接失败）。

### 1.5 是否适合进入下一阶段开发

**适合，但必须先做 P0。** 地基比外观好：知识对象模型、版本冻结、复合外键隔离、值解析都是高质量设计；缺的是把已有部件接到生成链路上，以及把安全校验从正则升级为 AST。不建议重写，建议沿现有结构增量演进。

---

## 2. 模块清单与真实调用关系

### 2.1 技术栈实况

| 关注点 | 实际情况 | 证据 |
|---|---|---|
| 前端 | Vue 3.5.26 + Vue CLI 5（webpack 5）+ Element Plus 2.14.7 + vue-router 4；本页仅用 `ref/computed`，不入 Vuex | `frontend/package.json` |
| 后端 | Python 3.11 + FastAPI + Starlette（线程池派发阻塞调用） | `backend/src/text_to_sql/api.py:22-49` |
| 数据库 | PostgreSQL 16.15 + pgvector 0.8.7（`vector` 扩展） | 实测 `pg_extension` |
| 搜索 | OpenSearch 2.19.6 —— **Text2SQL 完全未使用** | `backend/src/text_to_sql/` 对 ES 零引用 |
| Embedding | 复用 `model.gateway`，实测 `Qwen3-Embedding-0.6B` / 1024 维 | `indexer.py:14-23`、`t2s_config_version` 实测 |
| Reranker | 仓内有 `ExternalModelReranker` / `LLMReranker`，**Text2SQL 未用** | `engine/post_retriever/` |
| LLM | 复用 `model.resolver.resolve('llm')` + `model.operator_client.invoke_llm` | `query_service.py:420-470` |
| 任务队列 | 仓内有统一 `task_center` DB 队列；**Text2SQL 未接入**，索引构建在 HTTP 请求线程内同步完成 | `service.py:382-417` |
| 认证 | 共享 `AuthMiddleware`（local/gateway/none）；授权极薄 | `api.py:415-420` |
| Migration | 无 runner；空卷 `docker-entrypoint-initdb.d` 字典序执行 | `deploy/docker-compose.yml:81` |

### 2.2 模块表

| 模块 | 文件路径 | 核心类/函数 | 实际职责 | 完成情况 |
|---|---|---|---|---|
| API 层 | `backend/src/text_to_sql/api.py` | `build_router`（44 条路由：15 POST / 14 GET / 7 PATCH / 7 DELETE / 1 PUT） | REST + problem+json，线程池派发 | ✅ 完整 |
| 数据源/目录业务层 | `backend/src/text_to_sql/service.py` | `Text2SqlService` | 校验→仓库→扫描编排、版本构建/发布 | ✅ 完整 |
| 查询编排 | `backend/src/text_to_sql/query_service.py` | `Text2SqlQueryService.run_query` | 检索→生成→校验→执行→落库 | ⚠️ 检索未接生成 |
| 入参/出参模型 | `backend/src/text_to_sql/models.py` | `parse_*` / `*_to_api`（921 行） | 手工校验 + DTO 映射 | ✅ 完整 |
| Schema Loader | `backend/src/text_to_sql/scanner.py` | `scan_database` / `_read_*` | pg_catalog 只读扫描 + 低基数值采样 | ✅ 完整（缺索引、视图列注释见 §4） |
| 目录持久化 | `backend/src/text_to_sql/repository_pg.py` | `apply_scan` / `_upsert_column` / `_apply_relations` | 增量 upsert + tombstone | ✅ 且不覆盖人工语义 |
| 关联/枚举/指标 | `backend/src/text_to_sql/catalog_repository.py` | CRUD | 关系（含列对）、值、指标 | ✅ 完整 |
| 知识构建 | `backend/src/text_to_sql/knowledge.py` | `build_snapshot` / `build_knowledge` | 冻结快照 → 5 类知识对象 | ✅ 质量高 |
| 向量化 | `backend/src/text_to_sql/indexer.py` | `embed_texts` | 调 `embed_many` | ✅ 薄封装 |
| 版本/索引任务 | `backend/src/text_to_sql/version_repository.py` | `create_version` / `prepare_build` / `finish_build` / `publish_version` | 三段事务 + 向量写入 | ⚠️ 同步执行、无 GC |
| Schema Retriever | `backend/src/text_to_sql/query_repository.py` | `search_knowledge` | pgvector 余弦，`version_id` 过滤 | ❌ 仅 Vector，未接生成 |
| SQL 生成 | `backend/src/text_to_sql/query_service.py` | `_generate_sql` | 硬编码 system prompt + JSON 提取 | ⚠️ 无模板、无自修复 |
| SQL Guard | `backend/src/text_to_sql/sql_guard.py` | `validate_sql` / `_mask_literals` / `_validate_table_scope` | 正则 + token 扫描 + 表白名单 | ⚠️ 非 AST，有误报与绕过 |
| SQL Executor | `backend/src/text_to_sql/sql_guard.py` | `execute_readonly` | 只读事务 + timeout + 行上限 + EXPLAIN | ⚠️ 无字节上限、无分页/取消 |
| 值解析 | `backend/src/text_to_sql/value_resolver.py` | `resolve_and_rewrite` / `extract_text_filters` | 查询时回库改写字面量 | ✅ 设计优于目标 |
| Context Builder | `backend/src/text_to_sql/sql_guard.py` | `build_context` | **全量快照** + 24k 截断 | ❌ 无预算/分级/筛选 |
| 查询历史 | `backend/src/text_to_sql/query_repository.py` | `create_run` / `finish_success` / `finish_failure` | 不可变运行快照 | ⚠️ 缺 Prompt/Token |
| 前端 | `frontend/src/pages/text2sql/Text2SQLPage.vue`（1700 行）+ `features/text2sql/`（5462 行） | 4 个工作区 | 查询/历史/数据源/验证反馈 | ⚠️ 封装 38 条、UI 调用 35 条；关系编辑与澄清无 UI |

### 2.3 真实调用关系（以代码为准）

```text
POST /text2sql/datasources/{id}/query
  → api.run_query                      api.py:287-294
  → Text2SqlQueryService.run_query     query_service.py:54
      ├─ query_repository.get_active_context         :58   （取活动版本 + 冻结快照）
      ├─ models.parse_query_request                  :56
      ├─ query_repository.create_run / mark_running  :86 / :92
      ├─ _embed_question → model.gateway.embed_query :101
      ├─ query_repository.search_knowledge           :107  ──┐ 只用于展示
      ├─ sql_guard.build_context(snapshot)           :111  ←─┘ 用全量快照，与 hits 无关
      ├─ _value_hints(snapshot, question)            :114
      ├─ _generate_sql → model.resolver.resolve
      │                → model.operator_client.invoke_llm  :125
      ├─ sql_guard.validate_sql                      :137
      ├─ value_resolver.resolve_and_rewrite          :139
      ├─ sql_guard.validate_sql（改写后复检）         :142
      ├─ sql_guard.execute_readonly                  :146
      └─ query_repository.finish_success/_failure    :193 / :255
```

**与目标流程的差异**：目标中的 `SchemaRetriever → ContextBuilder → Generator` 三段在代码里是 `search_knowledge`（旁路）∥ `build_context`（主线），二者是**并行而非串行依赖**。这就是「检索是装饰性的」的实现层证据。

### 2.4 代码规模

| 层 | 行数 |
|---|---|
| 后端 `text_to_sql` | 6,497 行 / 337 个函数 |
| 前端 `features/text2sql` + `pages/text2sql` | 5,462 行 |
| 前端构建产物 | `module.text2sql-legacy` 167.67 KiB（gzip 45.88 KiB）；CSS 33.42 KiB（gzip 5.39 KiB） |

---

## 3. 架构对比矩阵

| 模块 | 目标架构 | 当前实现 | 差距 | 优先级 |
|---|---|---|---|---|
| Datasource | 多数据源、连接池、权限隔离 | 多数据源 ✅；**每查询新建连接**；连接测试 ✅；凭据 AES-GCM（`enc:v1:`）✅；DB CHECK 允许 mysql/oracle/sqlserver/clickhouse，应用层只放行 postgresql（`models.py:15,148`） | 无池、无只读账号强制、无数据源级 ACL；SSRF 面（`api.py:74-127` 无授权） | P0 |
| Schema Loader | 完整元数据（含索引） | pg_catalog 全量；表/视图/物化视图/外部表/分区表 ✅；列/类型/注释 ✅；PK/FK/复合键 ✅；**未采集普通索引**；未采集列级统计之外的约束细节 | 缺 index 采集；`t2s_column` 缺 `last_seen_at` 列但 API 读取（`models.py:337` 恒 `None`） | P2 |
| Schema RAG | BM25 + Vector + RRF + Rerank | **仅 Vector 余弦**，`LIMIT 24` 硬编码（`query_service.py:107`）；无 ANN 索引；检索结果不进 Prompt | 缺 3 条链路 + 主线未接线 | P0/P1 |
| Relation | 多跳、最短路径、可信度分级 | 关系表完整（FK/MANUAL/INFERRED、verified、复合列对）；`build_context` **全量平铺**；无 BFS/最短路径；`verified` 无消费者 | 无扩展算法、无可信度过滤 | P1 |
| Value Index | 业务值检索 | 扫描期只收 LOW 基数（≤20）；查询期回库解析改写（`value_resolver.py`）；Prompt 内 ≤80 条 | 无独立 Value Retriever；无 BM25/Vector 值检索 | P1 |
| Context Builder | 最小上下文 + 预算 + 分级 | **全量快照** + 24,000 字符硬截断（`sql_guard.py:470-471`） | 无预算模型、无 Minimal/Balanced/Full、无相关性筛选 | P0/P1 |
| SQL Generator | 结构化生成 + 模板 + 自修复 | 硬编码 prompt（`query_service.py:440-460`）；单次生成；失败不重试 | 无模板文件、无澄清、无修复回路、无 Token 计量 | P1 |
| SQL Guard | AST + Policy | 正则/token 扫描；表白名单；**无列/函数白名单**；**逗号连接误报** | 需换 AST（如 `pglast`）；实测 2 类绕过 | P0 |
| Executor | 只读 + 池 + 超时 + 字节上限 + 分页/取消 | 只读事务 ✅、`statement_timeout` ✅、行上限 ✅、`connect_timeout=8s` ✅ | 无池、无字节上限（实测 5 行 2.5MB）、无分页、无取消 | P0/P1 |
| Observability | 全链路 Trace | 8 阶段骨架 + `request_id` + 版本绑定 + SQL/EXPLAIN/结果快照 | 4 阶段恒 0ms；无 Prompt、无 Token、无 RRF/Rerank 分、无 Query Understanding | P1 |
| Operator | 可插拔 Query Operator | 无抽象；`operators/` 是文档处理算子（`file_parse`/`text_split`/`graph_extract`），与查询无关 | 需新建接口层 | P2 |

---

## 4. 代码级问题清单

> 严重度：**S1** 数据泄露/越权/资源耗尽/危险执行；**S2** 正确性缺陷（错误结果或错误拒绝）；**S3** 质量与可维护性。

### S1-01 SQL 防护可被 `query_to_xml()` 绕过（表白名单与 `pg_` 禁令同时失效）

```text
问题编号：S1-01
问题名称：字符串内嵌 SQL 使表白名单与系统对象禁令失效
严重程度：高（S1）
涉及文件：backend/src/text_to_sql/sql_guard.py
涉及类/函数：validate_sql / _mask_literals / _validate_table_scope
当前实现：_mask_literals(:157-217) 把单引号字面量整体替换为空格，
          _validate_table_scope(:224-253) 只在掩码后的文本上用
          r'\b(?:FROM|JOIN)\s+(...)' 抽取表名；_FORBIDDEN_PATTERNS(:42-48)
          同样只扫掩码文本。
存在的问题：任何接受 SQL 文本参数的函数都把内嵌 SQL 藏进被掩码的字面量里。
          实测（本机运行栈）：
            SELECT query_to_xml('SELECT count(*) FROM pg_catalog.pg_class', true, false, '')
            → HTTP 200，返回 419（pg_class 行数）
          表白名单（只含 order_info/user_info/region_info）与 pg_ 禁令
          同时被绕过。读 pg_shadow 失败仅因 t2s_reader 无权限，
          不是 Guard 起效。
目标实现：AST 解析（pglast/pg_query）后遍历 RangeVar 与 FuncCall；
          函数白名单；禁止任何参数为字符串且可求值 SQL 的函数
          （query_to_xml / query_to_xmlschema / xpath 之外的 xml 家族、
          dblink、lo_* 等）。
建议修改方式：引入 pglast 解析（PostgreSQL 官方语法树），
          在 AST 上做：①只允许 SelectStmt/CteStmt ②递归收集 RangeVar，
          与白名单比对 ③递归收集 FuncCall，与函数白名单比对
          ④禁止 SubLink 之外的动态 SQL。保留现有正则作为快速前置过滤。
影响范围：所有走 /query 的调用（含手工 SQL 与模型生成 SQL）。
```

### S1-02 结果集无字节上限，单次查询可返回任意大响应

```text
问题编号：S1-02
问题名称：只限行数不限字节，响应体可被放大到数百 MB
严重程度：高（S1）
涉及文件：backend/src/text_to_sql/sql_guard.py
涉及类/函数：execute_readonly
当前实现：:264 用 SELECT * FROM (sql) AS t2s_sub LIMIT max_rows+1 限行；
          :300 fetchmany(max_rows+1)；:317 全量 JSON 序列化。
存在的问题：无任何字节预算。实测 SELECT repeat('x',500000) FROM order_info LIMIT 5
          → 5 行、2,500,030 字符返回体。默认 max_rows=1000 时可放大到约 500MB，
          直接打爆应用进程内存与上游 nginx。
目标实现：行数 + 字节数双上限；超限截断并置 truncated 标记；
          单列超长值按上限截断并标注。
建议修改方式：在 execute_readonly 累积字节计数，达到上限即停止读取并
          置 byte_truncated；max_rows 与 max_bytes 一并进 query_policy
          （models.py:111-123 增加 max_bytes 校验）。
影响范围：所有查询响应；前端结果表格需处理 byte_truncated 提示。
```

### S1-03 数据源与目录 CRUD 无授权，构成 SSRF 与凭据外联面

```text
问题编号：S1-03
问题名称：任意已认证用户可创建任意 host/port 数据源并触发服务端外联
严重程度：高（S1）
涉及文件：backend/src/text_to_sql/api.py
涉及类/函数：_require_admin / create_datasource / test_connection_payload / scan
当前实现：_require_admin(:415-420) 仅用于三处（:169 关系核对、:235 指标审核、
          :274 发布）。数据源创建/修改/删除（:74-127）、扫描（:113-115）、
          连接测试（:82-86, :108-111）均无角色校验，只依赖 AuthMiddleware
          的「已登录」。
存在的问题：POST /datasources 接受任意 host/port，随后
          POST /datasources/connection-test 由服务端发起 TCP 连接。
          可用于探测内网端口、访问云元数据端点、对内部服务做协议探测。
          同时无「数据源归属/可见性」模型：任何用户可读写任何数据源元数据。
目标实现：数据源写操作限管理员；外联目标做私网/回环/链路本地地址拒绝
          或显式白名单；数据源增加 owner/visible_to。
建议修改方式：①create/update/delete/scan/connection-test 加 _require_admin
          ②在建立连接前解析主机名并对 127/8、10/8、172.16/12、192.168/16、
          169.254/16、::1、fc00::/7 做拒绝（与仓内既有的 egress 规则对齐，
          见 tests/test_http_egress.py）③t2s_datasource 增加 owner_id。
影响范围：前端数据源页；已有 5 个数据源需回填归属。
```

### S1-04 `queryPolicy.read_only` 是死配置

```text
问题编号：S1-04
问题名称：只读策略字段从未被读取，配置界面给出虚假保证
严重程度：中（S1 边缘）
涉及文件：backend/src/text_to_sql/models.py、sql_guard.py
涉及类/函数：_query_policy / execute_readonly
当前实现：models.py:116-123 校验并保存 read_only；execute_readonly 在
          sql_guard.py:287 无条件 conn.set_session(readonly=True)，
          从未读取 policy['read_only']。
存在的问题：用户关掉「只读」开关不会有任何行为变化；反之若将来有人按
          字段实现「可写」，会造成真实写入风险。当前是「假开关」。
目标实现：删除该字段，或让它真正决定（并禁止关闭）。
建议修改方式：短期从 API 契约与前端移除该字段；若保留，在
          execute_readonly 中断言 policy.get('read_only') is not False，
          否则拒绝执行并回 409。
影响范围：前端数据源表单、API 契约、已有 query_policy JSON。
```

### S1-05 只读数据库账号未被强制

```text
问题编号：S1-05
问题名称：安全性依赖部署者「用了只读账号」这一纪律，而非系统保证
严重程度：高（S1）
涉及文件：backend/src/text_to_sql/service.py、sql_guard.py
涉及类/函数：Text2SqlService.test_connection / execute_readonly
当前实现：连接使用用户填写 username/password；仅靠
          conn.set_session(readonly=True) 提供会话级只读。
存在的问题：结合 S1-01（query_to_xml 绕过），若数据源配置为具备
          高权限的账号（本机「电商业务演示库」即为 rag 账号），
          即可读取该账号可见的任意表。演示库用的 t2s_reader 属于
          人为约定，代码不作校验。
目标实现：连接测试时校验 session 只读且无写权限
          （SELECT pg_catalog.pg_is_in_recovery()/has_table_privilege 组合，
          或校验 rolcreatedb/rolsuper 为 false）；发布前强制校验。
建议修改方式：在 test_connection 与 scan 前执行
          SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user
          并拒绝高权限账号；把结论写入 t2s_datasource 以便审计。
影响范围：所有数据源；已有数据源在下次扫描/发布时被拦截。
```

### S2-01 逗号连接正则误报，多列 GROUP BY / ORDER BY 一律被拒

```text
问题编号：S2-01
问题名称：FROM 后的任意逗号被判定为多表逗号连接
严重程度：高（S2，直接阻断最常见的分析型 SQL）
涉及文件：backend/src/text_to_sql/sql_guard.py
涉及类/函数：validate_sql
当前实现：:151-152
          if re.search(r'\bFROM\b[^()]*?,', masked, re.IGNORECASE):
              raise SqlGuardError('SQL_UNSAFE', '请使用显式 JOIN，不允许多表逗号连接')
          该正则不认识子句边界，任何「FROM 之后、下一个左括号之前出现逗号」
          都会命中。
存在的问题：实测（本机运行栈，全部为合法单表/显式 JOIN 查询）：
            SELECT status, user_id, count(*) FROM order_info GROUP BY status, user_id   → 拒绝
            SELECT user_id, pay_amount FROM order_info ORDER BY user_id, pay_amount      → 拒绝
            两表 JOIN + GROUP BY r.city_name, o.status                                    → 拒绝
            GROUP BY status ORDER BY n DESC, status                                       → 拒绝
          单列 GROUP BY、IN 列表（括号内）不受影响，故测试未暴露。
          真实 NL 提问「用户所在城市和订单所属用户所在城市，分别有多少用户」
          生成的 SQL 全部使用显式 JOIN，仍被此规则误杀
          （run 记录 generated_sql 已留存，可复核）。
目标实现：AST 判定——SelectStmt.fromClause 中是否存在 JoinExpr 之外的
          多个 RangeVar 项。
建议修改方式：随 S1-01 的 AST 改造一并消除；过渡期可收窄为
          只检查 fromClause 文本区间，或直接移除该规则（逗号连接本身
          不构成安全风险，只是风格）。
影响范围：所有多维度聚合查询——正是 Text2SQL 的核心场景。
```

### S2-02 EXPLAIN 失败毒化事务，真实错误被掩盖

```text
问题编号：S2-02
问题名称：EXPLAIN 异常未回滚到保存点，导致后续错误信息失真
严重程度：中（S2，可诊断性）
涉及文件：backend/src/text_to_sql/sql_guard.py
涉及类/函数：execute_readonly
当前实现：:288-296
          with conn.cursor() as cursor:
              try:
                  cursor.execute('EXPLAIN (FORMAT JSON) ' + wrapped)
                  ...
              except Exception:
                  explain = None
          随后 :298 cursor.execute(wrapped)。psycopg2 中语句错误会把事务置为
          aborted，必须 ROLLBACK TO SAVEPOINT 才能继续。
存在的问题：实测 SELECT no_such_column FROM public.order_info
          → 返回 SQL_EXECUTION_FAILED: "current transaction is aborted,
            commands ignored until end of transaction block"
          用户看不到「列不存在」这一真实原因。同时 EXPLAIN 与真正执行
          各跑一次计划，成本翻倍。
目标实现：EXPLAIN 用 SAVEPOINT 包裹，失败即回滚到保存点；
          或先执行再取计划（EXPLAIN 仅用于展示时）。
建议修改方式：
          cursor.execute('SAVEPOINT t2s_explain')
          try: ...
          except: cursor.execute('ROLLBACK TO SAVEPOINT t2s_explain')
          else: cursor.execute('RELEASE SAVEPOINT t2s_explain')
影响范围：所有执行失败的错误码与文案；前端 error 展示。
```

### S2-03 无列级白名单，模型臆造字段只在执行期暴露

```text
问题编号：S2-03
问题名称：只校验表，不校验列与函数
严重程度：中（S2）
涉及文件：backend/src/text_to_sql/sql_guard.py
涉及类/函数：_validate_table_scope
当前实现：:224-253 只抽 FROM/JOIN 后的表名做白名单比对；
          SELECT 列表、WHERE、GROUP BY 中的列名完全不校验。
存在的问题：实测 SELECT no_such_column FROM public.order_info 通过校验
          （stage=execute），错误被 S2-02 进一步掩盖。
          模型编造字段无法在 validation 阶段给出「该字段不在当前范围」的
          明确反馈，也无法触发 S2-05 的自修复。
目标实现：AST 收集 ColumnRef，按作用域（别名→表）解析后与快照列集合比对；
          收集 FuncCall 与函数白名单比对。
建议修改方式：与 S1-01 同批实现。
影响范围：生成质量与错误可解释性。
```

### S2-04 校验失败无自修复回路

```text
问题编号：S2-04
问题名称：SQL 生成与校验是单次单向流程
严重程度：中（S2）
涉及文件：backend/src/text_to_sql/query_service.py
涉及类/函数：run_query
当前实现：:125-143 生成一次 → 校验一次 → 失败即 QueryFailure，
          由 :209-215 落 FAILED 并返回。
存在的问题：模型输出的 SQL 一旦触碰 Guard（含误报），用户只能改用更加
          自然语言或手工改 SQL。没有「把违规原因回灌给模型重生成 N 次」
          的回路。实测 1/5 条自然语言提问因此终态失败。
目标实现：最多 N 次重试；每次把违规码与提示拼进下一轮 prompt；
          记录每次尝试的 SQL 与错误（attempt 维度）。
建议修改方式：在 run_query 内加有界重试（N=2），把
          SqlGuardError.code/message 作为 retry_feedback 传入 _generate_sql；
          t2s_query_run 已有 stages/timing JSONB，可加 attempts 数组。
影响范围：生成成功率与耗时；需在 UI 展示「已重试」。
```

### S2-05 版本与向量无限累积，无 GC

```text
问题编号：S2-05
问题名称：每次配置变更产生全新知识集与向量，旧版本永不回收
严重程度：中（S2，稳定性）
涉及文件：backend/src/text_to_sql/version_repository.py、deploy/init/pg/18-text2sql.sql
涉及类/函数：create_version / finish_build；guard_config_version
当前实现：create_version 按 (datasource_id, revision) 生成整份知识；
          guard_config_version(:426-464) 禁止 DELETE 版本。
存在的问题：实测一个 3 表演示库已积累 25 个版本、610 条知识、602 条向量；
          其中活动版本只用 29 条知识。存储与检索成本随 revision 线性增长，
          且无任何清理入口。
目标实现：保留 N 个可用版本 + 活动版本；其余软删或硬删并级联清向量；
          定期任务。
建议修改方式：增加 version GC（保留最近 N 个 READY + 当前活动 + 被
          t2s_query_run 引用的版本）；向量表已有 ON DELETE CASCADE
          （20-text2sql-index.sql:12-13），删知识即清向量；需要先放开
          guard_config_version 对非活动版本的 DELETE 限制。
影响范围：存储、备份体积、检索延迟。
```

### S2-06 上下文硬截断静默丢表

```text
问题编号：S2-06
问题名称：build_context 按字符数截断，不感知表边界
严重程度：中（S2，规模化后必然触发）
涉及文件：backend/src/text_to_sql/sql_guard.py
涉及类/函数：build_context
当前实现：:469-472
          if len(text) > MAX_CONTEXT_CHARS:  # 24000
              text = text[:MAX_CONTEXT_CHARS] + '\n...（上下文已截断）'
存在的问题：离线实测（3/10/20/30 张表 × 12 列，带业务描述）：
            3 表 → 2,899 字符
            10 表 → 9,535 字符
            20 表 → 19,275 字符
            30 表 → 24,012 字符，触发截断
          截断点落在某列定义中间（"...    co"），且 30 张表中
          最后 5 张（table_025–table_029）被静默丢弃。
          表顺序是 schema/name 字典序，与问题相关性无关。
目标实现：Token 预算 + 按表边界截断 + 优先保留检索命中表。
建议修改方式：见 §5.9 的 Context Builder 重写；最低限度改为按表分组
          累加、超预算即停止并显式列出「已省略的表名」。
影响范围：任意规模 > ~25 张表的库。
```

### S2-07 索引构建同步阻塞 HTTP 请求，未接入统一任务中心

```text
问题编号：S2-07
问题名称：POST /versions/{id}/build 在请求线程内完成全量向量化
严重程度：中（S2，稳定性）
涉及文件：backend/src/text_to_sql/service.py
涉及类/函数：build_version
当前实现：:382-417 prepare_build(worker_id='api') → self._embed(全部 pending
          一次 HTTP) → finish_build。run_in_threadpool 承载。
存在的问题：无 worker、无重试、无进度、无取消；大规模目录会耗尽
          HTTP 超时；`t2s_index_job` 有 worker_id/heartbeat_at 但恒为 'api'，
          形态像租约却不是租约。统一任务中心（task_center）看不到这些任务。
目标实现：入队 → worker 领取 → 分批 embed → 心跳 → 断点续跑。
建议修改方式：复用 infrastructure/tasks/pg_queue（已有 FOR UPDATE SKIP LOCKED
          与 NOTIFY），注册 T2S_INDEX 任务类型；把 embed 改为分批（例如
          128 条/批）以支持续跑。
影响范围：索引构建；任务中心 UI 可见性。
```

### S2-08 `idempotency_key` 含随机串，`attempt` 恒为 1

```text
问题编号：S2-08
问题名称：幂等键不幂等
严重程度：低-中（S3）
涉及文件：backend/src/text_to_sql/version_repository.py
涉及类/函数：create_version / prepare_build
当前实现：:216 f'kb:{version_id}:{uuid4().hex}'
          :283 f'emb:{version_id}:{uuid4().hex}'
存在的问题：UNIQUE (datasource_id, idempotency_key)（18-text2sql.sql:264）
          永远不冲突；真正的并发保护来自
          uq_t2s_index_job_inflight 与 :262-265 的显式查询。
          attempt 从不自增，重试语义名存实亡。
目标实现：键确定为 f'emb:{version_id}' 之类的稳定值；重试时新建 attempt 行
          并自增 attempt。
建议修改方式：去掉 uuid4 后缀；prepare_build 计算 attempt = max+1。
影响范围：任务可观测性与重试语义。
```

### S2-09 `t2s_column` 缺 `last_seen_at` 列，但 API 读取

```text
问题编号：S2-09
问题名称：DTO 读取不存在的列，字段恒为 None
严重程度：低（S3）
涉及文件：backend/src/text_to_sql/models.py、deploy/init/pg/18-text2sql.sql
涉及类/函数：column_to_api
当前实现：models.py:337 'lastSeenAt': row.get('last_seen_at')
          但 t2s_column 只有 missing_since，没有 last_seen_at
          （t2s_table 两者都有）。
存在的问题：前端永远拿不到列的 lastSeenAt；语义与表不一致。
目标实现：二选一——加列，或从 DTO 删除该字段。
建议修改方式：删除该字段更简单；若保留监控语义则加列并在
          _upsert_column 中 now()。
影响范围：前端列详情展示。
```

### S3-01 8 阶段流水线中 4 个阶段是空的

```text
问题编号：S3-01
问题名称：STAGE_DEFS 声明了未实现的阶段
严重程度：低（S3，可观测性失真）
涉及文件：backend/src/text_to_sql/query_service.py
涉及类/函数：STAGE_DEFS / run_query
当前实现：:20-29 定义 tables/columns/values/relations/llm/validation/
          explain/execute 八段；:108-116 中 columns_ms、values_ms、
          relations_ms 由极廉价的纯内存操作计时，实测全部为 0。
存在的问题：前端 Debug 页展示 8 段「成功」，但 Column Retrieval、
          Value Retrieval、Relation Expansion 实际不存在。对外呈现的
          流水线与真实能力不符。
目标实现：阶段定义与真实步骤一一对应；未实现的阶段不出现。
建议修改方式：P1 实现分层检索后再填满；在此之前把阶段收敛为
          retrieval / llm / validation / explain / execute 五段。
影响范围：前端 Debug / 答案依据页。
```

### S3-02 Token 计量始终为空

```text
问题编号：S3-02
问题名称：usage 恒为 None / {}
严重程度：低（S3）
涉及文件：backend/src/text_to_sql/query_service.py、query_repository.py
涉及类/函数：_response / finish_success
当前实现：query_service.py:202 usage=None；:509 'usage': None；
          query_repository.py:155 _json(usage or {})。
存在的问题：实测 5 次真实生成，usage 全部为 None；t2s_query_run.usage
          列存在但无数据。无法做成本核算与配额。
目标实现：从模型响应（OpenAI 兼容 usage 字段）取值并落库。
建议修改方式：model.operator_client.invoke_llm 回传 usage；
          _generate_sql 透传；finish_success 写入。
影响范围：成本可观测性；未来配额。
```

### S3-03 SQL 生成 prompt 硬编码

```text
问题编号：S3-03
问题名称：生成模板写死在 Python 字符串里
严重程度：低（S3）
涉及文件：backend/src/text_to_sql/query_service.py
涉及类/函数：_generate_sql
当前实现：:440-460 system/user 两段中文字面量。
存在的问题：无法按方言/业务域切换模板；无法做 A/B；与仓内
          workflow/templates 的模板化实践不一致。
目标实现：模板文件 + 变量注入。
建议修改方式：抽到 text_to_sql/templates/，按 db_type 选择。
影响范围：生成质量调优效率。
```

### S3-04 前端 3 个死组件与 4 个死模块仍参与打包

```text
问题编号：S3-04
问题名称：演示期遗留代码未清理
严重程度：低（S3）
涉及文件：frontend/src/features/text2sql/
涉及类/函数：Text2SQLAttemptDrawer.vue / Text2SQLConditionsDialog.vue /
          Text2SQLSQLDraftDialog.vue / utils/text2sqlStorage.js(179 行) /
          utils/text2sql.js(162 行) / utils/text2sqlFlow.js(131 行) /
          utils/id.js
当前实现：上述组件与模块零导入或只被彼此引用。
存在的问题：Text2SQLSQLDraftDialog 内的文案「任意 SQL 的解析与执行
          尚未接入」与现行实现直接矛盾；Text2SQLAttemptDrawer 渲染「· 模拟」。
          打包体积与认知负担。
目标实现：删除。
建议修改方式：按「删依赖/删能力的四步验收法」移除并跑一次构建校验。
影响范围：前端体积与可维护性。
```

### S3-05 前端准备弹窗中的「指标名称/补充说明」被静默丢弃

```text
问题编号：S3-05
问题名称：UI 采集了服务端不存在的字段
严重程度：低（S3，误导用户）
涉及文件：frontend/src/features/text2sql/components/Text2SQLPreparationDialog.vue
涉及类/函数：prepareData（Text2SQLPage.vue:1395-1416）
当前实现：弹窗第 1 步采集 amountName / userName / notes，
          组件内注释 :165-166 明写「服务端没有对应字段」，
          prepareData 从不读取它们。
存在的问题：用户以为填的是正式语义配置，实际不落库、不参与生成。
目标实现：要么接入 t2s_metric（已有表），要么移除这些输入。
建议修改方式：映射到 t2s_metric 更合理——已有现成表与 API。
影响范围：前端准备流程。
```

### S3-06 关系编辑与多轮澄清：后端有能力，前端无入口

```text
问题编号：S3-06
问题名称：能力与界面不对称
严重程度：低（S3）
涉及文件：frontend/src/features/text2sql/api/text2sql.js、backend/src/text_to_sql/api.py
涉及类/函数：relations CRUD / parentRunId
当前实现：后端提供 POST/PATCH/DELETE relations 与
          POST relations/{id}/verification（api.py:144-172）；
          前端 api 模块无对应封装，关系只能只读查看。
          backend 接受 parentRunId（models.py:784-786），
          前端从不发送，无追问链路 UI。
存在的问题：关系（尤其 MANUAL 推断关系）无法维护，只能靠扫描得到的 FK；
          而 Relation Expansion 的前提正是可信关系。
目标实现：关系编辑抽屉 + 验证按钮；追问时带 parentRunId。
建议修改方式：先用现有 API 补 UI，不改后端。
影响范围：Schema 语义质量。
```

---

## 5. 检索能力差距

### 5.1 决定性事实：检索不参与生成

```python
# query_service.py:107-121
hits = self._repo.search_knowledge(version_id, vector, limit=24)   # 向量检索
timing['tables_ms'] = _ms(retrieval_started)

schema_context = sql_guard.build_context(snapshot)                  # 全量快照
timing['columns_ms'] = _ms(context_started)
```

`hits` 在文件内的全部使用点只有两处：`:157 retrieval = _retrieval_view(snapshot, hits)` 与 `_retrieval_view` 内部（`:535, :550`）。**没有任何一行把命中项传给 `build_context` 或 `_generate_sql`。**

推论：

- 向量索引、知识对象、版本发布对**生成结果**没有任何影响；
- 演示库只有 3 张表，全量塞进 Prompt 也放得下，因此**功能测试全部通过**，缺陷被小规模掩盖；
- 一旦表数超过约 25 张，Prompt 开始静默丢表（§4 S2-06），而丢掉哪些表与问题无关。

**这一状态是 2026-11-11 的明确取舍，不是遗漏。** 当时的决策记录写明：本版本不引入 ES/关键字检索，理由之一是「hits 目前只进『答案依据』不进生成提示，检索层还不影响答案」；并列出后续要做的事——「top-N 命中参与选表」「上下文超 24k 时按相关度而非快照字典序截断」，且建议优先在 PG 内用 `pg_trgm` + 余弦加权混合、ES 只作可重建派生索引。本审计对该决策的复核意见：**取舍在当时成立（单源 3 表、稳定优先），但现在必须执行其后续项**，因为演示库之外的真实库普遍超过 25 张表。

这也是「A/B/C 三选一」的判定依据：**B（Schema-aware Text2SQL）**，且是 B 中的下限形态 —— 有 Schema 知识对象与 Schema-aware Prompt，但检索未参与生成。

### 5.2 分项对比

| 能力 | 目标 | 当前 | 结论 |
|---|---|---|---|
| BM25 | 有 | 无（仓内有 ES 与 `es_store.search`，未接） | 缺失 |
| Vector | 有 | 有，pgvector 精确余弦，`version_id` 过滤 | 有，无 ANN |
| RRF | 有 | 无（`engine/retriever/fusion_retriever.py` 有 k=60 实现，未接） | 缺失 |
| Reranker | 有 | 无（`engine/post_retriever/*` 有两套实现，未接） | 缺失 |
| Table Retrieval | 有 | `search_knowledge` 在 TABLE/COLUMN/VALUE/RELATION/METRIC 混合池里取 top-24 | 部分 |
| Column Retrieval | 候选表内检索 | 无。列只作为知识对象被混检；无「在候选表内按字段语义找列」 | 缺失 |
| Relation Expansion | BFS/最短路径 | 无。`build_context` 平铺全部关系 | 缺失 |
| Value Retrieval | 枚举/别名/精确/BM25+Vector | 扫描期只收 LOW 基数；`_value_hints` 做内存子串匹配；`value_resolver` 查询期回库改写 | 部分（但见 5.4） |
| Context Builder | Token 预算 + 分级 | 全量快照 + 24k 字符硬截断 | 缺失 |
| Metadata Filter | datasource/version/type | 仅 `version_id`（`query_repository.py:94`）；无 `object_type`、无 `datasource_id` 谓词 | 部分 |

### 5.3 检索隔离与正确性

- 版本隔离：`WHERE vec.version_id = %s` 正确，且 `LIMIT 24` 是硬编码（`query_service.py:107`），不可配置。
- 数据源隔离：向量表有 `datasource_id` 但**查询不用它**（`query_repository.py:87-97`），隔离依赖版本 UUID 唯一性。向量表 `datasource_id/version_id` 也无外键（`20-text2sql-index.sql:14-16`），手工或异常写入可造成错配。建议加 `AND vec.datasource_id = %s`。
- 无 ANN 索引：`text2sql_index` 只有 3 个 btree。当前 602 条向量可接受；上万条后每次查询全表扫描。

### 5.4 值得保留的现有设计（优于目标方案）

**查询时值解析**（`value_resolver.py`）在架构上优于「预索引所有枚举值」：

- 扫描期只枚举 `LOW` 基数字段（≤20 个不同值，`scanner.py:23`），高基数字段（城市、商品）**不预置**；
- 查询时把 SQL 中的文本字面量回库做「精确 → 忽略大小写 → 去行政区后缀前缀 → 包含」四级匹配，唯一命中即改写，多命中报候选，零命中明确报错（`value_resolver.py:417-428`）；
- 实测：`city_name = '西安'` → 改写成 `'西安市'` 并返回 1；`IN ('西安','咸阳')` → 两条都改写；`LIKE '西安%'` 不动；不存在的城市明确报 `VALUE_NOT_FOUND`。

这条路径让「开放维度」不需要预索引，也不会有枚举漂移。**建议保留并在其上加一层可选的值 BM25 索引，而不是替换它。**

### 5.5 Context Builder 改造建议（最小可用形态）

```text
输入：question, snapshot, hits
1. 表选择：hits 中 object_type=TABLE 的 top-K（K=8），
   加上 hits 中 COLUMN/VALUE 所属的表，去重；
   若为空，回退到全量前 N 张并在响应中标注 fallback。
2. 列选择：在选中表内，命中列 + 主键 + 外键 + 时间字段 + semanticType=measure；
   其余列只给名字，不给描述。
3. 关系扩展：从选中表出发做 ≤2 跳 BFS，只保留 verified 或 FOREIGN_KEY 的关系；
   超过预算的最短路径优先。
4. 值：只给「与选中列相关」的枚举值，上限 40。
5. 指标：按 base_table_id 过滤。
6. Token 预算：按 table/column 粒度累加，超预算即停止并显式列出省略项。
7. 输出结构固定为 sections，便于落库与回放。
```

这七步全部可以在现有 `snapshot` 结构内完成，**不需要改表**。

---

## 6. 数据库差距

### 6.1 结论先行

目标设计的 7 张表（`t2s_datasource / t2s_table / t2s_column / t2s_relation / t2s_value / t2s_knowledge / t2s_index_job`）**全部存在且同名**；实际 18 张。差距不是「缺表」，而是以下 8 项。

### 6.2 现有表（18）

`text2sql`（17）：`t2s_datasource`、`t2s_table`、`t2s_column`、`t2s_relation`、`t2s_relation_column`、`t2s_value`、`t2s_metric`、`t2s_metric_column`、`t2s_metric_relation`、`t2s_config_version`、`t2s_knowledge`、`t2s_index_job`、`t2s_publication`、`t2s_query_run`、`t2s_favorite`、`t2s_feedback`、`t2s_workspace`
`text2sql_index`（1）：`t2s_knowledge_vector`

触发器函数 11 个（`guard_*` / `publish_version` / `touch_updated_at` 等），构成 DB 层状态机。

### 6.3 缺失表

| 缺失 | 为什么需要 | 优先级 |
|---|---|---|
| 无（建议新增 `t2s_benchmark_case` / `t2s_benchmark_result`） | 当前没有任何评测集载体；`tools/verify/verify-text2sql-e2e.py` 只有 1 条硬编码断言 | P1 |
| 无 `schema_migration` 记录 | 18/20/22 的执行状态无法查询，升级靠人工 | P1 |

### 6.4 缺失字段

| 表 | 缺失字段 | 影响 |
|---|---|---|
| `t2s_knowledge` | `token_count` / `embedding_model`（每版本一份，冗余但便于排查） | 预算与回溯 |
| `t2s_query_run` | `context_snapshot`（最终 Prompt） | **无法复现「为什么选这张表」** |
| `t2s_query_run` | `query_understanding`（意图/实体/维度度量） | 无 Semantic Planner 的落点 |
| `t2s_query_run` | `attempts`（重试轨迹） | 自修复不可观测 |
| `t2s_column` | `last_seen_at` | S2-09 |
| `t2s_datasource` | `owner_id` / `readonly_verified_at` | S1-03 / S1-05 |
| `t2s_index_job` | `scheduled_at` / `max_attempts` | 任务重试 |
| `t2s_config_version` | `error_message` | 版本失败原因只能去 job 表找 |

### 6.5 不合理字段

| 字段 | 问题 |
|---|---|
| `t2s_datasource.query_policy.read_only` | 死字段（S1-04） |
| `t2s_index_job.idempotency_key` | 含随机串，非幂等（S2-08） |
| `t2s_index_job.attempt` | 恒为 1，从不自增 |
| `t2s_knowledge.vector_namespace` / `vector_document_id` | 形似外部向量库引用，实际 namespace 是拼接串、document_id 是自身 UUID（`version_repository.py:331`）；易误导 |
| `t2s_knowledge_vector.content` | 与 `t2s_knowledge.content` 重复存储 |
| `t2s_column.is_unique` | 只表达单列唯一；复合唯一只在 `t2s_table.constraints_metadata` 里 |
| `t2s_knowledge.object_key` | 自由文本；正确性依赖生成方（当前用 UUID，安全） |

### 6.6 缺失约束 / 索引

| 项 | 现状 | 建议 |
|---|---|---|
| 向量维度 | `embedding vector` 无 typmod；维度只在应用层校验（`version_repository.py:310-315`） | 若确定单一模型，改 `vector(1024)` + HNSW；否则保留并在写入前强校验（已有）+ 加 HNSW 需固定维度 |
| ANN 索引 | 无 | 增加 HNSW（需固定维度）或对 version 分区的 IVFFlat |
| `t2s_knowledge_vector.datasource_id` / `version_id` | 无外键 | 加外键或至少在检索 SQL 中加 `datasource_id` 谓词 |
| `t2s_column(datasource_id)` | 无前导索引 | `CREATE INDEX ON t2s_column(datasource_id)` |
| `t2s_value(datasource_id)` | 无前导索引 | 同上 |
| `t2s_relation(source_table_id, datasource_id)` | 复合唯一索引前导列是 `datasource_id`，FK 检查走序列扫描 | 加 `(source_table_id, datasource_id)` |
| `t2s_feedback(datasource_id)`、`t2s_publication(version_id)`、`t2s_favorite(verified_version_id)` | 无 | 按查询需要补 |

### 6.7 是否需要 Migration

| 变更 | 是否必须 Migration | 说明 |
|---|---|---|
| 补索引（6.6） | 是 | 幂等 `CREATE INDEX IF NOT EXISTS`，可直接加 `23-text2sql-indexes.sql` |
| 删死字段（6.5） | 否（建议） | 保留列、停用 API 即可，避免破坏已部署库 |
| 加 `context_snapshot` 等列 | 是 | 幂等 `ADD COLUMN IF NOT EXISTS` |
| 向量维度固定 + HNSW | 是 | 需重建索引，按新文件名追加 |
| 版本 GC | 是 | 需放开 `guard_config_version` 的 DELETE 限制 |

**迁移机制本身的短板**：`18-text2sql.sql:2-4` 明写「Fresh installation ONLY」且 `CREATE SCHEMA text2sql`（无 IF NOT EXISTS），在已有 `text2sql` schema 的库上必然失败；`22-text2sql-cardinality.sql` 是后端硬依赖（`repository_pg.py:263,353` 无条件 SELECT 该列）但 `docs/database-schema.md:846-850` 未登记。**建议引入一个最小可用的 `schema_migration` 表 + 幂等 runner**，或在文档中把「按文件名顺序手工执行」固化为发布检查项。

### 6.8 需要提前抽到公共层的能力

按「领域数据保持独立、公共层只做投影与检索」的原则，只有三样值得抽：

1. **Hybrid Retriever 抽象**（BM25 ∥ Vector ∥ RRF ∥ Rerank）：仓内已有 `engine/primitives/interfaces.py` 的 `RagRetriever`、`QueryFusionRetriever`（RRF k=60）、`ExternalModelReranker`。建议抽成 `knowledge_engine/retrieval/`，Text2SQL 与后续 Operator 共用。
2. **Knowledge Object 投影契约**（`object_type` + `object_key` + `title` + `content` + `metadata` + `content_hash`）：`knowledge.py:18-26` 的 `KnowledgeDraft` 已经就是这个形状，抽出去即可。
3. **Policy Guard 骨架**（只读事务 + 超时 + 行/字节上限 + AST 校验接口）：`sql_guard.execute_readonly` 的执行部分可参数化为 `execute_readonly(connection, statement, policy)`，SQL 特有的是 AST 校验插件。

**不建议抽**：`t2s_*` 的业务字段（业务名、别名、语义类型、指标）应继续留在领域表，不要塞进一张万能 JSON 表。

---

## 7. 安全性评估

### 7.1 严重安全问题

| 编号 | 问题 | 实测证据 |
|---|---|---|
| S1-01 | `query_to_xml()` 内嵌 SQL 绕过表白名单与 `pg_` 禁令 | `SELECT query_to_xml('SELECT count(*) FROM pg_catalog.pg_class', true, false, '')` → 200，返回 419 |
| S1-03 | 数据源 CRUD 无授权 → SSRF / 内网探测 / 凭据外联 | `api.py:74-127` 无 `_require_admin`；`connection-test` 由服务端发起连接 |
| S1-05 | 只读账号未强制；结合 S1-01 等于「以数据源账号权限读全库」 | 演示库 `t2s_reader` 是人为约定；另一数据源直接用 `rag` 账号 |

### 7.2 高风险问题

| 编号 | 问题 | 实测证据 |
|---|---|---|
| S1-02 | 无字节上限，单查询可返回数百 MB | 5 行 × 500KB = 2.5MB 响应体 |
| — | 无成本阈值：EXPLAIN 已拿到 `total_cost`，但不做任何判断 | `JOIN ... ON true` ×5 → `total_cost=3.15e13`，正常执行 |
| — | `set_config('search_path', ...)` 未被拦截（`SET` 在禁用 token 里，`set_config()` 函数不在） | 实测通过 |
| — | 无 SQL 取消 / 无并发配额 | 单进程线程池；`statement_timeout` 兜底 |
| S1-04 | `read_only` 假开关 | 代码路径固定 `readonly=True` |

### 7.3 一般风险

- `current_database()` / `current_user` / `version()` 可被查询 —— 信息泄露但影响有限。
- `has_table_privilege()` 可探测权限。
- 错误信息把外部库的原始报错首行返回（`_safe_error`，截断 500 字符），可能泄露表名/角色名；当前设计可接受。
- 连接串密码经 `infrastructure.secrets.box`（AES-GCM，独立 AAD）加密，`credential_ref` 有非空 CHECK，接口从不回传密码（`models.py:291` 只回 `passwordConfigured`）。**这部分做得好。**

### 7.4 已做对的安全措施（应保留）

1. 只读事务 + `statement_timeout` + `connect_timeout` + `fetchmany(max_rows+1)`。
2. 单语句强制、写操作/DDL/事务控制 token 拒绝、`SELECT INTO`/`FOR UPDATE` 拒绝。
3. 表白名单来自**冻结快照**而非当前目录，历史运行可复现。
4. 值改写用 `_quote_literal` 正确转义单引号；标识符用 `_quote_identifier`。
5. 凭据加密 + AAD 隔离 + 从不回传。

### 7.5 安全结论

**Guard 是「防呆」，不是「安全边界」。** 真正的边界有三层，按可靠性排序：

1. 外部库账号的最小权限（部署纪律，代码不校验）—— 最有效；
2. 只读事务（代码强制）—— 防写有效，防读无效；
3. 正则 Guard（代码强制）—— 防常见手滑有效，防刻意绕过无效。

**行动项**：把第 1 层变成代码校验（S1-05），把第 3 层升级为 AST（S1-01），并补字节上限（S1-02）与授权（S1-03）。

---

## 8. 通用架构扩展评估

### 8.1 公共 Knowledge Engine

| 能力 | 现状 | 差距 |
|---|---|---|
| 统一数据源抽象 | 无。`text2sql` 自己的 `t2s_datasource`；KB 自己有 `knowledge_base` | 需抽 `DataSource` 接口 |
| 统一 Knowledge Object | **有**（`knowledge.py:18-26` `KnowledgeDraft`），但只在 text2sql 内 | 抽到公共层 |
| 统一知识对象 ID | 有（`object_type` + `object_key`） | 可直接复用 |
| 统一 ES 索引接口 | 有（`infrastructure/search/es_restful.py`） | text2sql 未用 |
| 统一 Vector 索引接口 | 弱。`retrieval/repository/vector_store.py`（KB 动态表）与 `graph_index_store.py`（HNSW）各写一套 | 需抽象 |
| 统一 Hybrid Retriever | 组件有（`FusionRetriever`）、编排无 | 抽公共编排 |
| 统一 Reranker | 有（`ExternalModelReranker` / `LLMReranker`） | 可直接复用 |
| 统一 Context Builder | 无 | 新建 |

### 8.2 Semantic Planner

**完全缺失。** 证据：

- `t2s_query_run` 没有 query understanding 字段；
- `parse_query_request`（`models.py:767-789`）只接受 question / parameters / datePolicy / 固定时间范围 / sql / model；
- 无意图分类、实体消解、维度度量识别；
- `parentRunId` 只落库（`query_service.py:90`），无澄清交互协议。

### 8.3 Operator Contract

**不存在统一的 Query Operator 接口。** 现存 `operators/` 是文档处理算子（`file_parse` / `text_split` / `graph_extract`，见 `docs/operator-interface.md`），运行在沙箱里，与「查询执行」是两回事。

但仓内已有可复用的原语接口（`engine/primitives/interfaces.py`：`RagRetriever`、`RagQueryEngine`、`RagNodePostprocessor`）。建议的 Query Operator 契约应与之同构：

```python
class QueryOperator(Protocol):
    knowledge_types: ClassVar[tuple[str, ...]]   # NL2SQL -> ('TABLE','COLUMN','RELATION','VALUE','METRIC')

    def retrieve(self, plan: QueryPlan, ctx: RetrieveContext) -> OperatorContext: ...
    def plan(self, question: str, ctx: OperatorContext) -> QueryPlan: ...
    def validate(self, plan: QueryPlan, ctx: OperatorContext) -> ValidatedPlan: ...
    def execute(self, plan: ValidatedPlan, ctx: RuntimeContext) -> ResultSet: ...
```

Text2SQL 完全可以按这个形状改造：`retrieve`=分层检索、`plan`=SQL 生成（逻辑计划即 SQL）、`validate`=AST Guard、`execute`=只读执行。**SQL 特有的是 `validate` 的 AST 分支与 `execute` 的方言，接口本身是通用的。**

### 8.4 五种 Operator 扩展能力

| Operator | 需要的基础能力 | 当前能否复用 | 需新增知识对象 | 需新增领域模块 | 需独立表 | 需新检索策略 | 需独立 Runtime |
|---|---|---|---|---|---|---|---|
| **NL2SQL**（已实现） | Schema RAG + AST + Executor | 自有 | — | — | 已有 | Hybrid（P1） | 已有 |
| **NL2API** | OpenAPI 知识 + 参数校验 + HTTP Runtime | 部分：Model Provider、Embedding、知识对象 | `API` / `ENDPOINT` / `PARAM` / `SCHEMA` | `api_operator/`（spec 解析、参数绑定） | 是（`t2a_*`） | BM25 为主（路径/字段名匹配） | 是（HTTP client + 鉴权注入） |
| **NL2Graph** | 图 Schema + 关系检索 + 图查询校验 | **高**：`graph/` 领域已有 schema、抽取、pgvector 检索、Cypher/图查询 | `NODE` / `EDGE` / `PROPERTY` | 复用 `graph/`，补 graph query validator | 否（复用 `graph_*`） | 图向量 + 关系扩展 | 有（图查询执行） |
| **NL2DSL** | 语法知识 + 类型化 AST + 编译器 | 低：需自建语法表示 | `GRAMMAR` / `TERM` / `RULE` | `dsl_operator/` | 是 | 语法感知检索 | 是（编译器 + 求值器） |
| **NL2Search** | 索引 Mapping + 字段检索 + Query DSL 校验 | **高**：`infrastructure/search/` + `es_store` 已具备 | `INDEX` / `FIELD` / `MAPPING` | 复用 `retrieval/`，补 Query DSL 校验 | 否 | Mapping + 字段级 BM25 | 是（ES 查询执行，只读） |

**判断**：NL2Graph 与 NL2Search **最值得优先扩展**——它们需要的底层能力（图检索、ES 检索、向量）在本仓已经成熟，只差一层「自然语言 → 查询」的 Operator 壳。NL2API 次之（只需 HTTP Runtime 与参数校验）。NL2DSL 最贵，不建议在公共层成型前启动。

> 注意：不要为「统一」而把五类知识对象塞进一张表。`t2s_metric` / `graph_*` / OpenAPI spec 的字段差异极大，强行合并会立刻退化成 JSON 泥潭。

### 8.5 最小改造路径（不重写）

```text
第 1 步（1~2 周）：只改 3 个文件，让检索真正生效
  · knowledge.py        导出 object_type 分层的 weight（无需改表）
  · query_service.py    build_context(snapshot) -> build_context(snapshot, hits)
  · sql_guard.py        新增 build_context_filtered()，保留旧函数做回退
  验收：同一问题在「无关问题」与「相关问题」下，Prompt 中的表集合不同

第 2 步（2~3 周）：把 Guard 换成 AST
  · 新增 sql_guard_ast.py（pglast），validate_sql 委派
  · 保留现有正则作前置快速过滤
  验收：S1-01 / S2-01 的探针全部反转为期望结果；既有的 61 条 text2sql 单测全绿

第 3 步（2 周）：执行侧硬化
  · 字节上限、SAVEPOINT、成本阈值、取消
  验收：§9 的验证脚本全部通过

第 4 步（3~4 周）：抽公共 Hybrid Retriever
  · 复用 engine 的 RRF/Reranker，Text2SQL 接 BM25(pg_trgm 或 ES)+Vector+RRF
  验收：Table 召回率与 Context 体积同时改善

第 5 步（4 周+）：Query Operator 接口 + Semantic Planner
```

---

## 9. 真实代码验证记录

### 9.1 已执行的测试

| # | 项目 | 命令 | 结果 |
|---|---|---|---|
| 1 | Text2SQL 后端单测 | `pytest tests/test_text_to_sql_*.py` | **61 passed**（1.29s） |
| 2 | 后端全量单测 | `pytest` | **2530 passed, 7 deselected**（85.83s） |
| 3 | 前端单测 | `npm run test:unit` | **992 passed / 102 files**（48.54s） |
| 4 | 前端生产构建 | `vue-cli-service build --mode production` | **通过**；`module.text2sql-legacy` 167.67 KiB（gzip 45.88 KiB） |
| 5 | 真实 NL→SQL→执行 | 5 条自然语言提问（已配置模型） | 4 成功 / 1 被误杀（S2-01） |
| 6 | SQL Guard 探针 | 20 条恶意/越权 SQL | 16 拦截 / 2 通过（`query_to_xml`、`set_config`）/ 2 误杀相关 |
| 7 | 合法 SQL 探针 | 8 条（单表/两跳 JOIN/CTE/子查询/引号标识符/聚合） | 8 通过 |
| 8 | 逗号连接误报 | 8 条 | 4 误杀（全部为多列 GROUP BY/ORDER BY） |
| 9 | 值解析 | 6 条 | 4 改写正确 / 1 明确报缺失 / 1 LIKE 不动 |
| 10 | 截断 | 1728 行 × 1 列 | 1000 行 + `truncated=true` |
| 11 | 字节上限 | `repeat('x',500000)` × 5 | 2,500,030 字符，**未拦截** |
| 12 | Context 截断 | 离线 `build_context` | 30 表触发截断，丢 5 表 |

### 9.2 未验证项（环境不具备）

| 项 | 原因 |
|---|---|
| 大表下的 `statement_timeout` 触发 | 演示库无大表；`generate_series` 被表白名单拦截，`JOIN ON true` 只到 248,832 行（未超 30s） |
| 多数据源并发与连接池行为 | 无连接池，未做压测 |
| 索引构建失败恢复 | 需构造 embedding 服务故障 |
| MySQL / Oracle / SQL Server 扩展 | 应用层直接拒绝（`models.py:15`），无法验证 |
| 跨数据源越权读取 | 需两个数据源指向同一外部库并构造越权 SQL；当前无此场景 |
| 前端视觉回归 | 本次为架构审计，未做截图基线 |

### 9.3 测试覆盖的盲区（重要）

现有 61 条 text2sql 单测**全部通过**，但漏掉了本次发现的全部 S1/S2 级问题：

- `test_text_to_sql_query.py:55` 测了「多表逗号连接被拒」，但**没有一条多列 GROUP BY / ORDER BY 的正向用例** → S2-01 未被发现；
- **没有 `query_to_xml` / `set_config` 等函数级绕过用例** → S1-01 未被发现；
- 没有结果字节上限用例 → S1-02；
- 没有「执行失败时错误码应可辨识」用例 → S2-02；
- 没有列级白名单用例 → S2-03；
- `test_text_to_sql_query.py:189` 的端到端用例 monkeypatch 了 `_repo` 与 `_llm`，因此**无法暴露「检索不参与生成」**；
- 前端 `text2sql.page.spec.js` 只断言空壳渲染（h1、textarea、空状态），不断言任何 API 载荷。

**建议**：把 §9.1 的第 5–12 项固化为 `tools/verify/verify-text2sql-guard.py`（参照已有的 `verify-text2sql-e2e.py`），纳入发布检查。

---

## 10. 优先级路线图

### P0：必须修复（安全/正确性/稳定性）

| # | 目标 | 修改模块 | 影响范围 | 前置依赖 | 验收标准 |
|---|---|---|---|---|---|
| P0-1 | Guard 改 AST，消除 `query_to_xml` 绕过与逗号误报 | `sql_guard.py` + 新增 `sql_guard_ast.py` | 所有查询路径 | 引入 `pglast` | ①`query_to_xml` 内嵌系统表 → 拒绝 ②4 条多列 GROUP BY → 通过 ③既有 61 条单测全绿 ④新增 ≥20 条 AST 用例 |
| P0-2 | 结果字节上限 | `sql_guard.py:execute_readonly`、`models.py:_query_policy` | 查询响应 | 无 | `repeat('x',500000)×5` → 被截断并标记；正常查询不受影响 |
| P0-3 | EXPLAIN 用 SAVEPOINT；保持事务可用 | `sql_guard.py:288-301` | 错误诊断 | 无 | `SELECT no_such_column` → `SQL_UNKNOWN_COLUMN` |
| P0-4 | 数据源写操作授权 + 私网目标拒绝 | `api.py`、`service.py` | 数据源管理 | 无 | 非管理员 POST /datasources → 403；host=169.254.169.254 → 400 |
| P0-5 | 只读账号校验 + 移除 `read_only` 假开关 | `service.py:test_connection`、`models.py`、前端表单 | 数据源配置 | 无 | 高权限账号连接测试 → 409；契约中不再有 read_only |

### P1：下一版本必须完成（Schema RAG 质量）

| # | 目标 | 修改模块 | 影响范围 | 前置依赖 | 验收标准 |
|---|---|---|---|---|---|
| P1-1 | **检索接入生成**：`build_context(snapshot, hits)`，分层筛选 | `query_service.py`、`sql_guard.py`、`knowledge.py` | 生成质量 | 无 | 同一问题的 Prompt 只含命中表 + 补全关系表；无关问题不再带全表 |
| P1-2 | Context Builder 重写：Token 预算 + 分级 + 表边界截断 + 省略标注 | 新增 `context_builder.py` | 生成质量、可观测性 | P1-1 | 30 表时不再静默丢表；超预算显式列出省略表 |
| P1-3 | Column Retrieval：候选表内按语义检索列 | 新增 `column_retriever.py` | Schema Linking | P1-1 | 「同名字段」场景正确区分 `user_info.city_id` 与 `region_info.city_id` |
| P1-4 | Relation Expansion：≤2 跳 BFS / 最短路径 / verified 优先 | 新增 `relation_expander.py` | JOIN 正确性 | P1-1 | 两跳问题自动补全中间表；不可信关系不进上下文 |
| P1-5 | BM25 + RRF | `query_repository.py`、新增 `hybrid_retriever.py` | 召回 | P1-1 | 关键词类问题（表名/字段名直命中）召回提升；有对照数据 |
| P1-6 | Reranker 接入 | 复用 `engine/post_retriever` | 排序质量 | P1-5 | top-8 命中率有对照提升 |
| P1-7 | 生成自修复（有界重试，回灌违规原因） | `query_service.py` | 成功率 | P0-1 | 误杀类失败可由重试恢复；attempt 可观测 |
| P1-8 | 补落库：最终 Prompt、Token、每阶段真实耗时 | `query_repository.py`、`query_service.py`、`18-text2sql.sql` | 可观测性 | 无 | 任一 run 可完整回放「给模型的原文」 |
| P1-9 | 版本 GC | `version_repository.py`、DDL | 存储 | 无 | 保留 N+1 个版本；向量级联清理 |
| P1-10 | Text2SQL Benchmark（≥50 条，含单表/多表/聚合/时间/枚举/同名/多跳/不存在字段/恶意/超大） | 新增 `t2s_benchmark_*` + `tools/verify` | 质量基线 | P1-1~P1-7 | 指标：执行成功率、Schema Linking 准确率、SQL 语义正确率、平均耗时、Guard 误杀率 |

### P2：架构增强

| # | 目标 | 修改模块 | 前置依赖 | 验收标准 |
|---|---|---|---|---|
| P2-1 | 抽公共 `knowledge_engine/`：KnowledgeObject 契约 + HybridRetriever + Reranker | 新建包，`text_to_sql` 改为消费者 | P1-5/P1-6 | Text2SQL 与文档 RAG 共用同一 Retriever 接口 |
| P2-2 | Query Operator 接口 | 新建 `knowledge_engine/operator.py` | P2-1 | Text2SQL 实现 `retrieve/plan/validate/execute`；既有行为不变 |
| P2-3 | Policy Guard 骨架（只读/超时/行/字节/AST 钩子） | 新建 | P0-1/P0-2 | 至少两个 Operator 复用 |
| P2-4 | 索引构建迁到 task_center | `service.py`、`version_repository.py` | 无 | 任务中心可见、可取消、可重试 |
| P2-5 | ANN 索引（HNSW，固定维度） | `20/23-text2sql-index.sql` | 确定单一 embedding 维度 | 1 万向量下检索 <50ms |
| P2-6 | 前端：关系编辑、量化指标可视化、检索调试（RRF/Rerank 分） | `features/text2sql` | P1-1/P1-5 | 关系可增删改验证；Debug 页显示真实分数 |
| P2-7 | Migration runner + `schema_migration` 记录 | `deploy/` | 无 | 18/20/22 执行状态可查；可重复执行 |

### P3：未来扩展

| # | 目标 | 说明 |
|---|---|---|
| P3-1 | NL2Graph | 复用 `graph/` 领域，新增 graph query validator 与自然语言入口 |
| P3-2 | NL2Search | 复用 `infrastructure/search/`，新增 index mapping 知识对象与 Query DSL 校验 |
| P3-3 | NL2API | 新增 OpenAPI 知识对象、参数绑定、HTTP Runtime |
| P3-4 | NL2DSL | 最后做，需类型化 AST 与编译器 |

---

## 11. 最终架构建议

### 11.1 当前真实架构

```text
┌──────────────────────────── 前端 ────────────────────────────┐
│ Text2SQLPage.vue（查询/历史/数据源/验证反馈）                   │
│  └ 前端封装 38 个端点、UI 实际调用 35 个；关系编辑/澄清无 UI     │
└───────────────────────────┬──────────────────────────────────┘
                            │ REST  /api/co-knowledge/v1/text2sql
┌───────────────────────────▼──────────────────────────────────┐
│ api.py（44 条路由，无授权） → service / query_service          │
│                                                              │
│  ┌──────────────── 查询主链（实际生效）────────────────┐        │
│  │ parse_query_request                              │        │
│  │   → get_active_context(version + 冻结快照)         │        │
│  │   → build_context(**全量快照**)  ← 24k 字符硬截断   │        │
│  │   → _value_hints(全量值子串匹配)                   │        │
│  │   → LLM 生成 SQL（单次，无自修复）                  │        │
│  │   → 正则 Guard（表白名单，无列/函数白名单）          │        │
│  │   → 值解析回写（回库改写字面量，✅ 设计好）           │        │
│  │   → 只读执行（超时/行上限，无字节上限）              │        │
│  └─────────────────────────────────────────────────┘        │
│                                                              │
│  ┌──────── 向量检索（旁路，只用于展示）────────┐              │
│  │ embed_query → pgvector 余弦 top-24         │              │
│  │   （无 BM25 / RRF / Rerank / ANN 索引）      │              │
│  └────────────────────────────────────────────┘              │
│                                                              │
│  知识构建：冻结快照 → 5 类知识对象 → 全量 embed                │
│  版本：revision 级全量重建，无 GC                              │
└───────────────┬──────────────────────────┬───────────────────┘
                │                          │
        text2sql (17 表)            text2sql_index (1 表)
        复合外键隔离 datasource      vector 无维度、无 ANN
                │
       外部 PostgreSQL（只读会话，账号权限决定真实边界）
```

### 11.2 建议目标架构（最小改造，不重写）

```text
                     RAGStudio
                         │
                  Knowledge Engine
                         │
        ┌────────────────┴─────────────────┐
        │  Unified Knowledge Retrieval     │  ← P2-1 抽公共层
        │  BM25 ∥ Vector → RRF → Rerank    │  ← P1-5 / P1-6（复用 engine 组件）
        │  Metadata Filter（datasource/type）│
        └────────────────┬─────────────────┘
                         │
                  Context Builder           ← P1-2（Token 预算 + 分级 + 表边界）
                         │
                 Semantic Planner           ← P2-2（意图/实体/度量 + 澄清协议）
                         │
                 Logical Query Plan
                         │
            ┌────────────┴────────────┐
            │      Query Operator     │  ← P2-2（retrieve/plan/validate/execute）
            └────────────┬────────────┘
                         │
        ┌────────────────┴─────────────────┐
        │  NL2SQL Operator（第一个实现）     │
        │  · Schema Linking  ← P1-3        │
        │  · Relation Expansion ← P1-4     │
        │  · AST Guard      ← P0-1         │
        │  · 自修复回路      ← P1-7         │
        └────────────────┬─────────────────┘
                         │
               Policy / Runtime              ← P2-3（只读/超时/行/字节/成本）
                         │
                 Execution / Result
                         │
             外部 PostgreSQL（只读账号，代码校验）
```

### 11.3 两者差异

| 层 | 当前 | 目标 | 改造量 |
|---|---|---|---|
| 检索 | 旁路、混合对象池、无融合 | 前置、分层、Hybrid | 中（复用 engine 组件） |
| Context | 全量 + 字符截断 | 预算 + 分级 + 表边界 | 中（新文件，不改表） |
| Planner | 无 | 意图/实体/度量/澄清 | 大（新领域） |
| Operator | 无 | 统一接口 | 中（接口 + 一次适配） |
| Guard | 正则 | AST + Policy | 中（P0-1） |
| Runtime | 只读 + 超时 + 行 | + 字节 + 成本 + 取消 | 小 |
| 知识 | 5 类对象，版本冻结 | 同（保留） | **零** |
| 数据库 | 18 表，复合外键 | 同（仅补索引/列） | **小** |

**关键判断：知识层与数据层不需要重构。** 需要改的是「检索到生成」的那一段接线，以及「校验与执行」的硬化。

### 11.4 最小改造后的模块结构

```text
backend/src/
├── knowledge_engine/                  # 新增（P2-1）
│   ├── object.py                      # KnowledgeObject 契约（搬 knowledge.py 的 KnowledgeDraft）
│   ├── retriever.py                   # HybridRetriever：BM25 ∥ Vector → RRF
│   ├── rerank.py                      # 适配 engine/post_retriever
│   ├── context.py                     # ContextBuilder：预算 + 分级 + 表边界
│   ├── operator.py                    # QueryOperator 协议（P2-2）
│   └── policy.py                      # Policy Guard（P2-3）
├── text_to_sql/                       # 保持现有 15 个文件
│   ├── api.py / service.py / query_service.py
│   ├── knowledge.py                   # 保留：Text2SQL 的知识投影实现
│   ├── sql_guard.py                   # 保留：改为委派 AST + Policy
│   ├── sql_guard_ast.py               # 新增（P0-1）
│   ├── context_builder.py             # 新增（P1-2），或直接用 knowledge_engine.context
│   ├── column_retriever.py            # 新增（P1-3）
│   ├── relation_expander.py           # 新增（P1-4）
│   └── value_resolver.py              # 保留（设计优于目标）
└── ...（其余领域不动）
```

### 11.5 下一阶段开发任务拆分

**迭代 1（P0，2 周）** —— 止血
1. `sql_guard_ast.py`：pglast → 单语句 / 只读 / 表+列+函数白名单
2. `execute_readonly`：SAVEPOINT、字节上限、成本阈值
3. `api.py`：数据源写操作授权 + 私网目标拒绝
4. `service.py`：只读账号校验；移除 `read_only`
5. 回归：61 条单测 + 新增 §9.1 探针脚本，全部固化

**迭代 2（P1 前半，2 周）** —— 让检索生效
6. `build_context(snapshot, hits)` + `context_builder.py`
7. `column_retriever.py`
8. `relation_expander.py`
9. 落库 `context_snapshot` / `usage` / 真实阶段耗时

**迭代 3（P1 后半，3 周）** —— 提升召回
10. BM25（ES 或 `pg_trgm`）+ RRF
11. Reranker 接入
12. 生成自修复（有界重试）
13. `t2s_benchmark_*` + 50 条评测集 + 指标看板

**迭代 4（P2，4 周）** —— 抽象
14. `knowledge_engine/` 抽包，Text2SQL 改为消费者
15. `QueryOperator` 协议 + Text2SQL 适配
16. 索引构建迁 task_center
17. ANN 索引 + 版本 GC + migration runner

**迭代 5（P3）** —— 扩展
18. NL2Graph（复用 `graph/`）→ NL2Search（复用 `infrastructure/search/`）→ NL2API → NL2DSL

---

## 12. 附：正向结论清单（当前设计优于或达到目标，不应改动）

1. **复合外键把 `datasource_id` 绑进每一个父引用**，使跨数据源挂错在 DB 层不可能发生 —— 强于目标设计。
2. **版本冻结快照 + 不可变触发器 + 发布审计表**（`t2s_config_version` / `t2s_publication` / `guard_*`）—— 强于目标设计，历史查询可精确回放。
3. **扫描不覆盖人工语义**：`_upsert_column`（`repository_pg.py:578-605`）只更新结构列，`business_name/business_description/business_aliases/semantic_type` 原样保留；`_apply_relations`（`:621-622`）遇到 `MANUAL` 关系直接跳过 —— 这是 Schema 同步最容易写错的地方，这里写对了。
4. **查询时值解析**优于预索引全量枚举（见 §5.4）。
5. **`t2s_metric` 指标知识对象**超出目标设计，且已进入 Prompt。
6. **表默认 `enabled=false`**（`18-text2sql.sql:62`）—— 扫描不会自动把整库暴露给查询，是好的安全默认值。
7. **凭据加密 + AAD 隔离 + 从不回传**。
8. **前端真实接线度高**：后端 44 条路由中封装 38 条、UI 实际调用 35 条，演示数据已基本退到边缘（仅剩示例问题与文案回退）。

---

*报告生成：2026-11-12。审计期间未修改任何业务文件；仅新增本文件。运行探针产生的查询历史记录可通过 `DELETE /text2sql/runs` 清理。*
