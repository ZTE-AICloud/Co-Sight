-- 统一任务管理面：优先级、取消状态、认领索引。
--
-- 幂等：列/索引用 IF NOT EXISTS，约束先 DROP 再 ADD；已有库可重复执行。

BEGIN;

ALTER TABLE task_center.task
    ADD COLUMN IF NOT EXISTS priority integer NOT NULL DEFAULT 0;

ALTER TABLE task_center.task
    ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false;

ALTER TABLE task_center.task
    ADD COLUMN IF NOT EXISTS cancel_requested_at timestamp with time zone;

ALTER TABLE task_center.task DROP CONSTRAINT IF EXISTS ck_task_priority;
ALTER TABLE task_center.task
    ADD CONSTRAINT ck_task_priority CHECK (priority BETWEEN -1000 AND 1000);

ALTER TABLE task_center.task DROP CONSTRAINT IF EXISTS ck_task_status;
ALTER TABLE task_center.task
    ADD CONSTRAINT ck_task_status CHECK (status IN (
        'PENDING', 'RUNNING', 'RETRY', 'COMPLETED',
        'COMPLETED_WITH_ERRORS', 'FAILED', 'CANCELLED'
    ));

-- 认领路径：lane + 可认领状态 + available_at，再按优先级、创建时间排序。
CREATE INDEX IF NOT EXISTS idx_task_claim
    ON task_center.task (lane, status, available_at, priority DESC, created_at)
    WHERE status IN ('PENDING', 'RETRY');

-- 终态归档/保留期清理按 finish_time 扫。
CREATE INDEX IF NOT EXISTS idx_task_terminal_finish
    ON task_center.task (finish_time)
    WHERE status IN ('COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED', 'CANCELLED');

COMMENT ON COLUMN task_center.task.priority IS
    '认领优先级，值越大越先；同优先级按 created_at';
COMMENT ON COLUMN task_center.task.cancel_requested IS
    '已请求取消；PENDING/RETRY 取消时直接置 CANCELLED';
COMMENT ON COLUMN task_center.task.cancel_requested_at IS
    '取消请求时间';

COMMIT;
