-- ============================================================================
-- 统一任务表：把 created_at / updated_at 调整为最后两列
--
-- PostgreSQL 不支持直接改列顺序；这里用「新增 + 回填 + 删旧 + 改名」把两列
-- 移到末尾，保留原值、默认值和 NOT NULL。脚本幂等：已经是最后两列时不做变更。
-- ============================================================================

BEGIN;

DROP VIEW IF EXISTS public.kb_import_task;
DROP VIEW IF EXISTS public.graph_extract_task;
DROP VIEW IF EXISTS public.graph_import_task;

DO $$
DECLARE
    max_other integer;
    min_ts integer;
BEGIN
    SELECT max(ordinal_position) INTO max_other
    FROM information_schema.columns
    WHERE table_schema = 'task_center' AND table_name = 'task'
      AND column_name NOT IN ('created_at', 'updated_at');

    SELECT min(ordinal_position) INTO min_ts
    FROM information_schema.columns
    WHERE table_schema = 'task_center' AND table_name = 'task'
      AND column_name IN ('created_at', 'updated_at');

    IF min_ts IS NOT NULL AND max_other IS NOT NULL AND min_ts < max_other THEN
        EXECUTE 'ALTER TABLE task_center.task ADD COLUMN created_at_new timestamp with time zone';
        EXECUTE 'ALTER TABLE task_center.task ADD COLUMN updated_at_new timestamp with time zone';
        EXECUTE 'UPDATE task_center.task SET created_at_new = created_at, updated_at_new = updated_at';
        EXECUTE 'ALTER TABLE task_center.task ALTER COLUMN created_at_new SET DEFAULT now()';
        EXECUTE 'ALTER TABLE task_center.task ALTER COLUMN created_at_new SET NOT NULL';
        EXECUTE 'ALTER TABLE task_center.task ALTER COLUMN updated_at_new SET DEFAULT now()';
        EXECUTE 'ALTER TABLE task_center.task ALTER COLUMN updated_at_new SET NOT NULL';
        EXECUTE 'ALTER TABLE task_center.task DROP COLUMN created_at';
        EXECUTE 'ALTER TABLE task_center.task DROP COLUMN updated_at';
        EXECUTE 'ALTER TABLE task_center.task RENAME COLUMN created_at_new TO created_at';
        EXECUTE 'ALTER TABLE task_center.task RENAME COLUMN updated_at_new TO updated_at';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_task_created_at
    ON task_center.task USING btree (created_at);

CREATE OR REPLACE VIEW public.kb_import_task AS
SELECT id,
       task_type::character varying(255) AS task_type,
       (payload ->> 'fileId')::character(32) AS related_identifier_id,
       NULL::character varying(255) AS created_by,
       NULL::character varying(255) AS updated_by,
       status::character varying(255) AS status,
       created_at,
       updated_at
FROM task_center.task
WHERE task_type = 'FILE_IMPORT';

CREATE OR REPLACE VIEW public.graph_extract_task AS
SELECT id,
       kbase_id AS kb_id,
       payload ->> 'schemaId' AS schema_id,
       (payload ->> 'operatorId')::integer AS operator_id,
       (payload ->> 'fileCount')::integer AS file_count,
       CASE status
           WHEN 'PENDING' THEN 'INIT'
           WHEN 'RUNNING' THEN 'RUNNING'
           WHEN 'COMPLETED' THEN 'SUCCESS'
           ELSE 'FAIL'
       END::character varying(20) AS status,
       progress,
       error_message,
       extra ->> 'resultFilePath' AS result_file_path,
       NULL::character varying(255) AS created_by,
       created_at,
       updated_at,
       start_time,
       finish_time
FROM task_center.task
WHERE task_type = 'GRAPH_EXTRACT';

CREATE OR REPLACE VIEW public.graph_import_task AS
SELECT id AS task_id,
       CASE WHEN kbase_id IS NULL THEN NULL
            ELSE ('graph_' || kbase_id)::character varying(1000)
       END AS kb_id,
       payload ->> 'schemaId' AS schema_id,
       CASE status
           WHEN 'PENDING' THEN 'PENDING'
           WHEN 'RUNNING' THEN 'PROCESSING'
           WHEN 'COMPLETED' THEN 'COMPLETED'
           WHEN 'COMPLETED_WITH_ERRORS' THEN 'COMPLETED_WITH_ERRORS'
           ELSE 'FAILED'
       END::character varying(50) AS status,
       progress,
       COALESCE((extra ->> 'entity_total')::integer, 0) AS entity_total,
       COALESCE((extra ->> 'entity_success')::integer, 0) AS entity_success,
       COALESCE((extra ->> 'entity_failed')::integer, 0) AS entity_failed,
       COALESCE((extra ->> 'edge_total')::integer, 0) AS edge_total,
       COALESCE((extra ->> 'edge_success')::integer, 0) AS edge_success,
       COALESCE((extra ->> 'edge_failed')::integer, 0) AS edge_failed,
       extra -> 'failed_records' AS failed_records,
       error_message::character varying(20000) AS error_message,
       created_at,
       updated_at
FROM task_center.task
WHERE task_type = 'GRAPH_IMPORT';

-- 重建视图后补应用角色 SELECT。
DO $$
DECLARE
    app_role name;
BEGIN
    SELECT tableowner INTO app_role
    FROM pg_tables
    WHERE schemaname = 'public' AND tablename = 'kb_kbase';

    IF app_role IS NOT NULL AND app_role <> current_user THEN
        EXECUTE format(
            'GRANT SELECT ON public.kb_import_task, public.graph_extract_task, '
            'public.graph_import_task TO %I', app_role);
    END IF;
END $$;

COMMIT;
