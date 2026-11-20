-- ============================================================================
-- 统一任务表：把类型私有属性从列迁到 JSONB
--
-- 适用场景：已经执行过旧版 10-unify-task-tables.sql，task_center.task 里还有
-- file_id / schema_id / operator_id / file_count / result_file_path 五列。
--
-- 执行后：
--   payload = 类型私有输入（fileId / schemaId / operatorId / fileCount）
--   extra   = 类型私有产出（resultFilePath / 图谱导入计数 / failed_records）
--
-- 脚本幂等：列已经不存在时只重建视图和索引。
-- ============================================================================

BEGIN;

-- 1. 回填 JSONB（只有旧五列都还在时才执行）
DO $$
DECLARE
    private_columns integer;
BEGIN
    SELECT count(*) INTO private_columns
    FROM information_schema.columns
    WHERE table_schema = 'task_center' AND table_name = 'task'
      AND column_name IN ('file_id', 'schema_id', 'operator_id',
                          'file_count', 'result_file_path');

    IF private_columns = 5 THEN
        EXECUTE $sql$
            UPDATE task_center.task
            SET payload = COALESCE(payload, '{}'::jsonb)
                || jsonb_strip_nulls(jsonb_build_object(
                       'fileId', file_id,
                       'schemaId', schema_id,
                       'operatorId', operator_id,
                       'fileCount', file_count))
            WHERE file_id IS NOT NULL OR schema_id IS NOT NULL
               OR operator_id IS NOT NULL OR file_count IS NOT NULL
        $sql$;
        EXECUTE $sql$
            UPDATE task_center.task
            SET extra = COALESCE(extra, '{}'::jsonb)
                || jsonb_build_object('resultFilePath', result_file_path)
            WHERE result_file_path IS NOT NULL
        $sql$;
    END IF;
END $$;

-- 2. 先删视图，避免 DROP COLUMN 被依赖挡住
DROP VIEW IF EXISTS public.kb_import_task;
DROP VIEW IF EXISTS public.graph_extract_task;
DROP VIEW IF EXISTS public.graph_import_task;

-- 3. 补 JSONB 对象约束（旧版 10 没有这两条）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'ck_task_payload_object') THEN
        ALTER TABLE task_center.task ADD CONSTRAINT ck_task_payload_object
            CHECK (payload IS NULL OR jsonb_typeof(payload) = 'object');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'ck_task_extra_object') THEN
        ALTER TABLE task_center.task ADD CONSTRAINT ck_task_extra_object
            CHECK (extra IS NULL OR jsonb_typeof(extra) = 'object');
    END IF;
END $$;

-- 4. 删掉私有列（IF EXISTS 保证幂等）
ALTER TABLE task_center.task DROP COLUMN IF EXISTS file_id;
ALTER TABLE task_center.task DROP COLUMN IF EXISTS schema_id;
ALTER TABLE task_center.task DROP COLUMN IF EXISTS operator_id;
ALTER TABLE task_center.task DROP COLUMN IF EXISTS file_count;
ALTER TABLE task_center.task DROP COLUMN IF EXISTS result_file_path;

-- 5. 重建兼容视图（字段从 JSONB 还原）
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

-- 6. 用表达式索引替代原来的 file_id 列索引
DROP INDEX IF EXISTS task_center.idx_task_file_id;
CREATE INDEX IF NOT EXISTS idx_task_file_id
    ON task_center.task ((payload ->> 'fileId'))
    WHERE task_type = 'FILE_IMPORT';
CREATE INDEX IF NOT EXISTS idx_task_schema_id
    ON task_center.task ((payload ->> 'schemaId'))
    WHERE task_type IN ('GRAPH_EXTRACT', 'GRAPH_IMPORT');

-- 7. 应用角色授权（重建视图后需要重新 GRANT）
DO $$
DECLARE
    app_role name;
BEGIN
    SELECT tableowner INTO app_role
    FROM pg_tables
    WHERE schemaname = 'public' AND tablename = 'kb_kbase';

    IF app_role IS NOT NULL AND app_role <> current_user THEN
        EXECUTE format('GRANT USAGE, CREATE ON SCHEMA task_center TO %I', app_role);
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON task_center.task TO %I', app_role);
        EXECUTE format(
            'GRANT SELECT ON public.kb_import_task, public.graph_extract_task, '
            'public.graph_import_task TO %I', app_role);
    END IF;
END $$;

COMMIT;
