-- 建库补丁：schema.prisma 表达不了的手写结构，由 prisma db push 建完 schema 后执行（见 server/scripts/db.mjs）。
-- 只放结构，不放数据订正。

-- 并发写模式：WAL 下读写互不阻塞。journal_mode 持久在库文件头，建库时设置一次即可。
PRAGMA journal_mode=WAL;

-- 活跃顶层 run 的并发边界（子 run 以 parent_run_id 非空区分，均不参与索引）：
-- 1) 任何 stage：同一 session 至多一个活跃顶层 run；
-- 2) 非 runtime stage：同一 instance 至多一个活跃顶层 run。
-- runtime 例外：同一 instance 的不同 session 可各起一个活跃顶层 run，按会话隔离；session 级约束仍然生效。
-- development / preview / evaluation 仍按 instance 互斥：development 与 runtime 共用 agentRoot/development/ 这棵树
-- （runtime 原地运行），两个 run 同时写就是文件冲突。
-- 索引不解决文件冲突；由上层约定按会话 / 运行分目录或文件名规避，后端不加锁。
-- Prisma schema 表达不了部分索引（见 server/docs/03-architecture/02-data-model.md §6）。
-- 旧索引 uq_runs_one_active_per_instance 约束所有 run（引入子 run 后不再适用）；
-- uq_runs_one_active_top_per_instance 被下面的 session 级 + 非 runtime 实例级双索引取代，先删后建。
DROP INDEX IF EXISTS "uq_runs_one_active_per_instance";
DROP INDEX IF EXISTS "uq_runs_one_active_top_per_instance";
CREATE UNIQUE INDEX IF NOT EXISTS "uq_runs_one_active_top_per_session"
  ON "runs"("session_id") WHERE "status" IN ('pending', 'running') AND "parent_run_id" IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS "uq_runs_one_active_top_per_instance_non_runtime"
  ON "runs"("instance_id") WHERE "status" IN ('pending', 'running') AND "parent_run_id" IS NULL AND "stage" <> 'runtime';

-- 目录实例：同一目录按「用途」区分实例，(cwd, stage) 唯一
-- （技能工坊 = development、自由对话 = runtime；NULL cwd 的智能体实例不受约束）。
-- 旧索引只约束 cwd，会把「同一目录的两种用途」顶成一条实例。
DROP INDEX IF EXISTS "uq_instances_cwd";
CREATE UNIQUE INDEX IF NOT EXISTS "uq_instances_cwd_stage"
  ON "instances"("cwd", "stage") WHERE "cwd" IS NOT NULL;
