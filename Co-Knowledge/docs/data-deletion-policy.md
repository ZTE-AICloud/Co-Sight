# 删除策略（一律物理删除）

> 适用范围：`rag_studio` 库内全部业务表。

## 1. 删除语义

删除在本项目中是一次**物理 `DELETE`**：对象及其派生数据在同一套删除链里被清理，
读路径只看到当前存在的数据。具体语义：

- **即时生效**：删除请求成功后，列表、详情与检索都不再返回该对象。
- **级联清理**：删除知识库会同时清理动态向量/切片表、OpenSearch 索引与磁盘目录；
  删除目录会先删子节点、属性、关系与文件。矩阵见 §2。
- **不可恢复**：没有回收站与撤销入口，删除前需要按 §3 备份或确认。
- **单一语义**：全库统一使用物理删除，不引入 `is_enabled` / `deleted_at` 之类的
  逻辑删除列，避免同一对象在不同读路径上出现「存在但不可见」的分歧。
- **业务停用**：需要「停用但保留」的语义时，使用业务状态列（例如
  `model_registry.enabled`），它与删除是两件事。

## 2. 现行删除矩阵

| 对象 | 删除动作 | 连带清理 |
|---|---|---|
| 知识库 `kb_kbase` | `DELETE FROM kb_kbase WHERE kbase_id = %s` | 服务层先 `DROP TABLE` 动态表：`doc_<id>_vector` / `doc_<id>_chunk`（文档库）或 `graph_<id>_*`（图谱库）；`kb_storage_registry` / `graph_registry` / ES 索引 / 磁盘目录 |
| 目录 / 文件 `kb_directory` | `DELETE FROM kb_directory WHERE id = ANY(%s)` | 先删子节点（递归），再删属性、关系、向量行、切片行、磁盘文件 |
| 目录属性 `kb_directory_property` | 随目录 `DELETE` | 另有孤儿清理（`file_id` 不存在） |
| 导入任务 `kb_import_task` | `DELETE` | 无 |
| 算子 `operator` | `DELETE FROM operator` + `operator_param` / `operator_prop` | 同事务内先删参数/属性 |
| 节点关系 `kb_node_relation` | `DELETE` | 无 |
| 动态向量行 | `DELETE ... WHERE node_id = ANY(...)` | 无 |
| 动态切片行 | `DELETE ... WHERE source = ANY(文件名)` | 与向量同批 |
| 查询轨迹 `chat_query_trace` | 按保留期 `DELETE`（运维脚本） | 无 |

**静态子表有外键兜底**（10 个 FK，`NOT VALID` 后 `VALIDATE` 上线）：

- `kb_directory.kbase_id` → `kb_kbase(kbase_id)` CASCADE；
- `kb_directory.parent_id` → 自身 `id` CASCADE；
- `kb_directory_property.file_id` / `kb_node_relation.directory_id` → `kb_directory(id)` CASCADE；
- `kb_node_relation.kbase_id` / `kb_storage_registry.kbase_id` / `graph_extract_task.kb_id`
  → `kb_kbase(kbase_id)` CASCADE；
- `kb_kbase.operator_id` → `operator(id)` SET NULL；
- `operator_param.operator_id` / `operator_prop.operator_id` → `operator(id)` CASCADE。

动态表（`doc_*` / `graph_*`）仍由应用显式 `DROP`，不挂 FK；删除顺序仍由
`kbase_write_service._purge_files` 与各仓储保证。改删除链时必须同步改这里。

## 3. 安全约定

1. **破坏性运维先备份**：`pg_dump -Fc` 到仓库外的备份目录；
2. 破坏性运维操作必须先 `--dry-run` 确认；
3. 删知识库前确认 `kb_storage_registry` 中的物理表名，避免删错库；
4. 生产库不手工 `DELETE`；走 API（服务层会清动态表/ES/磁盘）。

## 4. 结构基线

| 事项 | 位置 |
|---|---|
| 表结构与运维查询 | `docs/database-schema.md` |
| 空卷初始化 | `deploy/init/pg/00-schema.sql` |
| 删除策略 | 本文 |

## 5. 代码侧约定

新增代码遵循同一套删除语义：

- 删除走物理 `DELETE`，并同步清理该对象的派生数据（动态表、索引、磁盘文件）；
- 查询只针对当前存在的行，不需要额外的「是否已删」过滤条件；
- 需要「停用但保留」的语义时用**业务状态列**（例如 `model_registry.enabled`），
  并在文档中说明它与删除的区别。
