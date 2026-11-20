-- 任务尝试历史：每次 RUNNING 一条，终态/租约丢失时关闭。
--
-- 用触发器记录，而不是让引擎写：图谱两条车道的终态由领域 `_run` 写入，
-- 触发器能同时覆盖引擎与领域两种写者。已有历史任务不补造尝试行。

BEGIN;

CREATE TABLE IF NOT EXISTS task_center.task_attempt (
    id bigserial PRIMARY KEY,
    task_id varchar(100) NOT NULL
        REFERENCES task_center.task(id) ON DELETE CASCADE,
    attempt integer NOT NULL,
    worker_id varchar(200),
    status varchar(32) NOT NULL CHECK (status IN (
        'RUNNING', 'COMPLETED', 'COMPLETED_WITH_ERRORS',
        'FAILED', 'CANCELLED', 'LOST'
    )),
    error_message text,
    started_at timestamp with time zone NOT NULL DEFAULT now(),
    finished_at timestamp with time zone
);

CREATE INDEX IF NOT EXISTS idx_task_attempt_task
    ON task_center.task_attempt (task_id, attempt, id);

COMMENT ON TABLE task_center.task_attempt IS
    '任务每次执行的尝试历史；task 删除时级联删除';
COMMENT ON COLUMN task_center.task_attempt.status IS
    'RUNNING=执行中；LOST=租约过期被回收；其余为终态';

CREATE OR REPLACE FUNCTION task_center.track_task_attempt()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'RUNNING' AND OLD.status IS DISTINCT FROM 'RUNNING' THEN
        INSERT INTO task_center.task_attempt
            (task_id, attempt, worker_id, status, started_at)
        VALUES (NEW.id, NEW.attempt, NEW.locked_by, 'RUNNING',
                COALESCE(NEW.start_time, now()));
    ELSIF OLD.status = 'RUNNING' AND NEW.status <> 'RUNNING' THEN
        UPDATE task_center.task_attempt
        SET finished_at = now(),
            status = CASE
                WHEN NEW.status = 'PENDING' THEN 'LOST'
                WHEN NEW.status = 'RETRY' THEN
                    CASE WHEN NEW.error_message IS NOT NULL THEN 'FAILED'
                         ELSE 'LOST' END
                ELSE NEW.status
            END,
            error_message = CASE
                WHEN NEW.status IN ('RETRY', 'PENDING')
                    THEN COALESCE(NEW.error_message, 'Worker lease expired')
                ELSE NEW.error_message
            END
        WHERE task_id = NEW.id
          AND attempt = OLD.attempt
          AND finished_at IS NULL;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS task_track_attempt ON task_center.task;
CREATE TRIGGER task_track_attempt
    AFTER UPDATE OF status ON task_center.task
    FOR EACH ROW EXECUTE FUNCTION task_center.track_task_attempt();

-- 触发器以调用者（rag_app）权限执行，需要显式授权新表与序列。
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON task_center.task_attempt TO rag_app;
        GRANT USAGE, SELECT ON SEQUENCE task_center.task_attempt_id_seq TO rag_app;
    END IF;
END $$;

COMMIT;
