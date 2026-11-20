-- ============================================================================
-- 统一任务表：清理没有持久化 payload 的历史任务
--
-- 旧版本的任务行只存 fileId / schemaId / operatorId，没有 DB 队列重跑所需的
-- fileHandle / tmpDir / zipPath。切换 DB 队列后这些行不能被安全恢复，统一判
-- FAILED 并写明原因，避免 worker 认领后立刻报“入参为空”。
--
-- 只影响非终态行；新任务都带完整 payload，不会被误伤。
-- ============================================================================

BEGIN;

UPDATE task_center.task
SET status = 'FAILED',
    error_message = 'Legacy task has no durable payload; cannot be resumed',
    finish_time = now(),
    locked_by = NULL,
    locked_until = NULL,
    heartbeat_at = NULL,
    updated_at = now()
WHERE status IN ('PENDING', 'RUNNING', 'RETRY')
  AND (
        (task_type = 'FILE_IMPORT' AND payload ->> 'fileHandle' IS NULL)
     OR (task_type = 'GRAPH_EXTRACT' AND payload ->> 'tmpDir' IS NULL)
     OR (task_type = 'GRAPH_IMPORT' AND payload ->> 'zipPath' IS NULL)
  );

COMMIT;
