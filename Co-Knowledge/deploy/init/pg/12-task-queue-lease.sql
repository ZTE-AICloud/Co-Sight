-- ============================================================================
-- 统一任务表：持久化队列字段（DB 认领 + 租约）
--
-- 目标：worker 不再只依赖进程内 queue.Queue，而是从 task_center.task 认领：
--   PENDING/RETRY + available_at <= now()  →  claim  →  RUNNING + locked_until
--   长任务通过 heartbeat 续租；worker 崩溃后由 reclaim 把过期 RUNNING 放回队列。
--
-- 这是持久化队列的底座；payload 仍由各领域适配器写入可重建的任务输入。
-- ============================================================================

BEGIN;

ALTER TABLE task_center.task
    ADD COLUMN IF NOT EXISTS available_at timestamp with time zone
        DEFAULT now() NOT NULL;
ALTER TABLE task_center.task
    ADD COLUMN IF NOT EXISTS locked_by character varying(100);
ALTER TABLE task_center.task
    ADD COLUMN IF NOT EXISTS locked_until timestamp with time zone;
ALTER TABLE task_center.task
    ADD COLUMN IF NOT EXISTS heartbeat_at timestamp with time zone;

COMMENT ON COLUMN task_center.task.available_at IS '最早可被认领时间（延迟重投/退避）';
COMMENT ON COLUMN task_center.task.locked_by IS '当前认领者标识（实例 + 车道 + worker）';
COMMENT ON COLUMN task_center.task.locked_until IS '租约到期时间；过期后任务可被回收';
COMMENT ON COLUMN task_center.task.heartbeat_at IS '最后一次续租时间';

-- 存量行：available_at 由 DEFAULT 补齐；这里只兜底 NULL。
UPDATE task_center.task SET available_at = now() WHERE available_at IS NULL;

-- 认领扫描：按 lane + 状态 + 可执行时间排序。
CREATE INDEX IF NOT EXISTS idx_task_claim
    ON task_center.task (lane, status, available_at, created_at)
    WHERE status IN ('PENDING', 'RETRY');

-- 过期租约回收。
CREATE INDEX IF NOT EXISTS idx_task_lease
    ON task_center.task (status, locked_until)
    WHERE status = 'RUNNING';

COMMIT;
