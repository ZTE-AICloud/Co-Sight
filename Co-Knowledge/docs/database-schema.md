# 数据库 Schema 参考

> **当前口径**：
> - 语义类型已收口：`kb_kbase.operator_id` 为 `integer`，`status` 为 `smallint`（+CHECK），
>   时间为 `timestamptz`，布尔列（`is_published` / `system` / `enabled_flag` / `can_spread`）
>   为 `boolean`；静态子表有外键、CHECK 与表注释。
> - 索引/约束名统一：`<table>_pkey` / `<table>_<cols>_uidx` / `idx_<table>_<cols>` /
>   `fk_<子表>_<父表>`。
> - **没有软删除**：删除即物理 `DELETE`，没有 `is_enabled` 列与回收站。
>   详见 [`docs/data-deletion-policy.md`](data-deletion-policy.md)。
> - 文档库动态表为 `doc_<id>_vector` / `doc_<id>_chunk`；所有表最后两列为
>   `created_at` / `updated_at timestamptz`（自动刷新触发器）。
>
> **结构来源**：从标准部署的 PostgreSQL 16 + pgvector 读取（`information_schema` /
> `pg_catalog`）；表结构反映当前 schema 版本，行数随数据量变化。
> **适用范围**：`deploy/docker-compose.yml` 起的标准本地栈。
>
> 复现本文数据：
>
> ```bash
> docker exec rag-studio-postgresql-1 psql -U rag -d rag_studio -c '\dt *.*'
> ```

---

## 1. 总览

### 1.1 一个 database + 五个 schema

| database | 角色 | 谁在读写 | 连接开关 |
|---|---|---|---|
| **`rag_studio`** | **全栈唯一业务库**：库/目录/切片关系/任务/算子/图谱元数据 + 动态向量表 + `flow_*` 编排三表 + `model_registry` + Text2SQL 元数据 | `rag-knowledge-base`（唯一业务进程） | `POSTGRES_DB`（默认 `rag_studio`）；应用侧 `RKB_DB_NAME` 同值 |

**单库部署**：整栈只有一个业务库 `rag_studio`。**本栈不存在跨库查询**。

五个 schema：

| schema | 内容 |
|---|---|
| `public` | 固定表：元数据、任务、算子、画布、模型注册表 |
| `kb_index` | **动态表**：每个知识库一对「向量表 + 切片表」；图谱库导入后另有 `_vector` 检索索引 |
| `task_center` | 统一任务队列与尝试历史（文件导入 / 图谱抽图 / 图谱导入 / Text2SQL 索引） |
| `text2sql` | Text2SQL 数据源、结构目录、语义指标、版本化检索知识与查询工作台 |
| `text2sql_index` | Text2SQL 按数据源分表的向量索引（`t2s_vec_<datasourceId>`，构建时建表） |

### 1.2 表清单

**`rag_studio.public`（核心业务表）**

| 表 | 用途 |
|---|---|
| `kb_kbase` | 知识库主表（文档库 + 图谱库） |
| `kb_directory` | 目录/文件树（folder 与 file 同表，自引用 `parent_id`） |
| `kb_directory_property` | 文件/目录的键值属性 |
| `kb_node_relation` | 「文件 → 向量行」关系（`chunkId` 的主键表） |
| `operator` | 算子注册表 |
| `operator_param` | 算子入参定义 |
| `operator_prop` | 算子属性（KV） |
| `graph_schema` | 图谱 schema（本体定义） |
| `graph_registry` | 图谱库登记 |
| `flow_workflow` | 检索编排工作流元数据 |
| `flow_draft` | 画布草稿（JSON 原样存） |
| `flow_release` | 发布快照（运行时只读，只 INSERT） |
| `model_registry` | **模型注册表**（llm / embedding / rerank），保存即生效 |
| `kb_storage_registry` | 知识库存储生命周期（见 §5.5） |
| `agent_api_key` | Agent 接口 API Key（见 §3.8） |
| `agent_api_key_usage` | API Key 调用计数（见 §3.8） |
| `auth_user` / `auth_session` | 本地账号与会话（见 §3.9） |
| `chat_query_trace` | 查询链路耗时（仅指标，30 天保留，见 §3.10） |

> 动态表随建库/删库变化；行数随数据导入变化，不在文档中维护固定值。

**`rag_studio.task_center`（任务管理）**

| 表 | 用途 |
|---|---|
| `task` | 统一异步任务表：`FILE_IMPORT` / `GRAPH_EXTRACT` / `GRAPH_IMPORT`，统一状态与进度 |

旧的 `public.kb_import_task` / `public.graph_extract_task` / `public.graph_import_task`
已退役（`deploy/init/pg/20-drop-task-compat-views.sql`），三类任务只剩
`task_center.task` 一个入口。

**`rag_studio.kb_index`** 按库动态建表：

| 形态 | 库类型 | 表名 |
|---|---|---|
| 向量表 | 文档库 | `doc_<kbaseId>_vector` |
| 切片表 | 文档库 | `doc_<kbaseId>_chunk` |
| 切片表 | 图谱库 | `graph_<kbaseId>_chunk` |
| 实体表 | 图谱库 | `graph_<kbaseId>_vertex` |
| 边表 | 图谱库 | `graph_<kbaseId>_edge` |
| 检索索引 | 图谱库 | `graph_<kbaseId>_vector`（导入时懒建） |

**`rag_studio.text2sql`（Text2SQL 元数据，18 表）**

| 层次 | 表 | 用途 |
|---|---|---|
| 连接 | `t2s_datasource` | 外部库连接（`credential_ref` 存 `enc:v1:` 密文）、schema 范围、主题、查询策略、`config_revision`、活动版本、`embedding_model`、`llm_model`（SQL 生成模型，可随时改，NULL = 部署默认） |
| 结构 | `t2s_table` / `t2s_column` | 扫描得到的原始注释与人工语义分开；`enabled` 是查询范围；`missing_since` 标记源对象消失；`value_cardinality`（LOW/HIGH/UNKNOWN）与 `distinct_value_count` 标记值基数，**只对已启用表上的已启用列**自动收录取值 |
| 关联 | `t2s_relation` / `t2s_relation_column` | 外键/逻辑关联与**有序**列对；人工关联修改会清除核对标记 |
| 枚举 | `t2s_value` | 封闭小字典的人工名称/同义词，加上扫描自动发现的低基数值（`source_type=DATABASE`）；标识类列（id/uuid/hash/邮箱/路径等）与 UUID/文件名取值不收录；城市、商品等开放维度不预置，查询时回库解析 |
| 指标 | `t2s_metric` / `t2s_metric_column` / `t2s_metric_relation` | 指标表达式、过滤 AST、时间字段、可加性与依赖列/关联 |
| 版本 | `t2s_config_version` | 冻结配置快照、内容 hash、embedding 模型/维度、构建状态 |
| 检索知识 | `t2s_knowledge` | 按版本保存 TABLE/COLUMN/VALUE/RELATION/METRIC/NOTE 文本与外部向量引用；`index_status` 是各存储的汇总态 |
| 存储绑定 | `t2s_knowledge_binding` | 每个知识对象在每种存储（VECTOR / ES）里的索引状态与外部标识 |
| 异步 | `t2s_index_job` | SCHEMA_SYNC / KNOWLEDGE_BUILD / EMBEDDING 的幂等任务与尝试 |
| 发布 | `t2s_publication` | 活动版本切换审计 |
| 查询 | `t2s_query_run` | 固定版本/日期边界的问题、SQL、口径、结果预览与失败记录 |
| 工作台 | `t2s_favorite` / `t2s_feedback` / `t2s_workspace` | 常用查询、反馈流转、草稿与偏好 |

约束与触发器（`guard_config_version` / `guard_index_job` / `guard_query_run` /
`guard_knowledge_write` / `guard_active_version` / `publish_version` /
`archive_versions` / `purge_archived_knowledge`）在
`deploy/init/pg/18-text2sql.sql`；向量表 `text2sql_index.t2s_vec_<datasourceId>`
在版本构建时按数据源的固定维度创建（`vector(N)` + HNSW），不预先建表。
接口层见 `backend/src/text_to_sql/`。

### 1.3 非关系存储（不在本文范围）

| 存储 | 结构 |
|---|---|
| OpenSearch 2.19 | 每个文档库一个索引 `doc_<kbaseId>`；文档是**扁平**的 7 字段 `node_id` / `file_id` / `text` / `source` / `chunk_index` / `chunk_id` / `type`，`_id = node_id`，mapping `dynamic: strict` + `_meta.schema_version=2` |

它们的字段语义见 `docs/TECHNICAL-GUIDE.md` 与 `backend/src/retrieval/repository/es_store.py`。

---

## 2. 逻辑数据模型

**静态子表有 10 个外键约束**（`NOT VALID` 后 `VALIDATE`）：
删除静默留下孤儿行由数据库兜底。动态 `doc_*` / `graph_*` 表不挂外键，
删除链仍由代码显式按序执行（见 `backend/src/knowledge_base/service/kbase_write_service.py`）。

```text
kb_kbase (1 行 = 1 个知识库)
  │  kbase_id (varchar 32, uuid)   ← 业务主键，动态表名的后缀
  │  id (int, identity)            ← 数据库主键，部分旧接口用
  │
  ├─ category = 1 (文档库) ──► 动态表  doc_<kbase_id>_vector (+ _chunk)
  │      │
  │      └─ kb_directory (file) ──► kb_node_relation.directory_id
  │                                   │ node_id
  │                                   ▼
  │                              doc_<id>_vector  (向量行)
  │                              doc_<id>_chunk (切片正文)
  │
  └─ category = 10 (图谱库) ──► 动态表  graph_<kbase_id> (+ _chunk)
         │
         ├─ graph_registry   (kb_id = graph_<uuid>)
         ├─ task_center.task   (kbase_id = 裸 uuid，task_type 区分抽取/导入)
         └─ graph_schema           (schema_id)

operator (1) ──< operator_param (N)
           └──< operator_prop  (N)

flow_workflow (1) ── 1 flow_draft        (草稿，workflow_id 唯一)
                 └─< N flow_release     (发布快照，workflow_id + version 唯一)
```

⚠️ **三个标识、两种形态**（`graph_delete_store.py` 头部专门警告过）：

| 标识 | 形态 | 用在哪 |
|---|---|---|
| 图谱库名 | `graph_<uuid>` | `graph_registry.kb_id` |
| 统一任务行 | 裸 `<uuid>` | `task_center.task.kbase_id`（抽取/导入用 `task_type` 区分） |

导入任务对外返回的 `kb_id` 仍带 `graph_` 前缀，但那只是 store 返回时拼的，不进库。

---

## 3. `rag_studio.public` 逐表

### 3.1 `kb_kbase` —— 知识库主表

| 列 | 类型 | 空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | integer identity | NO | — | 数据库主键（**不是**业务 id） |
| `kbase_id` | varchar(32) | NO | — | **业务主键**：新库 16 位 hex（64 bit），既有库可能为 32 位 hex uuid；动态表名的后缀 |
| `type` | varchar(255) | NO | `'document'` | 子类型标识（当前固定 `document`），代码基本不读 |
| `name` | varchar(255) | NO | — | 展示名；**启用中唯一**（部分唯一索引） |
| `description` | varchar(1000) | YES | — | 描述 |
| `head_icon` | varchar(255) | YES | — | 图标 |
| `es_index_name` | varchar(255) | YES | — | 实际 ES 索引名：文档库 `doc_<uuid>`，图谱库 `graph_<uuid>`（不建 ES 索引） |
| `embedding_model` | varchar(255) | YES | — | 该库使用的 embedding 模型名 |
| `created_by` / `created_at` | varchar(255) / timestamp | — | now | 审计列 |
| `updated_by` / `updated_at` | 同上 | — | now | 审计列 |
| `file_count_limit` | integer | NO | 3000 | 文件数上限（图谱库 50） |
| `org_id` | varchar(512) | YES | — | 组织隔离 |
| `table_name` | varchar(255) | YES | — | **动态表名**：文档库 `doc_<uuid>_vector`，图谱库 `graph_<uuid>` |
| `operator_id` | integer | YES | — | 抽图算子 id（→ `operator.id`，外键 SET NULL） |
| `schema_id` / `schema_obj` | varchar(100) / json | YES | — | 图谱库绑定的 schema（快照） |
| `fail_reason_obj` | json | YES | — | 失败原因 |
| `category` | smallint | NO | 1 | **1 = 文档库 / 10 = 图谱库** |
| `status` | smallint | NO | `0` | 状态码：`0–8` 生命周期、`101–104` / `106` 失败态（CHECK 约束）；前端用 `toNum` 归一 |
| `process` / `process_obj` | varchar(50) / json | YES | — | 处理阶段 |

索引：`kb_kbase_pkey(id)`、`kb_kbase_kbase_id_idx(kbase_id)`、
`kb_kbase_name_uidx(name)`（全表唯一）。

**读法**：按 `category` 分流；动态表名取 `table_name`，
取不到才按 `doc_<id>_vector` 回退（`store/chunk_store.py:vector_table_name`）。

### 3.2 `kb_directory` —— 目录 / 文件树

| 列 | 类型 | 空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | varchar(32) | NO | — | 目录/文件 id（文件 id 即 `fileId`） |
| `kbase_id` | varchar(32) | NO | — | 所属知识库（软关联 `kb_kbase.kbase_id`） |
| `title` | varchar(255) | YES | — | 名称 |
| `parent_id` | varchar(32) | YES | — | 父目录（自引用；根目录为 `Default` 目录 id） |
| `parent_path` | varchar(500) | YES | — | 物化路径（递归 CTE 的替代） |
| `can_spread` | boolean | NO | `false` | 是否可展开 |
| `type` | varchar(32) | NO | — | **`folder` / `file`** |
| `created_by` / `created_at` / `updated_by` / `updated_at` | — | — | now | 审计列 |
| `status` | smallint | YES | — | **文件上传/解析状态**：`-4..2`（CHECK）；`folder` 为 NULL |
| `fail_reason` | varchar(1024) | YES | — | 失败码（如 `RetCode.file.save.error`） |
| `file_from` | varchar(10) | YES | — | 文件来源 |

索引：`kb_directory_pkey(id)`、`directory_kbase_id_index(kbase_id)`、
`uk_kbase_parent_folder_title(kbase_id,parent_id,title) WHERE type='folder'`。

### 3.3 `kb_directory_property` —— 文件/目录键值属性

| 列 | 类型 | 空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | varchar(32) | NO | — | 主键 |
| `file_id` | varchar(32) | NO | — | 指向 `kb_directory.id` |
| `kbase_id` | varchar(32) | NO | — | 冗余的库 id（便于按库查） |
| `prop_name` / `prop_value` | varchar(255) / varchar(1024) | YES | — | 属性键值 |
| 4 个审计列 | — | — | — | 同其它表 |

索引：主键 + `(file_id)` + `(kbase_id)` + `(kbase_id,file_id)`。

### 3.4 `kb_node_relation` —— 文件 → 向量行（`chunkId` 的来源）

| 列 | 类型 | 空 | 说明 |
|---|---|---|---|
| `id` | bigint identity | NO | **业务 `chunkId`**（前端/接口里的 `chunkId` 就是它，不是向量表 id） |
| `kbase_id` | varchar(32) | NO | 知识库 |
| `directory_id` | varchar(32) | NO | 文件 id（`kb_directory.id`） |
| `node_id` | varchar | NO | 向量表 `node_id` |

索引：`kb_node_relation_pkey(id)`、`kb_node_relation_directory_id_idx(directory_id)`。

关系表是**物理删**（与 `kb_directory` 的物理删一致）。
文件 → 切片的完整链路：`kb_directory(id) → kb_node_relation(directory_id) →
.node_id → kb_index.<向量表>.node_id`。

### 3.5 `task_center.task` —— 统一异步任务表

三类任务共用一张表，`task_type` 区分：`FILE_IMPORT` / `GRAPH_EXTRACT` / `GRAPH_IMPORT`。

| 列 | 类型 | 空 | 说明 |
|---|---|---|---|
| `id` | varchar(100) | NO | taskId |
| `task_type` | varchar(32) | NO | 任务类型（CHECK） |
| `lane` | varchar(32) | NO | 执行车道：`file_import` / `graph_extract` / `graph_import` |
| `status` | varchar(32) | NO | 统一状态：`PENDING` / `RUNNING` / `RETRY` / `COMPLETED` / `COMPLETED_WITH_ERRORS` / `FAILED` / `CANCELLED`（CHECK） |
| `priority` | integer | NO | 认领优先级（-1000–1000，越大越先）；默认 0 |
| `progress` | integer | NO | 0–100 |
| `attempt` / `max_attempts` | integer | NO | 当前尝试次数 / 总执行次数 |
| `kbase_id` | varchar(100) | YES | **裸** kbase id |
| `payload` | jsonb | YES | **类型私有输入**（见下表） |
| `extra` | jsonb | YES | **类型私有产出/状态**（见下表） |
| `error_message` | text | YES | 失败原因 |
| `available_at` | timestamptz | NO | 最早可认领时间（延迟重投/退避） |
| `cancel_requested` | boolean | NO | 是否已请求取消（默认 false；取消排队任务时置 true） |
| `cancel_requested_at` | timestamptz | YES | 取消请求时间 |
| `locked_by` / `locked_until` / `heartbeat_at` | — | YES | DB 队列的认领者 / 租约到期 / 最后心跳 |
| `created_at` / `updated_at` / `start_time` / `finish_time` | timestamptz | — | 时间线（`created_at`/`updated_at` 固定在物理列最后两位） |

私有属性不摊成列，按任务类型放 JSONB：

| `task_type` | `payload` | `extra` |
|---|---|---|
| `FILE_IMPORT` | `fileId` / `fileHandle`（完整任务输入，可重建） | `fileName` / `fileSize` / `format` / `embeddingModel` / `splitOperatorId`、`chunkCount` / `vectorCount` / `indexDocCount`、`stageTimingsMs` |
| `GRAPH_EXTRACT` | `tmpDir` / `dto` / `schemaObj` / `isUpdate` / `cacheSchemaId` / `schemaId` / `operatorId` / `fileCount` | `fileCount` / `operatorId` / `schemaId` / `llm` / `importTaskId`、实体与边的 `*_total/success/failed`、`vector_*`、`failedRecordCount`；失败时 `failedStage` |
| `GRAPH_IMPORT` | `kbIndexName` / `schemaId` / `schemaObj` / `zipPath` | `entity_total/success/failed`、`edge_*`、`failed_records`、`vector_entities/edges/chunks/chunk_rows/skipped/collisions`、`index_error` |

`extra` 同时承担**结果摘要**：`FILE_IMPORT` 在成功落停时由引擎合并 runner 通过
`TaskContext.set_result` 收集的计数（失败/重试不写，避免回滚后的半成品被误读）；
`GRAPH_EXTRACT` / `GRAPH_IMPORT` 由领域 runner 在写终态时合并。`vector_*` 是
`graph_index_store.build_index` 的实际产出；索引失败不判死导入，任务落
`COMPLETED_WITH_ERRORS` 并把原因写进 `index_error`。

索引：主键 + `(task_type, status)` + `(status)` + `(kbase_id)` + `(created_at)`；
私有属性需要等值查询时用表达式索引：`((payload->>'fileId'))`、
`((payload->>'schemaId'))`。
认领与清理两条热点路径另有两个部分索引：
`idx_task_claim(lane, status, available_at, priority DESC, created_at)
WHERE status IN ('PENDING','RETRY')` 和
`idx_task_terminal_finish(finish_time) WHERE status IN (终态)`。
更新由 `task_set_updated_at` 触发器刷新 `updated_at`。

**DB 队列**：提交后 `pg_notify('task_center_task', '<lane>')` 唤醒各实例；
每个进程同时 `LISTEN task_center_cancel` 接收 RUNNING 取消标记。
worker 用 `FOR UPDATE SKIP LOCKED` 认领
`lane + PENDING/RETRY + available_at <= now()` 的行，置 `RUNNING` +
`locked_by/locked_until`；长任务由心跳续租，过期 `RUNNING` 由回收线程放回
`PENDING`（`attempt` 自增）或按 `max_attempts` 判 `FAILED`。5s 短轮询只作
NOTIFY 丢失时的兜底。索引 `idx_task_claim` 与
`idx_task_lease(status, locked_until)` 支撑这两条路径。

**管理面**：`PENDING/RETRY` 可立即取消（置 `CANCELLED` + `cancel_requested`）；
`RUNNING` 取消只置 `cancel_requested=true` 并 `pg_notify('task_center_cancel',
'<taskId>')`，worker 在安全点确认后落 `CANCELLED`（心跳时查 `cancel_requested`
兜底）。`FAILED/CANCELLED` 可重试（重置 `attempt=1`、清空锁与终态时间后回
`PENDING`），排队中任务可改 `priority`。取消/重试/改优先级都会刷新 `updated_at`。

**尝试历史**：`task_center.task_attempt` 每次进入 `RUNNING` 记一行，字段为
`task_id / attempt / worker_id / status / error_message / started_at / finished_at`；
`status` 取 `RUNNING` / `COMPLETED` / `COMPLETED_WITH_ERRORS` / `FAILED` /
`CANCELLED` / `LOST`（租约过期被回收）。由 `task.status` 的 UPDATE 触发器
自动写入，覆盖引擎与领域两种终态写者；任务删除时外键级联删除。任务详情
`GET /tasks/{id}` 的 `attempts` 数组返回这段历史。

> 旧的 `public.kb_import_task` / `public.graph_extract_task` / `public.graph_import_task`
> 兼容视图已退役（`20-drop-task-compat-views.sql`）：运行期代码只走 `task_center.task`，
> 视图没有 `INSTEAD OF` 触发器、写入本来就报错，留着只会让每次改表都要跟着重写。
> 领域状态（`INIT/RUNNING/SUCCESS/FAIL`、`PENDING/PROCESSING/...`）的映射在
> `graph/repository/*_store.py` 里完成，不再由视图承担。

任务完成时**先移出内存表、再写库**（`task/queue.py`），所以库里的终态行是唯一可回落的来源。

### 3.6 算子三表

**`operator`**

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | integer identity | 主键 |
| `name` / `name_en` | varchar(255) | 中英文名 |
| `description` / `description_en` | varchar(1000) | 中英文描述 |
| `module` | varchar(255) | 模块（如 `core.rag`） |
| `visible_range` | varchar(255) | `public` / `private`（私有按 `created_by` 过滤） |
| `version` | varchar(255) | 版本 |
| `is_published` | boolean | 是否发布；检索接口强制 `is_published` |
| `operator_zip_path` / `operator_path` | varchar(512) | 算子包/目录 |
| `system` | boolean | 是否系统内置 |
| `org_id` | varchar(512) | 组织 |
| 审计列 | — | — |

**`operator_param`**：`id`、`operator_id`、`arg_name`、`arg_type`、`description`、
`default_value`、`tips`、`placeholder`、审计列。
索引 `(operator_id)`。

**`operator_prop`**：`id`、`operator_id`、`prop_name`、`prop_value`、审计列。
索引 `(operator_id)`。

### 3.7 图谱四表

**`graph_schema`** —— 图谱 schema（本体）

| 列 | 类型 | 说明 |
|---|---|---|
| `schema_id` | varchar(100) | 主键 |
| `schema_name` / `schema_desc` | varchar(100/1000) | 名称/描述 |
| `schema_obj` | json | 本体定义（实体/边类型） |
| `created_at` / `updated_at` | varchar(1000) | **字符串时间**（不是 timestamp） |
| `create_user` / `modify_user` / `tenant_id` | varchar | 审计 |
| `status` | smallint | 状态 |

**`graph_registry`** —— 图谱库登记（表上有注释）

| 列 | 类型 | 说明 |
|---|---|---|
| `kb_id` | varchar(1000) | **`graph_<uuid>`**（图谱库名） |
| `schema_id` | varchar(100) | 指向 `graph_schema` |
| `graph_name` / `graph_desc` | varchar(100/1000) | 名称/描述 |
| `created_at` / `updated_at` | timestamptz | 审计时间 |

主键 `(kb_id, schema_id)`。

**抽图 / 导入任务** —— 数据在 `task_center.task`，没有独立表

`task_type='GRAPH_EXTRACT'`：`kbase_id` 存裸 uuid；`payload` 放 `schemaId` /
`operatorId` / `fileCount`，`extra` 放 `resultFilePath`。领域状态
`INIT/RUNNING/SUCCESS/FAIL` 与统一状态的映射在 `graph_extract_store`。

`task_type='GRAPH_IMPORT'`：`kbase_id` 存裸 uuid（对外返回时再拼 `graph_`）；
`payload` 放 `schemaId` 与 zip 路径，`extra` 放实体/边六个计数与
`failed_records`。领域状态
`PENDING/PROCESSING/COMPLETED/COMPLETED_WITH_ERRORS/FAILED` 的映射在
`graph_import_store`。

### 3.8 `agent_api_key` —— Agent 接口 API Key

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | bigserial PK | |
| `name` | varchar(128) NOT NULL | 用途名（如 `dify-prod`） |
| `key_prefix` | varchar(32) NOT NULL | 查表前缀（`ragk_` + 8 位随机） |
| `key_hash` | char(64) NOT NULL | `HMAC-SHA256(RKB_AGENT_KEY_PEPPER, full_key)`；**不存明文** |
| `scopes` | text[] | `kb:list` / `kb:search` / `kb:answer` |
| `kb_ids` | text[] | 空 = 全部启用文档库；非空 = 白名单 |
| `rate_limit_per_min` | integer | 默认 60；0 = 不限制 |
| `enabled` | boolean | 启用/禁用（不是删除；真删除是物理 DELETE） |
| `expires_at` | timestamptz | 过期即 401 |
| `last_used_at` | timestamptz | 最多每 60s 更新一次 |
| `created_at` | timestamptz | |
| `created_by` | varchar(128) | |

唯一索引 `agent_api_key_prefix_uidx (key_prefix)`。DDL 单一来源
`backend/src/agent/schema.py`；空卷由 `deploy/init/pg/00-schema.sql` 建。
表缺失时主服务正常，agent 路径返回 503。

**调用计数 `agent_api_key_usage`** —— 密钥管理页「总调用量 /
最近 7 天请求数」的唯一数据源：

| 列 | 类型 | 说明 |
|---|---|---|
| `key_prefix` | varchar(32) NOT NULL | 指向 `agent_api_key.key_prefix`，`ON DELETE CASCADE` |
| `usage_date` | date NOT NULL | Asia/Shanghai 自然日（CST） |
| `request_count` | bigint NOT NULL DEFAULT 0 | 当天**鉴权通过**的请求数（401/429 不计） |
| `created_at` / `updated_at` | timestamptz | 最后累加时间即 `updated_at` |

主键 `agent_api_key_usage_pkey (key_prefix, usage_date)`；外键
`fk_agent_api_key_usage_agent_api_key`；索引 `idx_agent_api_key_usage_usage_date`。
计数点在 `agent/auth.py::authenticate()`（REST 与 MCP 共用），每次请求一条
`INSERT ... ON CONFLICT DO UPDATE`，写失败不影响鉴权。DDL 单一来源
`backend/src/agent/schema.py` 的 `USAGE_SCHEMA_STATEMENTS`。

### 3.9 `auth_user` / `auth_session` —— 本地账号与会话

**`auth_user`**（本地账号；口令以 scrypt 哈希存储）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | bigserial PK | |
| `username` | varchar(64) NOT NULL | 登录名；`lower(username)` 唯一索引（大小写不敏感） |
| `email` | varchar(255) | 可选；`lower(email)` 部分唯一索引（仅非 NULL） |
| `display_name` | varchar(128) | 界面显示名 |
| `password_hash` | varchar(255) NOT NULL | `scrypt$n$r$p$<b64salt>$<b64dk>`，**不存明文** |
| `role` | varchar(16) | `user` / `admin`；角色由认证层记录，部署侧按实例划分权限边界 |
| `enabled` | boolean | 禁用后登录 403 且撤销全部会话 |
| `must_change_password` | boolean | 首次登录强制改密 |
| `created_at` / `updated_at` | timestamptz | |
| `last_login_at` | timestamptz | 登录成功时更新 |

**`auth_session`**（登录会话）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | bigserial PK | |
| `token_hash` | char(64) NOT NULL | `SHA-256(token)` 十六进制；**不存明文** |
| `user_id` | bigint NOT NULL | 指向 `auth_user.id`（无外键，应用维护） |
| `created_at` / `last_seen_at` | timestamptz | `last_seen_at` 每 5 分钟最多更新一次 |
| `expires_at` | timestamptz | 默认 12h（`RKB_AUTH_SESSION_TTL_SECONDS`） |
| `revoked_at` | timestamptz | 登出/改密/禁用时置位 |
| `ip` / `user_agent` | varchar | 审计用 |

索引：`token_hash` 唯一、`user_id`、`expires_at`。DDL 单一来源
`backend/src/auth/schema.py`；空卷由 `deploy/init/pg/00-schema.sql` 建。
表缺失时登录接口返回 `503 auth_not_initialized`。

### 3.10 `chat_query_trace` —— 查询链路耗时

每次 `POST /query` 一行，**只存指标**，不存问题/答案/证据正文。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | bigserial PK | 内部主键；`trace_id` 可重复，不作唯一键 |
| `trace_id` | varchar(64) | 来自 `X-Request-Id`，可重复 |
| `conversation_id` / `workflow_id` / `org_id` | varchar(128) | 客户端可控，写库前截断/清洗 |
| `is_stream` | boolean | |
| `status` | varchar(24) | `ok` / `error` / `client_disconnect`（CHECK） |
| `error_code` | varchar(128) | problem 机器码 |
| `http_status` / `error_status` | smallint | 实际 wire 状态 / 问题规格状态 |
| `question_len` / `answer_len` | integer | 字符数；流式输出含思考段 |
| `understanding_ms` / `retrieval_ms` / `rerank_ms` / `generate_ms` / `first_token_ms` / `total_ms` | numeric(12,1) | 阶段没执行 = NULL；`generate/first_token` 仅流式 |
| `hit_count` / `source_count` / `kb_count` | integer | 全部清洗后 source_nodes 的统计 |
| `top_score` | numeric(12,4) | 重排后最高分 |
| `created_at` | timestamptz | 完成时刻 |

索引：`(created_at DESC,id DESC)`、`(workflow_id,...)`、`(conversation_id,...)`、
`(org_id,...)`、`trace_id`。DDL 单一来源 `backend/src/chat/schema.py`；空卷由
`deploy/init/pg/00-schema.sql` 建；30 天保留由宿主侧
`tools/ops/prune-query-traces.py` 分批删除。

---

## 4. `rag_studio.kb_index` —— 动态表

### 4.1 命名与创建规则

| 库类型 | 向量/检索表 | 切片表 | 图库本体 |
|---|---|---|---|
| 文档库（category=1） | `doc_<kbase_id>_vector` | `doc_<kbase_id>_chunk` | — |
| 图谱库（category=10） | `graph_<kbase_id>_vector`（导入时懒建） | `graph_<kbase_id>_chunk` | `graph_<kbase_id>_vertex` / `_edge` |

> 图谱库不创建裸 `graph_<kbase_id>`：检索向量在导入时懒建为 `_vector`。

- 表名**不是算出来的**：建库时写进 `kb_kbase.table_name`，读的时候优先取它
  （按主键拼出来的名字在库里根本不存在，实测 `UndefinedTable`）。
- 检索接口的 `bases[].baseList` 传的是**基名** `doc_<kbase_id>`，
  后端按 `kb_kbase.table_name` 解析到物理表 → 所以 `baseList` 与物理表名**不是一回事**。
- 建表/删表/判存唯一入口：`backend/src/infrastructure/db/ddl.py`；
  **DDL 由本项目单方定义**。

### 4.2 文档向量表 DDL（当前 5 张，逐张相同）

```sql
CREATE TABLE IF NOT EXISTS kb_index.doc_<id>_vector (
    id             INT8 GENERATED BY DEFAULT AS IDENTITY,
    "text"         TEXT        NULL,   -- 普通行为 NULL（正文在切片表）；LLM 优化行存生成的问题
    node_id        VARCHAR     NOT NULL,
    embedding      vector(1024) NULL,  -- 维度写死该库模型维度，并建 HNSW
    source         VARCHAR(255) NULL,  -- 源文件名
    content_expand TEXT        NULL,   -- chunkId 指针（切片表主键）
    chunk_id       INT4        NULL,   -- 切片序号（**不是** kb_node_relation.id）
    type           SMALLINT    NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT doc_<id>_vector_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX doc_<id>_vector_node_id_uidx
    ON kb_index.doc_<id>_vector (node_id);
CREATE INDEX doc_<id>_vector_embedding_hnsw
    ON kb_index.doc_<id>_vector USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

> `chunk_index` 不是物理列；`content_expand` **不建 btree 索引**
>（单条索引键上限约 2704 字节，长正文 INSERT 会直接失败）。

### 4.3 切片表 DDL（按库类型分两套）

**文档库**（当前 5 张）：

```sql
CREATE TABLE IF NOT EXISTS kb_index.doc_<id>_chunk (
    id          VARCHAR(100) NOT NULL,
    kb_id       VARCHAR(100) NOT NULL,
    source      VARCHAR(255) NULL,
    text        TEXT NULL,          -- 新库**唯一**正文副本
    chunk_id    INT4 NULL,
    type        SMALLINT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT doc_<id>_chunk_pkey PRIMARY KEY (id)
);
CREATE INDEX doc_<id>_chunk_source_idx ON kb_index.doc_<id>_chunk (source);
```

**图谱库**（当前 4 张，保留导入/导出契约字段）：

```sql
CREATE TABLE IF NOT EXISTS kb_index.graph_<id>_chunk (
    id             VARCHAR(100) NOT NULL,
    kb_id          VARCHAR(100) NOT NULL,
    source         VARCHAR(255) NULL,
    chunk_order    INT4 NULL,
    spilt_type     VARCHAR(50) NULL,   -- 契约拼写
    text           TEXT NULL,
    label          VARCHAR(255) NULL,
    table_name     VARCHAR(255) NULL,
    table_id       VARCHAR(255) NULL,
    chunk_index    VARCHAR(64) NULL,
    content_expand TEXT NULL,
    chunk_id       INT4 NULL,
    type           SMALLINT NULL,
    created_by     VARCHAR(200) NULL,
    updated_by     VARCHAR(200) NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT graph_<id>_chunk_pkey PRIMARY KEY (id)
);
CREATE INDEX graph_<id>_chunk_source_idx ON kb_index.graph_<id>_chunk (source);
```

**正文只存切片表的 `text`**：向量表的 `content_expand` 是 chunkId 指针。读侧统一
`COALESCE(vector.text, chunk.text)`，向量表在前，保证 `llm_opt_*` 行行为不变。

### 4.4 库与动态表命名

`kb_kbase` 的 `category` 决定动态表的前缀；`table_name` 是动态表基名，把库 ID
作为后缀：

| 库类型 | category | 动态表 |
|---|---:|---|
| 文档库 | 1 | `doc_<id>_vector`（切片向量）/ `doc_<id>_chunk`（切片正文） |
| 图谱库 | 10 | `graph_<id>_vertex` / `graph_<id>_edge` / `graph_<id>_chunk` |

> 图谱库建库时只建 `graph_<id>_chunk`（+ `_vertex`/`_edge`）；向量表
> `graph_<id>_vector` 在导入时懒建。裸 `graph_<id>` 不新建。
> 实际在册的库以 `kb_kbase` / `kb_storage_registry` 为准，不在文档中维护固定清单。

### 4.5 图谱检索索引表 `graph_<uuid>_vector`

除 §4.2 的文档式向量表外，每个图谱库还有一张 **`graph_<uuid>_vector`** ——
实体/边/切片的**检索索引**（`key_id` / `key_type` / `labels` / `embedding`），
由 `backend/src/graph/repository/graph_index_store.py` 在图谱导入完成后写入。

```sql
CREATE TABLE kb_index.graph_<uuid>_vector (
    id         INT8 GENERATED BY DEFAULT AS IDENTITY,
    key_id     VARCHAR NOT NULL,
    key_type   VARCHAR(16) NOT NULL,  -- entity / edge / chunk
    "key"      TEXT NULL,             -- 向量化用的原文（排障）
    labels     TEXT[] NULL,           -- 供 `labels && ARRAY[...]` 过滤
    embedding  vector(1024) NULL,
    edge_id    VARCHAR(255) NULL,     -- 边身份（新行 key_id=edge_id）
    source_id  VARCHAR(255) NULL,     -- 边的起点 entity_id
    target_id  VARCHAR(255) NULL,     -- 边的终点 entity_id
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT graph_<uuid>_vector_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX graph_<uuid>_vector_type_key_uidx
    ON kb_index.graph_<uuid>_vector (key_type, key_id);
CREATE INDEX graph_<uuid>_vector_embedding_hnsw
    ON kb_index.graph_<uuid>_vector USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- 部分索引：WHERE key_type = 'edge'
CREATE INDEX graph_<uuid>_vector_edge_source_idx
    ON kb_index.graph_<uuid>_vector (source_id) WHERE key_type = 'edge';
CREATE INDEX graph_<uuid>_vector_edge_target_idx
    ON kb_index.graph_<uuid>_vector (target_id) WHERE key_type = 'edge';
```

写入链路（`graph_import_engine.build_pg_index`，导入成功后执行）：

| 数据 | 来源 | 写入 |
|---|---|---|
| 实体 | zip 的 `entities.jsonl` | `key_type='entity'`、`key_id=entity_id`、`key`=类型+属性文本 |
| 边 | zip 的 `edges.jsonl` | `key_type='edge'`、**`key_id=edge_id`**（端点落 `source_id`/`target_id` 列）、`key`=类型+两端+属性 |
| 切片 | zip 的 `document_chunk.jsonl` | ① `graph_<uuid>_chunk` 一行；② `key_type='chunk'`、`key_id=<chunk id>`、`key`=切片正文 |

- 向量化用该库 `kb_kbase.embedding_model`（**必须与检索时一致**），整批
  `model_gateway.embed_many`，每批 64 条；
- 重导入按 `(key_type,key_id)` upsert；切片按 `source` 覆盖；
- **边身份**：`key_id = edge_id`，平行边各占一行；检索/删除端读 `source_id` /
  `target_id` 列，不拆 `key_id`；
- **删文件时**同源的切片行与对应的 chunk 向量一起删（`delete_chunks_by_sources`），
  不留指向已删切片的 `key_id`；
- 索引失败**不判死导入**（图数据仍可用），但任务标 `COMPLETED_WITH_ERRORS`
  并写明 `index build failed: ...`，不再静默。

> 缺索引时的症状（实测）：`_build_retrieve_sql` 查
> `kb_index.graph_<uuid>_vector` 得到 `relation does not exist`，`_query_vector_index`
> 吞成 `[]`，接口 `code: 0` + 空结果。根因是导入链没有写实体/边/切片向量。

### 4.6 图谱实体/边表（PostgreSQL）

每个图谱库在 `kb_index` 下另有 `graph_<uuid>_vertex` / `graph_<uuid>_edge`：

```sql
graph_<uuid>_vertex (id BIGSERIAL pk, entity_id unique, entity_type, properties jsonb, ...)
graph_<uuid>_edge   (id BIGSERIAL pk, edge_id unique, edge_type, source_id, target_id,
                     properties jsonb, ...)
```

响应侧保留图行形状（`@rid`/`@class`/`out`/`in`），所以查询/导出/路径提取的
实现不变。图谱存储只有 PostgreSQL 一套，没有独立图数据库或回滚后端。

---

## 5. `rag_studio.public` 的编排 / 注册表 / 存储表

### 5.1 `flow_workflow` —— 工作流元数据

表注释：*检索编排工作流元数据（RKB 侧写入）*

| 列 | 类型 | 空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | bigint serial | NO | — | 主键 |
| `workflow_id` | varchar(128) | NO | — | **业务 id**（如 `RAG_Workflow_ec08`），唯一 |
| `name` | varchar(255) | NO | — | 名称 |
| `description` | text | YES | — | 描述 |
| `template` | varchar(64) | YES | — | 模板标识（顺序/混合/条件） |
| `knowledge_type` | varchar(32) | YES | — | 知识类型 |
| `publish_type` | smallint | NO | 0 | 发布类型 |
| `status` | smallint | NO | 1 | 状态 |
| `bound_info` | jsonb | YES | — | 绑定的知识库快照（`running` / `dev` 两组） |
| 4 个审计列 | — | — | now | — |

### 5.2 `flow_draft` —— 画布草稿

表注释：*检索编排画布草稿，JSON 原样存；`version` 为最后一次发布的版本号*

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | bigint serial | 主键 |
| `workflow_id` | varchar(128) unique | 工作流 |
| `version` | integer default 1 | 最后一次发布版本 |
| `flow_type` | varchar(32) default `'workflow'` | 画布类型 |
| `node_config` | jsonb NOT NULL | 节点配置（**画布的两份 variables 副本之一**） |
| `other_node_config` | jsonb NOT NULL | 边/全局配置 |
| 审计列 | — | — |

### 5.3 `flow_release` —— 发布快照

表注释：*检索编排发布快照，编排运行时只读这里；行不可变（只 INSERT）*

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | bigint serial | 主键 |
| `workflow_id` | varchar(128) | 工作流 |
| `version` | integer | 版本号（与 workflow_id 组合唯一） |
| `node_config` / `other_node_config` | jsonb | 发布时的画布快照 |
| 审计列 | — | — |

索引：`(workflow_id, version)` 唯一 + `(workflow_id, version DESC)`。
运行时（`POST /query`）**只读这张表**；改草稿不影响已发布版本。

### 5.4 `model_registry` —— 模型注册表

由 `backend/src/model/repository_pg.py` 在首次使用时 `CREATE TABLE IF NOT EXISTS` 并播种
（来源仅 `.env`，不从 `kb_embedding` 播种）。**保存即生效**，
``.env` 降为播种 + 回落。

| 列 | 类型 | 说明 |
|---|---|---|
| `model_id` | varchar(64) | 主键 |
| `model_kind` | varchar(16) | `llm` / `embedding` / `rerank`（与 `model_name` 组合唯一） |
| `model_name` | varchar(255) | 模型名 |
| `display_name` | varchar(255) | 展示名 |
| `api_model` | varchar(255) | 实际发给端点的 model 字段 |
| `base_url` | varchar(1000) | 端点根 |
| `api_key` | varchar(2000) | 密钥（**敏感**）：落库为 `enc:v1:<AES-GCM>`，读侧透明解密；见 `docs/security-hardening.md` |
| `chat_path` / `embeddings_path` / `models_path` / `rerank_path` | varchar(255) | 各操作路径（空则用默认） |
| `dimension` | integer | 维度（embedding） |
| `max_tokens` / `temperature` / `timeout` | — | 生成参数 |
| `is_reasoning` | boolean | 是否推理模型 |
| `thinking_mode` | varchar(16) | `none` / `auto` / `preset` / `custom`；仅 LLM 有意义。默认 none，表单新建默认 auto |
| `thinking_preset` | varchar(64) | preset 模式下的目录 ID |
| `thinking_payload` | jsonb | preset/custom 模式下实际合并进请求体的顶层片段快照；白名单键见 `thinking_presets.py` |
| `is_default` | boolean | 默认模型 |
| `enabled` | boolean | 启用 |
| `source` | varchar(16) | `env` / `user` |
| `remark` / `creator` | — | — |
| `created_at` / `updated_at` | timestamp | — |

### 5.5 `kb_storage_registry` —— 存储生命周期

记录每个启用知识库的
`vector_table / chunk_table / graph_vector_table / embedding_dim` 与
`state ∈ {creating, ready, failed, deleting}`。建库/删库流程推进状态，
`storage_registry_store.reconcile()` 负责与 `kb_kbase` / 物理表对账。
详见 `docs/data-deletion-policy.md`。

## 6. 不变的约定与坑

### 6.1 `kbase_id` ≠ `kb_kbase.id`

- `kbase_id`：**业务主键**、动态表后缀、`kb_directory.kbase_id` 的值；
  新库为 **16 位 hex（64 bit）**，既有库可能为 32 位 hex uuid，两种长度都要支持；
- `id`：数据库自增整数，只有少数老接口（按 pk 建表名）用。

用错会**静默拿到空数据**。

### 6.2 三种「库名」形态别混

| 场景 | 值 |
|---|---|
| 动态表 `kb_kbase.table_name` | `doc_<uuid>_vector`（文档）/ `graph_<uuid>`（图谱） |
| 检索 `bases[].baseList` | `doc_<uuid>`（后端按 kb_kbase.table_name 解析物理表） |
| 画布 `knowledge_base_name` | 同上，可带 `\|#\|dev` / `\|#\|publish` 后缀 |
| ES 索引 | `doc_<uuid>` |

### 6.3 删除策略：一律物理删

**全库没有软删除。** 删除即 `DELETE`，不存在 `is_enabled` 列。

| 表 | 删除方式 |
|---|---|
| `kb_kbase` | 物理 `DELETE`；动态表（`doc_*` / `graph_*`）由 `delete_kbase` 显式 `DROP` |
| `kb_directory` | 物理 `DELETE`（目录树由服务层按父子顺序递归删） |
| `kb_directory_property` | 物理 `DELETE`（随所属目录删除，或作为孤儿清理） |
| `task_center.task` / 算子三表 | 物理 `DELETE` |
| `kb_node_relation` | 物理 `DELETE` |
| 动态向量表行 | 物理 `DELETE`（按 `node_id`） |
| 动态切片表行 | 物理 `DELETE`（**按 `source` = 文件名**，删文件时与向量一起清） |

**删除语义**：删除统一走物理 `DELETE`，与「删库即 DROP 动态表」的清理链保持一致；
读路径只面向当前存在的行。完整矩阵与安全约定见
[`data-deletion-policy.md`](data-deletion-policy.md)。

**静态子表有外键兜底**（9 个 FK，全部 `NOT VALID` 后
`VALIDATE` 上线；任务表不挂 FK，删库时由 `graph_delete_store` 显式删任务行）：

| 子表 | 父表 | 删除动作 |
|---|---|---|
| `kb_directory` | `kb_kbase(kbase_id)` | CASCADE |
| `kb_directory.parent_id` | `kb_directory(id)` | CASCADE（自引用） |
| `kb_directory_property.file_id` | `kb_directory(id)` | CASCADE |
| `kb_node_relation.directory_id` | `kb_directory(id)` | CASCADE |
| `kb_node_relation.kbase_id` | `kb_kbase(kbase_id)` | CASCADE |
| `kb_storage_registry.kbase_id` | `kb_kbase(kbase_id)` | CASCADE |
| `kb_kbase.operator_id` | `operator(id)` | SET NULL |
| `operator_param.operator_id` | `operator(id)` | CASCADE |
| `operator_prop.operator_id` | `operator(id)` | CASCADE |

动态表（`doc_*` / `graph_*`）仍由应用显式 `DROP`，不挂 FK；任务行由
`graph_delete_store` 在删库时按 `task_type + kbase_id` 显式删除。

### 6.4 静态表有外键，动态表删除顺序由代码保证

静态子表有 10 个 `FOREIGN KEY`（见 §6.3）；动态 `doc_*` / `graph_*` 表没有外键。删库/删文件的顺序在
`kbase_write_service._purge_files`：relation → 向量表 → 切片表 → 属性 → 磁盘文件。
**动态表的删除链没有数据库兜底**；静态子表已由外键兜底。

### 6.5 `content_expand` 的语义

向量表的 `content_expand` = 切片表的 `id`（chunkId 指针）。正文只存 `chunk.text`；
读侧用 `COALESCE(vector.text, chunk.text)` 兜住 LLM 优化行（它把生成的问题写进
`vector.text`）。

### 6.6 ES 索引名与 `kb_kbase.es_index_name`（`doc_` 前缀）

- 文档库索引 = `doc_<uuid>`，与检索基名（`tableName`）和物理表族
  `doc_<uuid>_vector` / `doc_<uuid>_chunk` 一致；图谱库不建 ES 索引，列值写
  `graph_<uuid>`。**ES 读写只认 `doc_<uuid>`**。
- **基名**（`bases[].baseList` / 画布 `knowledge_base_name`）使用同一套 `doc_<uuid>`。

### 6.7 `embedding` 列带维度并建 HNSW

`ddl.py` 建的是 `embedding vector(N)`，`N` 从 `kb_kbase.embedding_model` →
`model_registry.dimension` 解析（解析不到回落 `EMBEDDING_DIMENSION` / 1024）。
每张表固定一个维度，并建 `USING hnsw (embedding vector_cosine_ops)` 索引；
检索 SQL 用 `ORDER BY embedding <=> q ASC`（可索引形状）。

- 两代维度（768 / 1024）仍可共存于**不同表**；同一张表内不能混维度；
- `graph_<uuid>_vector` 同样带维度 + HNSW。

### 6.9 两个「variables 副本」

画布节点的配置在 `flow_draft.node_config` 里存两份（顶层 `variables` 与
`data.variables`），前端保存时按 `data.variables` 回写顶层。只改一份会导致
「打开画布再保存」静默冲掉绑定。详见 `docs/ARCHITECTURE.md` §7.2。

## 7. 建库

### 7.1 全新环境的建表来源

| 对象 | 谁创建 |
|---|---|
| `rag_studio` database | PostgreSQL 官方镜像按 `POSTGRES_DB` 自动创建（pgdata 为空时） |
| **核心业务表**（`kb_kbase` / `kb_directory` / `operator*` / 图谱四表等） | `deploy/init/pg/00-schema.sql`：默认 `docker-compose.yml` 挂到 `/docker-entrypoint-initdb.d/`，**只在空 PGDATA 上执行** |
| `kb_index` / `task_center` schema | `00-schema.sql` 内 `CREATE SCHEMA IF NOT EXISTS`；应用侧 `ddl.ensure_schema()` 兜底 `kb_index` |
| `task_center.task` 与三个兼容视图 | `deploy/init/pg/10-unify-task-tables.sql`（空卷时在 00 之后自动执行；已有部署手工执行） |
| 任务管理列/索引（`priority`、`cancel_requested*`、`CANCELLED` 状态） | `deploy/init/pg/16-task-management.sql`（幂等，已有部署手工执行） |
| 任务尝试历史 `task_center.task_attempt` 与触发器 | `deploy/init/pg/17-task-attempt-history.sql`（幂等，已有部署手工执行） |
| **Text2SQL 结构**（`text2sql` 18 表 + `text2sql_index` schema + 触发器/发布/归档函数） | `deploy/init/pg/18-text2sql.sql`（首次发布整体建库；结构变更时 DROP SCHEMA 后重跑，不做原地升级） |
| Text2SQL 数据源扩展列（`query_examples` / `llm_model`） | `deploy/init/pg/29-text2sql-query-examples.sql`、`deploy/init/pg/30-text2sql-datasource-llm.sql`（幂等，已有部署可直接执行） |
| `text2sql` / `text2sql_index` 的应用角色授权 | `deploy/init/pg/19-text2sql-grants.sh`（空卷，在 18 之后执行） |
| `task_center.task` 的 `T2S_INDEX` 任务类型 | 已包含在 `deploy/init/pg/10-unify-task-tables.sql` 的 `ck_task_type` |
| 非 superuser 应用角色 `rag_app` 与对象所有权 | `deploy/init/pg/05-app-role.sh`（空卷） |
| 动态向量/切片表 | `knowledge_base/repository/ddl.py`，建库时按需创建（新表带 `UNIQUE(node_id)`） |
| `model_registry` | `model/repository_pg.py` 的 `_ensure_schema`（`CREATE TABLE IF NOT EXISTS`，每进程一次） |
| `flow_*` 三表 | `workflow/repository_pg.py` 的 `FLOW_SCHEMA_STATEMENTS` + `_ensure_schema`（每进程一次） |
| `graph_schema` 等图谱四表 | 已包含在 `00-schema.sql` 的静态快照内 |

> 空卷 `docker compose up -d` 即可建库、上传、检索。

## 8. 常用诊断 SQL

```sql
-- 在册知识库与它们的动态表
SELECT kbase_id, name, category, table_name
FROM kb_kbase ORDER BY category, name;

-- 某个库的「文件 → 切片」链路
SELECT d.id AS file_id, d.title, count(r.id) AS nodes
FROM kb_directory d
LEFT JOIN kb_node_relation r ON r.directory_id = d.id
WHERE d.kbase_id = '<kbaseId>' AND d.type = 'file'
GROUP BY d.id, d.title ORDER BY nodes DESC;

-- 动态表的行数与大小
SELECT c.relname, c.reltuples::bigint AS est_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS size
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'kb_index' AND c.relkind = 'r' ORDER BY 1;

-- 任务积压（统一任务表）
SELECT task_type, status, count(*) FROM task_center.task GROUP BY 1, 2 ORDER BY 1, 2;

-- 画布发布版本
SELECT workflow_id, max(version) AS latest FROM flow_release GROUP BY 1;
```

---

## 9. 相关文档

- `docs/ARCHITECTURE.md` —— 代码结构、依赖规则与修改约定
- `docs/data-deletion-policy.md` —— 删除策略
- `docs/query-trace-persistence.md` —— 查询链路耗时表的使用与保留期
- `docs/TECHNICAL-GUIDE.md` —— 面向使用者的系统说明
