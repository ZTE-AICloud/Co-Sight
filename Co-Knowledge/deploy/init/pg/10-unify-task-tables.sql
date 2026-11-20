-- ============================================================================
-- 统一任务表：把三类任务收敛到 task_center.task
--
-- 公共属性平铺成列；类型私有属性放 JSONB：
--   payload = 任务输入（FILE_IMPORT 的 fileId；GRAPH_* 的 schemaId/operatorId/fileCount）
--   extra   = 任务产出/状态（GRAPH_EXTRACT 的 resultFilePath；
--             GRAPH_IMPORT 的实体/边计数与 failed_records）
--
-- 空卷初始化时本脚本在 00-schema.sql 之后执行：把 00 建的三张旧任务表
-- 原样迁移进 task_center.task，再替换成只读兼容视图。
--
-- 已有部署手工执行：
--   psql -U <owner> -d rag_studio -f deploy/init/pg/10-unify-task-tables.sql
-- 如果库里已经有旧版 task_mgmt，会先自动改名；如果已经是 task_center 但仍是
-- 旧列结构，继续执行 11-task-private-jsonb.sql。
-- ============================================================================

BEGIN;

-- 兼容旧名：如果库里已经按 task_mgmt 建过，先改名（视图依赖 OID，自动跟随）。
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.schemata
               WHERE schema_name = 'task_mgmt')
       AND NOT EXISTS (SELECT 1 FROM information_schema.schemata
                       WHERE schema_name = 'task_center') THEN
        EXECUTE 'ALTER SCHEMA task_mgmt RENAME TO task_center';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS task_center;

CREATE TABLE IF NOT EXISTS task_center.task (
    id character varying(100) NOT NULL,
    task_type character varying(32) NOT NULL,
    lane character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    progress integer DEFAULT 0 NOT NULL,
    attempt integer DEFAULT 1 NOT NULL,
    max_attempts integer DEFAULT 1 NOT NULL,
    kbase_id character varying(100),
    payload jsonb,
    extra jsonb,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    start_time timestamp with time zone,
    finish_time timestamp with time zone,
    CONSTRAINT task_pkey PRIMARY KEY (id),
    CONSTRAINT ck_task_type CHECK (
        (task_type)::text = ANY ((ARRAY['FILE_IMPORT'::character varying,
                                        'GRAPH_EXTRACT'::character varying,
                                        'GRAPH_IMPORT'::character varying])::text[])),
    CONSTRAINT ck_task_status CHECK (
        (status)::text = ANY ((ARRAY['PENDING'::character varying,
                                     'RUNNING'::character varying,
                                     'RETRY'::character varying,
                                     'COMPLETED'::character varying,
                                     'COMPLETED_WITH_ERRORS'::character varying,
                                     'FAILED'::character varying])::text[])),
    CONSTRAINT ck_task_payload_object CHECK (
        payload IS NULL OR jsonb_typeof(payload) = 'object'),
    CONSTRAINT ck_task_extra_object CHECK (
        extra IS NULL OR jsonb_typeof(extra) = 'object')
);

COMMENT ON TABLE task_center.task IS '统一异步任务表（文件导入 / 图谱抽取 / 图谱导入）';
COMMENT ON COLUMN task_center.task.task_type IS 'FILE_IMPORT / GRAPH_EXTRACT / GRAPH_IMPORT';
COMMENT ON COLUMN task_center.task.lane IS '执行车道：file_import / graph_extract / graph_import';
COMMENT ON COLUMN task_center.task.status IS '统一状态：PENDING / RUNNING / RETRY / COMPLETED / COMPLETED_WITH_ERRORS / FAILED';
COMMENT ON COLUMN task_center.task.kbase_id IS '裸 kbase_id（图谱导入的 graph_ 前缀由兼容视图补回）';
COMMENT ON COLUMN task_center.task.payload IS '类型私有输入：fileId / schemaId / operatorId / fileCount';
COMMENT ON COLUMN task_center.task.extra IS '类型私有产出：resultFilePath / 实体边计数 / failed_records';

CREATE INDEX IF NOT EXISTS idx_task_type_status ON task_center.task USING btree (task_type, status);
CREATE INDEX IF NOT EXISTS idx_task_status ON task_center.task USING btree (status);
CREATE INDEX IF NOT EXISTS idx_task_kbase_id ON task_center.task USING btree (kbase_id);
CREATE INDEX IF NOT EXISTS idx_task_created_at ON task_center.task USING btree (created_at);

-- 私有属性的等值查询用表达式索引，不把列再摊回表结构。
DROP INDEX IF EXISTS task_center.idx_task_file_id;
CREATE INDEX IF NOT EXISTS idx_task_file_id
    ON task_center.task ((payload ->> 'fileId'))
    WHERE task_type = 'FILE_IMPORT';
CREATE INDEX IF NOT EXISTS idx_task_schema_id
    ON task_center.task ((payload ->> 'schemaId'))
    WHERE task_type IN ('GRAPH_EXTRACT', 'GRAPH_IMPORT');

DROP TRIGGER IF EXISTS task_set_updated_at ON task_center.task;
CREATE TRIGGER task_set_updated_at
    BEFORE UPDATE ON task_center.task
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 数据迁移：只有旧对象还是 BASE TABLE 时才搬；已经是视图时跳过。
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'kb_import_task'
                 AND table_type = 'BASE TABLE') THEN
        INSERT INTO task_center.task (id, task_type, lane, status, progress, attempt,
                                      max_attempts, kbase_id, payload,
                                      created_at, updated_at, finish_time)
        SELECT t.id,
               'FILE_IMPORT',
               'file_import',
               CASE t.status
                   WHEN 'RUNNING' THEN 'RUNNING'
                   WHEN 'RETRY' THEN 'RETRY'
                   WHEN 'COMPLETED' THEN 'COMPLETED'
                   WHEN 'FAILED' THEN 'FAILED'
                   ELSE 'PENDING'
               END,
               0,
               1,
               4,
               d.kbase_id,
               jsonb_strip_nulls(jsonb_build_object('fileId', t.related_identifier_id)),
               t.created_at,
               t.updated_at,
               CASE WHEN t.status IN ('COMPLETED', 'FAILED') THEN t.updated_at ELSE NULL END
        FROM public.kb_import_task t
        LEFT JOIN public.kb_directory d ON d.id = t.related_identifier_id
        ON CONFLICT (id) DO NOTHING;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'graph_extract_task'
                 AND table_type = 'BASE TABLE') THEN
        INSERT INTO task_center.task (id, task_type, lane, status, progress, attempt,
                                      max_attempts, kbase_id, payload, extra,
                                      error_message, created_at,
                                      updated_at, start_time, finish_time)
        SELECT id,
               'GRAPH_EXTRACT',
               'graph_extract',
               CASE status
                   WHEN 'RUNNING' THEN 'RUNNING'
                   WHEN 'SUCCESS' THEN 'COMPLETED'
                   WHEN 'FAIL' THEN 'FAILED'
                   ELSE 'PENDING'
               END,
               COALESCE(progress, 0),
               1,
               1,
               kb_id,
               jsonb_strip_nulls(jsonb_build_object(
                   'schemaId', schema_id,
                   'operatorId', operator_id,
                   'fileCount', file_count)),
               jsonb_strip_nulls(jsonb_build_object(
                   'resultFilePath', result_file_path)),
               error_message,
               created_at,
               updated_at,
               start_time,
               finish_time
        FROM public.graph_extract_task
        ON CONFLICT (id) DO NOTHING;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'graph_import_task'
                 AND table_type = 'BASE TABLE') THEN
        INSERT INTO task_center.task (id, task_type, lane, status, progress, attempt,
                                      max_attempts, kbase_id, payload, extra,
                                      error_message, created_at, updated_at, finish_time)
        SELECT task_id,
               'GRAPH_IMPORT',
               'graph_import',
               CASE status
                   WHEN 'PROCESSING' THEN 'RUNNING'
                   WHEN 'COMPLETED' THEN 'COMPLETED'
                   WHEN 'COMPLETED_WITH_ERRORS' THEN 'COMPLETED_WITH_ERRORS'
                   WHEN 'FAILED' THEN 'FAILED'
                   ELSE 'PENDING'
               END,
               COALESCE(progress, 0),
               1,
               1,
               CASE
                   WHEN kb_id LIKE 'graph\_%' ESCAPE '\' THEN substr(kb_id, 7)
                   ELSE kb_id
               END,
               jsonb_build_object('schemaId', schema_id),
               jsonb_build_object(
                   'entity_total', COALESCE(entity_total, 0),
                   'entity_success', COALESCE(entity_success, 0),
                   'entity_failed', COALESCE(entity_failed, 0),
                   'edge_total', COALESCE(edge_total, 0),
                   'edge_success', COALESCE(edge_success, 0),
                   'edge_failed', COALESCE(edge_failed, 0),
                   'failed_records', failed_records
               ),
               error_message,
               created_at,
               updated_at,
               CASE WHEN status IN ('COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED')
                    THEN updated_at ELSE NULL END
        FROM public.graph_import_task
        ON CONFLICT (id) DO NOTHING;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 旧表 → 只读兼容视图（从 JSONB 还原字段形状）
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'kb_import_task'
                 AND table_type = 'BASE TABLE') THEN
        EXECUTE 'DROP TABLE public.kb_import_task';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'graph_extract_task'
                 AND table_type = 'BASE TABLE') THEN
        EXECUTE 'DROP TABLE public.graph_extract_task';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'graph_import_task'
                 AND table_type = 'BASE TABLE') THEN
        EXECUTE 'DROP TABLE public.graph_import_task';
    END IF;
END $$;

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

COMMENT ON VIEW public.kb_import_task IS '兼容视图：FILE_IMPORT 任务（只读，写入走 task_center.task）';
COMMENT ON VIEW public.graph_extract_task IS '兼容视图：GRAPH_EXTRACT 任务（只读，写入走 task_center.task）';
COMMENT ON VIEW public.graph_import_task IS '兼容视图：GRAPH_IMPORT 任务（只读，写入走 task_center.task）';

-- 已有部署手工执行本脚本时，05-app-role.sh 不会重跑；这里按 kb_kbase 的属主
-- 找到应用角色并补授权（空卷初始化时 05 已经做过，这里是幂等的兜底）。
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
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA task_center '
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
            current_user, app_role);
    END IF;
END $$;

COMMIT;
