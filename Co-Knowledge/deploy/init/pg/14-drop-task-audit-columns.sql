-- ============================================================================
-- 统一任务表：删除冗余的 created_by / updated_by
--
-- 任务归属已经由 kbase_id / payload / 创建时间表达；这两个审计列没有消费方。
-- 兼容视图仍保留同名字段（返回 NULL），避免旧 DTO/查询因缺列报错。
-- ============================================================================

BEGIN;

DROP VIEW IF EXISTS public.kb_import_task;
DROP VIEW IF EXISTS public.graph_extract_task;
DROP VIEW IF EXISTS public.graph_import_task;

ALTER TABLE task_center.task DROP COLUMN IF EXISTS created_by;
ALTER TABLE task_center.task DROP COLUMN IF EXISTS updated_by;

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
