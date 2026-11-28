-- Text2SQL / Schema RAG，首次发布的完整结构。PostgreSQL 14+。
--
-- 本文件是 text2sql 领域唯一的建库入口：`text2sql`（目录、版本化知识、查询工作台）
-- 与 `text2sql_index`（按数据源分表的向量索引）都在这里一次建好。
-- 特性尚未对外发布，不存在旧版本升级路径；重建数据时直接 DROP SCHEMA 再执行本文件。
--
-- 故意不加 IF NOT EXISTS：schema 已存在说明库里还有旧结构，应当先显式清理，
-- 而不是让 CREATE TABLE 悄悄失败一半。
BEGIN;

-- 向量检索依赖 pgvector；已由 00-schema.sql 创建，这里兜底保证本文件自足。
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA text2sql;
COMMENT ON SCHEMA text2sql IS 'Text2SQL configuration, semantic catalog, versioned RAG and query workspace';

CREATE SCHEMA text2sql_index;
COMMENT ON SCHEMA text2sql_index IS 'Text2SQL 按数据源分表的向量索引（表在版本构建时创建）';

CREATE FUNCTION text2sql.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = clock_timestamp(); RETURN NEW; END;
$$;

CREATE TABLE text2sql.t2s_datasource (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL CHECK (btrim(name) <> ''),
    db_type VARCHAR(32) NOT NULL DEFAULT 'postgresql'
        CHECK (db_type IN ('postgresql','mysql','oracle','sqlserver','clickhouse')),
    host VARCHAR(255) NOT NULL CHECK (btrim(host) <> ''),
    port INTEGER NOT NULL DEFAULT 5432 CHECK (port BETWEEN 1 AND 65535),
    database_name VARCHAR(128) NOT NULL CHECK (btrim(database_name) <> ''),
    username VARCHAR(128) NOT NULL CHECK (btrim(username) <> ''),
    credential_ref TEXT NOT NULL CHECK (btrim(credential_ref) <> ''),
    include_schemas TEXT[] NOT NULL DEFAULT ARRAY['public']
        CHECK (cardinality(include_schemas) > 0 AND array_position(include_schemas, NULL) IS NULL
            AND array_position(include_schemas, '') IS NULL),
    connection_options JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(connection_options) = 'object'),
    business_description TEXT NOT NULL DEFAULT '',
    topic_name VARCHAR(60),
    topic_description TEXT NOT NULL DEFAULT '',
    maintainer_ref TEXT, -- platform user/team ID, display name resolved by backend
    business_timezone TEXT NOT NULL DEFAULT 'UTC', -- backend validates against pg_timezone_names
    embedding_model VARCHAR(255), -- pinned at the first version build; fixes the vector dimension
    query_policy JSONB NOT NULL DEFAULT '{"read_only":true,"max_rows":1000,"timeout_ms":30000}'
        CHECK (jsonb_typeof(query_policy) = 'object'),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config_revision BIGINT NOT NULL DEFAULT 1 CHECK (config_revision > 0),
    active_version_id UUID, -- set only after a complete, version-isolated index is ready
    connection_tested_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (deleted_at IS NULL OR (NOT enabled AND active_version_id IS NULL))
);
CREATE UNIQUE INDEX uq_t2s_datasource_live_name ON text2sql.t2s_datasource(lower(name)) WHERE deleted_at IS NULL;
COMMENT ON COLUMN text2sql.t2s_datasource.credential_ref IS 'Secret service reference; never a plaintext password';
COMMENT ON COLUMN text2sql.t2s_datasource.embedding_model IS 'Data source level embedding model; pinned when the first version is built, and every vector table of this source uses its dimension';
COMMENT ON COLUMN text2sql.t2s_datasource.config_revision IS 'Backend increments once per committed semantic/scope/connection change under datasource row lock; rename alone need not increment';
COMMENT ON COLUMN text2sql.t2s_datasource.query_policy IS 'Policy configuration only; backend and read-only database account must enforce it';

CREATE TABLE text2sql.t2s_table (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL REFERENCES text2sql.t2s_datasource(id),
    schema_name VARCHAR(128) NOT NULL CHECK (btrim(schema_name) <> ''),
    table_name VARCHAR(128) NOT NULL CHECK (btrim(table_name) <> ''),
    table_type VARCHAR(32) NOT NULL DEFAULT 'BASE_TABLE'
        CHECK (table_type IN ('BASE_TABLE','VIEW','MATERIALIZED_VIEW','FOREIGN_TABLE','PARTITIONED_TABLE')),
    db_comment TEXT,
    business_name VARCHAR(255),
    business_description TEXT,
    business_aliases TEXT[] NOT NULL DEFAULT '{}',
    schema_hash VARCHAR(64) CHECK (schema_hash ~ '^[0-9a-f]{64}$'),
    constraints_metadata JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(constraints_metadata) = 'array'),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    missing_since TIMESTAMPTZ, -- source object disappeared; preserve its identity and history
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (datasource_id, schema_name, table_name),
    UNIQUE (id, datasource_id)
);
COMMENT ON COLUMN text2sql.t2s_table.enabled IS 'Explicit query scope selection, not a database permission; new discoveries are opt-in';
COMMENT ON COLUMN text2sql.t2s_table.constraints_metadata IS 'Ordered PK/UNIQUE column groups, e.g. [{"type":"UNIQUE","name":"uq_pair","columns":["a","b"]}]; individual flags do not describe composite uniqueness';

CREATE TABLE text2sql.t2s_column (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL,
    table_id UUID NOT NULL,
    column_name VARCHAR(128) NOT NULL CHECK (btrim(column_name) <> ''),
    data_type VARCHAR(128) NOT NULL,
    ordinal_position INTEGER NOT NULL CHECK (ordinal_position > 0),
    is_nullable BOOLEAN NOT NULL DEFAULT TRUE,
    default_value TEXT,
    is_primary_key BOOLEAN NOT NULL DEFAULT FALSE,
    is_unique BOOLEAN NOT NULL DEFAULT FALSE, -- single-column unique only
    db_comment TEXT,
    business_name VARCHAR(255), business_description TEXT,
    business_aliases TEXT[] NOT NULL DEFAULT '{}',
    semantic_type VARCHAR(32) CHECK (semantic_type IN ('identifier','measure','dimension','time','category')),
    value_cardinality VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN'
        CHECK (value_cardinality IN ('UNKNOWN','LOW','HIGH')), -- LOW is auto-collected during scan
    distinct_value_count INTEGER,
    schema_hash VARCHAR(64) CHECK (schema_hash ~ '^[0-9a-f]{64}$'),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    missing_since TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (table_id, datasource_id) REFERENCES text2sql.t2s_table(id, datasource_id),
    UNIQUE (table_id, column_name), UNIQUE (id, datasource_id), UNIQUE (id, table_id, datasource_id)
);
COMMENT ON COLUMN text2sql.t2s_column.value_cardinality IS 'LOW values are collected at scan time; HIGH (city, product, …) are resolved against the source database at query time';

CREATE TABLE text2sql.t2s_relation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL,
    source_table_id UUID NOT NULL, target_table_id UUID NOT NULL,
    relation_name VARCHAR(255) NOT NULL CHECK (btrim(relation_name) <> ''),
    relation_type VARCHAR(32) NOT NULL CHECK (relation_type IN ('FOREIGN_KEY','MANUAL','INFERRED')),
    cardinality VARCHAR(16) CHECK (cardinality IN ('ONE_TO_ONE','ONE_TO_MANY','MANY_TO_ONE','MANY_TO_MANY')),
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    verified_by TEXT, verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (source_table_id, datasource_id) REFERENCES text2sql.t2s_table(id, datasource_id),
    FOREIGN KEY (target_table_id, datasource_id) REFERENCES text2sql.t2s_table(id, datasource_id),
    UNIQUE (datasource_id, source_table_id, relation_name), -- FK names need not be datasource-wide unique
    UNIQUE (id, datasource_id), UNIQUE (id, source_table_id, target_table_id, datasource_id),
    CHECK ((verified AND verified_at IS NOT NULL AND verified_by IS NOT NULL)
        OR (NOT verified AND verified_at IS NULL AND verified_by IS NULL))
);
COMMENT ON TABLE text2sql.t2s_relation IS 'FK/logical relations, including valid self joins; column pairs live in t2s_relation_column';
CREATE INDEX idx_t2s_relation_target ON text2sql.t2s_relation(target_table_id, datasource_id);

CREATE TABLE text2sql.t2s_relation_column (
    relation_id UUID NOT NULL,
    datasource_id UUID NOT NULL,
    source_table_id UUID NOT NULL, target_table_id UUID NOT NULL,
    ordinal_position INTEGER NOT NULL CHECK (ordinal_position > 0),
    source_column_id UUID NOT NULL, target_column_id UUID NOT NULL,
    PRIMARY KEY (relation_id, ordinal_position),
    FOREIGN KEY (relation_id, source_table_id, target_table_id, datasource_id)
        REFERENCES text2sql.t2s_relation(id, source_table_id, target_table_id, datasource_id),
    FOREIGN KEY (source_column_id, source_table_id, datasource_id)
        REFERENCES text2sql.t2s_column(id, table_id, datasource_id),
    FOREIGN KEY (target_column_id, target_table_id, datasource_id)
        REFERENCES text2sql.t2s_column(id, table_id, datasource_id),
    UNIQUE (relation_id, source_column_id), UNIQUE (relation_id, target_column_id)
);
COMMENT ON TABLE text2sql.t2s_relation_column IS 'Ordered composite-FK pairs with real column membership constraints; replaces V1 column_mapping JSONB';
CREATE INDEX idx_t2s_relation_column_source ON text2sql.t2s_relation_column(source_column_id);
CREATE INDEX idx_t2s_relation_column_target ON text2sql.t2s_relation_column(target_column_id);

CREATE TABLE text2sql.t2s_value (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL, column_id UUID NOT NULL,
    raw_value TEXT NOT NULL, value_type VARCHAR(64) NOT NULL,
    business_name VARCHAR(255), aliases TEXT[] NOT NULL DEFAULT '{}', description TEXT,
    source_type VARCHAR(32) NOT NULL DEFAULT 'DATABASE' CHECK (source_type IN ('DATABASE','MANUAL','ENUM')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (column_id, datasource_id) REFERENCES text2sql.t2s_column(id, datasource_id),
    UNIQUE (column_id, raw_value), UNIQUE (id, datasource_id)
);

CREATE TABLE text2sql.t2s_metric (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL, base_table_id UUID NOT NULL,
    metric_key VARCHAR(128) NOT NULL CHECK (btrim(metric_key) <> ''),
    business_name VARCHAR(255) NOT NULL CHECK (btrim(business_name) <> ''),
    business_description TEXT NOT NULL DEFAULT '', aliases TEXT[] NOT NULL DEFAULT '{}',
    expression_sql TEXT NOT NULL CHECK (btrim(expression_sql) <> ''),
    filter_definition JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(filter_definition) = 'object'),
    time_column_id UUID,
    unit VARCHAR(64), business_timezone TEXT NOT NULL DEFAULT 'UTC',
    aggregation_behavior VARCHAR(32) NOT NULL DEFAULT 'ADDITIVE'
        CHECK (aggregation_behavior IN ('ADDITIVE','SEMI_ADDITIVE','NON_ADDITIVE')),
    attribution_description TEXT NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','APPROVED','DISABLED')),
    verified_by TEXT, verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (base_table_id, datasource_id) REFERENCES text2sql.t2s_table(id, datasource_id),
    FOREIGN KEY (time_column_id, datasource_id) REFERENCES text2sql.t2s_column(id, datasource_id),
    UNIQUE (datasource_id, metric_key), UNIQUE (id, datasource_id),
    CHECK (status <> 'APPROVED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))
);
COMMENT ON COLUMN text2sql.t2s_metric.expression_sql IS 'Dialect-specific definition, e.g. SUM(order_info.pay_amount); backend must parse/validate, never blindly execute';
COMMENT ON COLUMN text2sql.t2s_metric.filter_definition IS 'Backend-defined filter AST, e.g. {"op":"eq","column":"public.order_info.status","value":2}; validate schema and resolve identifiers';
COMMENT ON COLUMN text2sql.t2s_metric.aggregation_behavior IS 'COUNT(DISTINCT user_id) is NON_ADDITIVE: monthly distinct users cannot be summed into total distinct users';
CREATE INDEX idx_t2s_metric_base ON text2sql.t2s_metric(base_table_id, datasource_id);
CREATE INDEX idx_t2s_metric_time ON text2sql.t2s_metric(time_column_id, datasource_id);

CREATE TABLE text2sql.t2s_metric_column (
    metric_id UUID NOT NULL, datasource_id UUID NOT NULL, column_id UUID NOT NULL,
    dependency_role VARCHAR(16) NOT NULL CHECK (dependency_role IN ('MEASURE','FILTER','TIME','DIMENSION','JOIN')),
    PRIMARY KEY (metric_id, column_id, dependency_role),
    FOREIGN KEY (metric_id, datasource_id) REFERENCES text2sql.t2s_metric(id, datasource_id),
    FOREIGN KEY (column_id, datasource_id) REFERENCES text2sql.t2s_column(id, datasource_id)
);
CREATE INDEX idx_t2s_metric_column_reverse ON text2sql.t2s_metric_column(column_id);
CREATE TABLE text2sql.t2s_metric_relation (
    metric_id UUID NOT NULL, datasource_id UUID NOT NULL, relation_id UUID NOT NULL,
    PRIMARY KEY (metric_id, relation_id),
    FOREIGN KEY (metric_id, datasource_id) REFERENCES text2sql.t2s_metric(id, datasource_id),
    FOREIGN KEY (relation_id, datasource_id) REFERENCES text2sql.t2s_relation(id, datasource_id)
);
CREATE INDEX idx_t2s_metric_relation_reverse ON text2sql.t2s_metric_relation(relation_id);

CREATE TABLE text2sql.t2s_config_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL REFERENCES text2sql.t2s_datasource(id),
    revision BIGINT NOT NULL CHECK (revision > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT','BUILDING','READY','FAILED','CANCELLED','ARCHIVED')),
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object' AND snapshot <> '{}'::jsonb),
    content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    expected_knowledge_count INTEGER NOT NULL DEFAULT 0 CHECK (expected_knowledge_count >= 0),
    embedding_model VARCHAR(255) NOT NULL CHECK (btrim(embedding_model) <> ''),
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    created_by TEXT NOT NULL,
    ready_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (datasource_id, revision), UNIQUE (id, datasource_id),
    CHECK ((status IN ('READY','ARCHIVED')) = (ready_at IS NOT NULL))
);
COMMENT ON COLUMN text2sql.t2s_config_version.snapshot IS 'Complete allowlisted config: connection identity (no secrets), selected tables/columns, descriptions, relations/pairs, values, metrics/dependencies, timezone, policy; immutable after DRAFT';
COMMENT ON COLUMN text2sql.t2s_config_version.status IS 'DRAFT->BUILDING->READY, plus FAILED/CANCELLED and the terminal ARCHIVED (storage reclaimed by purge_archived_knowledge)';
ALTER TABLE text2sql.t2s_datasource ADD CONSTRAINT fk_t2s_datasource_active_version
    FOREIGN KEY (active_version_id, id) REFERENCES text2sql.t2s_config_version(id, datasource_id);

CREATE TABLE text2sql.t2s_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL, version_id UUID NOT NULL,
    object_type VARCHAR(16) NOT NULL CHECK (object_type IN ('TABLE','COLUMN','VALUE','RELATION','METRIC','NOTE')),
    object_key TEXT NOT NULL CHECK (btrim(object_key) <> ''),
    table_id UUID, column_id UUID, value_id UUID, relation_id UUID, metric_id UUID,
    title TEXT NOT NULL, content TEXT NOT NULL CHECK (btrim(content) <> ''),
    metadata JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata) = 'object'),
    content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    vector_namespace TEXT NOT NULL CHECK (btrim(vector_namespace) <> ''),
    vector_document_id TEXT CHECK (btrim(vector_document_id) <> ''),
    index_status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (index_status IN ('PENDING','INDEXED','FAILED')),
    index_error TEXT, indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (version_id, datasource_id) REFERENCES text2sql.t2s_config_version(id, datasource_id),
    FOREIGN KEY (table_id, datasource_id) REFERENCES text2sql.t2s_table(id, datasource_id),
    FOREIGN KEY (column_id, datasource_id) REFERENCES text2sql.t2s_column(id, datasource_id),
    FOREIGN KEY (value_id, datasource_id) REFERENCES text2sql.t2s_value(id, datasource_id),
    FOREIGN KEY (relation_id, datasource_id) REFERENCES text2sql.t2s_relation(id, datasource_id),
    FOREIGN KEY (metric_id, datasource_id) REFERENCES text2sql.t2s_metric(id, datasource_id),
    UNIQUE (version_id, object_type, object_key),
    UNIQUE (vector_namespace, vector_document_id),
    CHECK (
        (object_type = 'NOTE' AND num_nonnulls(table_id,column_id,value_id,relation_id,metric_id) = 0)
        OR (num_nonnulls(table_id,column_id,value_id,relation_id,metric_id) = 1 AND (
            (object_type = 'TABLE' AND table_id IS NOT NULL) OR (object_type = 'COLUMN' AND column_id IS NOT NULL)
            OR (object_type = 'VALUE' AND value_id IS NOT NULL) OR (object_type = 'RELATION' AND relation_id IS NOT NULL)
            OR (object_type = 'METRIC' AND metric_id IS NOT NULL)))
    ),
    CHECK ((index_status = 'INDEXED' AND vector_document_id IS NOT NULL AND indexed_at IS NOT NULL AND index_error IS NULL)
        OR (index_status <> 'INDEXED' AND indexed_at IS NULL))
);
COMMENT ON COLUMN text2sql.t2s_knowledge.index_status IS 'Aggregate state across all enabled stores; per-store detail lives in t2s_knowledge_binding';
CREATE INDEX idx_t2s_knowledge_version_status ON text2sql.t2s_knowledge(version_id, index_status);
CREATE INDEX idx_t2s_knowledge_datasource ON text2sql.t2s_knowledge(datasource_id, version_id);
CREATE INDEX idx_t2s_knowledge_table ON text2sql.t2s_knowledge(table_id) WHERE table_id IS NOT NULL;
CREATE INDEX idx_t2s_knowledge_column ON text2sql.t2s_knowledge(column_id) WHERE column_id IS NOT NULL;
CREATE INDEX idx_t2s_knowledge_value ON text2sql.t2s_knowledge(value_id) WHERE value_id IS NOT NULL;
CREATE INDEX idx_t2s_knowledge_relation ON text2sql.t2s_knowledge(relation_id) WHERE relation_id IS NOT NULL;
CREATE INDEX idx_t2s_knowledge_metric ON text2sql.t2s_knowledge(metric_id) WHERE metric_id IS NOT NULL;

-- 每种存储各自记录索引结果；t2s_knowledge.index_status 是它们的汇总态。
CREATE TABLE text2sql.t2s_knowledge_binding (
    knowledge_id UUID NOT NULL,
    datasource_id UUID NOT NULL,
    version_id UUID NOT NULL,
    store_kind VARCHAR(16) NOT NULL CHECK (store_kind IN ('VECTOR','ES')),
    state VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','INDEXED','FAILED')),
    external_id TEXT,
    error TEXT,
    indexed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (knowledge_id, store_kind),
    FOREIGN KEY (knowledge_id) REFERENCES text2sql.t2s_knowledge(id) ON DELETE CASCADE,
    -- INDEXED 必须有外部标识与时间；非 INDEXED 不能留着它们。
    CHECK ((state = 'INDEXED') = (external_id IS NOT NULL AND indexed_at IS NOT NULL))
);
COMMENT ON TABLE text2sql.t2s_knowledge_binding IS 'Per-store index binding for a knowledge object (VECTOR / ES); t2s_knowledge.index_status stays the aggregate';
CREATE INDEX idx_t2s_knowledge_binding_version ON text2sql.t2s_knowledge_binding(version_id, store_kind, state);

CREATE TABLE text2sql.t2s_index_job (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL, version_id UUID NOT NULL,
    job_type VARCHAR(32) NOT NULL CHECK (job_type IN ('SCHEMA_SYNC','KNOWLEDGE_BUILD','EMBEDDING')),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')),
    idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt > 0),
    total_count INTEGER NOT NULL DEFAULT 0, processed_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    worker_id TEXT, heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (version_id, datasource_id) REFERENCES text2sql.t2s_config_version(id, datasource_id),
    UNIQUE (datasource_id, idempotency_key),
    CHECK (total_count >= 0 AND processed_count >= 0 AND failed_count >= 0 AND processed_count + failed_count <= total_count),
    CHECK ((status = 'PENDING' AND started_at IS NULL AND finished_at IS NULL)
        OR (status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('COMPLETED','FAILED','CANCELLED') AND finished_at IS NOT NULL)),
    CHECK (finished_at IS NULL OR finished_at >= coalesce(started_at, created_at)),
    CHECK (status <> 'COMPLETED' OR (started_at IS NOT NULL AND processed_count = total_count AND failed_count = 0)),
    CHECK (status <> 'FAILED' OR nullif(btrim(error_message), '') IS NOT NULL)
);
COMMENT ON COLUMN text2sql.t2s_index_job.processed_count IS 'Successfully processed objects; failed_count is disjoint. Retries create a new attempt/key, rather than counting objects twice';
CREATE UNIQUE INDEX uq_t2s_index_job_inflight ON text2sql.t2s_index_job(version_id, job_type) WHERE status IN ('PENDING','RUNNING');
CREATE INDEX idx_t2s_index_job_source ON text2sql.t2s_index_job(datasource_id, created_at DESC);
CREATE INDEX idx_t2s_index_job_claim ON text2sql.t2s_index_job(status, created_at) WHERE status IN ('PENDING','RUNNING');

CREATE FUNCTION text2sql.guard_index_job() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Job attempts are retained'; END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.id,NEW.datasource_id,NEW.version_id,NEW.job_type,NEW.idempotency_key,NEW.attempt)
            IS DISTINCT FROM (OLD.id,OLD.datasource_id,OLD.version_id,OLD.job_type,OLD.idempotency_key,OLD.attempt) THEN
            RAISE EXCEPTION 'Job identity cannot change';
        END IF;
        IF OLD.status IN ('COMPLETED','FAILED','CANCELLED') THEN RAISE EXCEPTION 'Finished job is immutable; create a new attempt'; END IF;
        IF NEW.status = 'PENDING' AND OLD.status <> 'PENDING' THEN RAISE EXCEPTION 'Running job cannot return to queue'; END IF;
    ELSIF NEW.status <> 'PENDING' THEN RAISE EXCEPTION 'Jobs must start in PENDING';
    END IF;
    SELECT status INTO v_status FROM text2sql.t2s_config_version WHERE id = NEW.version_id FOR UPDATE;
    IF v_status NOT IN ('DRAFT','BUILDING') AND NOT (
        TG_OP = 'UPDATE' AND v_status IN ('FAILED','CANCELLED') AND NEW.status IN ('FAILED','CANCELLED')
    ) THEN RAISE EXCEPTION 'Version is not accepting jobs'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_index_job BEFORE INSERT OR UPDATE OR DELETE ON text2sql.t2s_index_job
    FOR EACH ROW EXECUTE FUNCTION text2sql.guard_index_job();

CREATE TABLE text2sql.t2s_publication (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource_id UUID NOT NULL REFERENCES text2sql.t2s_datasource(id),
    previous_version_id UUID, version_id UUID,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (previous_version_id, datasource_id) REFERENCES text2sql.t2s_config_version(id, datasource_id),
    FOREIGN KEY (version_id, datasource_id) REFERENCES text2sql.t2s_config_version(id, datasource_id),
    CHECK (previous_version_id IS DISTINCT FROM version_id)
);
CREATE INDEX idx_t2s_publication_source ON text2sql.t2s_publication(datasource_id, created_at DESC);

CREATE TABLE text2sql.t2s_query_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    datasource_id UUID NOT NULL REFERENCES text2sql.t2s_datasource(id),
    version_id UUID, parent_run_id UUID,
    actor_id TEXT NOT NULL,
    question TEXT NOT NULL CHECK (btrim(question) <> ''),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    request_parameters JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(request_parameters) = 'object'),
    date_policy VARCHAR(16) NOT NULL DEFAULT 'relative' CHECK (date_policy IN ('relative','fixed','all')),
    resolved_time_range JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(resolved_time_range) = 'object'),
    source_snapshot JSONB NOT NULL CHECK (jsonb_typeof(source_snapshot) = 'object' AND source_snapshot <> '{}'::jsonb),
    generated_sql TEXT, final_sql TEXT,
    retrieval_snapshot JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(retrieval_snapshot) = 'object'),
    context_snapshot JSONB CHECK (context_snapshot IS NULL OR jsonb_typeof(context_snapshot) = 'object'),
    explanation_snapshot JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(explanation_snapshot) = 'object'),
    validation_snapshot JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(validation_snapshot) = 'object'),
    explain_snapshot JSONB CHECK (jsonb_typeof(explain_snapshot) = 'object'),
    result_snapshot JSONB CHECK (jsonb_typeof(result_snapshot) = 'object'),
    result_row_count BIGINT CHECK (result_row_count >= 0),
    result_truncated BOOLEAN NOT NULL DEFAULT FALSE,
    result_expires_at TIMESTAMPTZ, -- backend retention worker scrubs only result payload
    error_code TEXT, error_message TEXT, error_stage TEXT,
    stages JSONB NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(stages) = 'array'),
    timing JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(timing) = 'object'),
    usage JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(usage) = 'object'),
    started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (version_id, datasource_id) REFERENCES text2sql.t2s_config_version(id, datasource_id),
    FOREIGN KEY (parent_run_id, datasource_id) REFERENCES text2sql.t2s_query_run(id, datasource_id),
    UNIQUE (id, datasource_id),
    CHECK (parent_run_id IS NULL OR parent_run_id <> id),
    CHECK ((status = 'PENDING' AND started_at IS NULL AND finished_at IS NULL)
        OR (status = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('SUCCEEDED','FAILED','CANCELLED') AND finished_at IS NOT NULL)),
    CHECK (finished_at IS NULL OR finished_at >= coalesce(started_at, created_at)),
    CHECK (status <> 'SUCCEEDED' OR (version_id IS NOT NULL AND started_at IS NOT NULL
        AND nullif(btrim(final_sql), '') IS NOT NULL AND result_row_count IS NOT NULL AND error_code IS NULL)),
    CHECK (status <> 'FAILED' OR nullif(btrim(error_code), '') IS NOT NULL)
);
COMMENT ON COLUMN text2sql.t2s_query_run.resolved_time_range IS 'Resolved absolute [start,end_exclusive) bounds, timezone, reference date and time column; never recalculate historical dates';
COMMENT ON COLUMN text2sql.t2s_query_run.context_snapshot IS 'The exact prompt context handed to the model: selected tables, rendered text and budget/render timings';
COMMENT ON COLUMN text2sql.t2s_query_run.result_snapshot IS 'Bounded result preview {columns,rows}; NULL after retention or when results are not retained. Never silently rerun a historical query';
CREATE INDEX idx_t2s_query_run_history ON text2sql.t2s_query_run(actor_id, created_at DESC);
CREATE INDEX idx_t2s_query_run_source ON text2sql.t2s_query_run(datasource_id, created_at DESC);
CREATE INDEX idx_t2s_query_run_version ON text2sql.t2s_query_run(version_id);
CREATE INDEX idx_t2s_query_run_parent ON text2sql.t2s_query_run(parent_run_id);

CREATE TABLE text2sql.t2s_favorite (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id TEXT NOT NULL,
    datasource_id UUID REFERENCES text2sql.t2s_datasource(id),
    name VARCHAR(80) NOT NULL CHECK (btrim(name) <> ''),
    question TEXT NOT NULL CHECK (btrim(question) <> ''),
    parameters JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(parameters) = 'object'),
    date_policy VARCHAR(16) NOT NULL DEFAULT 'relative' CHECK (date_policy IN ('relative','fixed','all')),
    fixed_time_range JSONB CHECK (jsonb_typeof(fixed_time_range) = 'object'),
    notes TEXT NOT NULL DEFAULT '',
    verified_version_id UUID, verified_by TEXT, verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (verified_version_id, datasource_id) REFERENCES text2sql.t2s_config_version(id, datasource_id),
    CHECK (num_nonnulls(verified_version_id, verified_by, verified_at) IN (0,3)),
    CHECK (verified_version_id IS NULL OR datasource_id IS NOT NULL),
    CHECK ((date_policy = 'fixed' AND fixed_time_range IS NOT NULL AND fixed_time_range <> '{}'::jsonb)
        OR (date_policy <> 'fixed' AND fixed_time_range IS NULL))
);
CREATE INDEX idx_t2s_favorite_owner ON text2sql.t2s_favorite(actor_id, updated_at DESC);
CREATE INDEX idx_t2s_favorite_source ON text2sql.t2s_favorite(datasource_id);

CREATE TABLE text2sql.t2s_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL, datasource_id UUID NOT NULL,
    actor_id TEXT NOT NULL,
    category VARCHAR(16) NOT NULL CHECK (category IN ('helpful','meaning','sql','data')),
    helpful BOOLEAN, notes TEXT NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','REVIEWING','RESOLVED')),
    resolution TEXT NOT NULL DEFAULT '',
    processed_by TEXT, processed_at TIMESTAMPTZ,
    resolved_version_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, actor_id, category),
    FOREIGN KEY (run_id, datasource_id) REFERENCES text2sql.t2s_query_run(id, datasource_id),
    FOREIGN KEY (resolved_version_id, datasource_id) REFERENCES text2sql.t2s_config_version(id, datasource_id),
    CHECK (status = 'OPEN' OR (btrim(resolution) <> '' AND processed_by IS NOT NULL AND processed_at IS NOT NULL)),
    CHECK ((status = 'RESOLVED') = (resolved_version_id IS NOT NULL)),
    CHECK ((category = 'helpful' AND helpful IS NOT NULL)
        OR (category <> 'helpful' AND helpful IS NULL AND btrim(notes) <> ''))
);
COMMENT ON COLUMN text2sql.t2s_feedback.resolved_version_id IS 'Backend verifies this same-source READY version covers the reported question and has a post-feedback validation; FK alone does not prove resolution';
CREATE TABLE text2sql.t2s_workspace (
    actor_id TEXT PRIMARY KEY,
    datasource_id UUID REFERENCES text2sql.t2s_datasource(id),
    question_draft TEXT NOT NULL DEFAULT '', sql_draft TEXT NOT NULL DEFAULT '',
    preferences JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(preferences) = 'object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE text2sql.t2s_workspace IS 'User draft/UI preferences only; no duplicated catalog, credentials or query result history';

-- Serialize knowledge writes with version finalization. READY/ARCHIVED 版本只允许删除知识。
CREATE FUNCTION text2sql.guard_knowledge_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_id UUID; v_status TEXT;
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.version_id, NEW.datasource_id, NEW.id) IS DISTINCT FROM (OLD.version_id, OLD.datasource_id, OLD.id) THEN
        RAISE EXCEPTION 'Knowledge identity/version cannot change';
    END IF;
    IF TG_OP = 'DELETE' THEN v_id := OLD.version_id; ELSE v_id := NEW.version_id; END IF;
    SELECT status INTO v_status FROM text2sql.t2s_config_version WHERE id = v_id FOR UPDATE;
    IF TG_OP = 'DELETE' THEN
        IF v_status <> 'ARCHIVED' THEN
            RAISE EXCEPTION 'Knowledge version % is not writable', v_id;
        END IF;
        RETURN OLD;
    END IF;
    IF v_status NOT IN ('DRAFT','BUILDING') THEN RAISE EXCEPTION 'Knowledge version % is not writable', v_id; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_knowledge BEFORE INSERT OR UPDATE OR DELETE ON text2sql.t2s_knowledge
    FOR EACH ROW EXECUTE FUNCTION text2sql.guard_knowledge_write();

CREATE FUNCTION text2sql.guard_config_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_count INTEGER;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'DRAFT' THEN RAISE EXCEPTION 'Versions must start in DRAFT'; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'ARCHIVED' THEN
            RAISE EXCEPTION 'Only archived versions can be removed';
        END IF;
        RETURN OLD;
    END IF;
    IF (NEW.id, NEW.datasource_id, NEW.revision) IS DISTINCT FROM (OLD.id, OLD.datasource_id, OLD.revision) THEN
        RAISE EXCEPTION 'Version identity cannot change';
    END IF;
    IF OLD.status IN ('CANCELLED', 'ARCHIVED') THEN
        RAISE EXCEPTION 'Terminal version is immutable';
    END IF;
    -- READY 唯一的合法变更是归档；归档也不许顺手改构建产物。
    IF OLD.status = 'READY' AND NEW.status IS DISTINCT FROM 'ARCHIVED' THEN
        RAISE EXCEPTION 'Terminal version is immutable';
    END IF;
    IF OLD.status <> 'DRAFT' AND
        (NEW.snapshot, NEW.content_hash, NEW.expected_knowledge_count, NEW.embedding_model, NEW.embedding_dimensions, NEW.created_by, NEW.created_at)
        IS DISTINCT FROM
        (OLD.snapshot, OLD.content_hash, OLD.expected_knowledge_count, OLD.embedding_model, OLD.embedding_dimensions, OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'Build inputs are frozen; create a new revision';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'DRAFT' AND NEW.status IN ('BUILDING','CANCELLED'))
        OR (OLD.status = 'BUILDING' AND NEW.status IN ('READY','FAILED','CANCELLED'))
        OR (OLD.status = 'FAILED' AND NEW.status IN ('BUILDING','CANCELLED'))
        OR (OLD.status = 'READY' AND NEW.status = 'ARCHIVED')
    ) THEN RAISE EXCEPTION 'Invalid version transition: % -> %', OLD.status, NEW.status; END IF;
    IF NEW.status = 'READY' THEN
        SELECT count(*) INTO actual_count FROM text2sql.t2s_knowledge WHERE version_id = NEW.id;
        IF NEW.expected_knowledge_count = 0 OR actual_count <> NEW.expected_knowledge_count
            OR EXISTS (SELECT 1 FROM text2sql.t2s_knowledge WHERE version_id = NEW.id AND index_status <> 'INDEXED') THEN
            RAISE EXCEPTION 'All expected knowledge objects must be indexed before READY';
        END IF;
        IF EXISTS (SELECT 1 FROM text2sql.t2s_index_job WHERE version_id = NEW.id AND status IN ('PENDING','RUNNING')) THEN
            RAISE EXCEPTION 'Index jobs are still in progress';
        END IF;
        NEW.ready_at := clock_timestamp();
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_version BEFORE INSERT OR UPDATE OR DELETE ON text2sql.t2s_config_version
    FOR EACH ROW EXECUTE FUNCTION text2sql.guard_config_version();

CREATE FUNCTION text2sql.guard_active_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status TEXT; v_revision BIGINT;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.config_revision < OLD.config_revision THEN RAISE EXCEPTION 'Configuration revision cannot decrease'; END IF;
    IF NEW.active_version_id IS NOT NULL AND (TG_OP = 'INSERT' OR NEW.active_version_id IS DISTINCT FROM OLD.active_version_id) THEN
        SELECT status, revision INTO v_status, v_revision FROM text2sql.t2s_config_version
            WHERE id = NEW.active_version_id AND datasource_id = NEW.id FOR SHARE;
        IF v_status IS DISTINCT FROM 'READY' OR v_revision IS DISTINCT FROM NEW.config_revision OR NEW.deleted_at IS NOT NULL THEN
            RAISE EXCEPTION 'Only a READY version matching current configuration can be activated';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_active_version BEFORE INSERT OR UPDATE ON text2sql.t2s_datasource
    FOR EACH ROW EXECUTE FUNCTION text2sql.guard_active_version();

CREATE FUNCTION text2sql.log_publication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.active_version_id IS DISTINCT FROM OLD.active_version_id THEN
        INSERT INTO text2sql.t2s_publication(datasource_id,previous_version_id,version_id,actor_id)
            VALUES (NEW.id,OLD.active_version_id,NEW.active_version_id,
                coalesce(nullif(current_setting('text2sql.actor_id',true),''),'system'));
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER log_publication AFTER UPDATE OF active_version_id ON text2sql.t2s_datasource
    FOR EACH ROW EXECUTE FUNCTION text2sql.log_publication();

CREATE FUNCTION text2sql.publish_version(p_datasource_id UUID, p_version_id UUID, p_expected_revision BIGINT)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE current_revision BIGINT;
BEGIN
    SELECT config_revision INTO current_revision FROM text2sql.t2s_datasource WHERE id = p_datasource_id FOR UPDATE;
    IF NOT FOUND OR current_revision IS DISTINCT FROM p_expected_revision THEN
        RAISE EXCEPTION 'Datasource missing or configuration changed; refresh before publishing';
    END IF;
    UPDATE text2sql.t2s_datasource SET active_version_id = p_version_id WHERE id = p_datasource_id;
END;
$$;

CREATE FUNCTION text2sql.invalidate_favorite_verification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.datasource_id,NEW.question,NEW.parameters,NEW.date_policy,NEW.fixed_time_range)
        IS DISTINCT FROM (OLD.datasource_id,OLD.question,OLD.parameters,OLD.date_policy,OLD.fixed_time_range) THEN
        NEW.verified_version_id := NULL; NEW.verified_by := NULL; NEW.verified_at := NULL;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER invalidate_favorite BEFORE UPDATE ON text2sql.t2s_favorite
    FOR EACH ROW EXECUTE FUNCTION text2sql.invalidate_favorite_verification();

CREATE FUNCTION text2sql.guard_query_run() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'PENDING' THEN RAISE EXCEPTION 'Queries must start in PENDING'; END IF;
        IF NEW.version_id IS NOT NULL THEN
            SELECT status INTO v_status FROM text2sql.t2s_config_version
                WHERE id = NEW.version_id AND datasource_id = NEW.datasource_id;
            IF v_status IS DISTINCT FROM 'READY' THEN RAISE EXCEPTION 'Queries can only pin a READY version'; END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id,NEW.request_id,NEW.datasource_id,NEW.version_id,NEW.parent_run_id,NEW.actor_id,NEW.question,
        NEW.request_parameters,NEW.date_policy,NEW.resolved_time_range,NEW.source_snapshot,NEW.created_at)
        IS DISTINCT FROM (OLD.id,OLD.request_id,OLD.datasource_id,OLD.version_id,OLD.parent_run_id,OLD.actor_id,OLD.question,
        OLD.request_parameters,OLD.date_policy,OLD.resolved_time_range,OLD.source_snapshot,OLD.created_at) THEN
        RAISE EXCEPTION 'Query inputs and pinned version are immutable';
    END IF;
    IF OLD.status IN ('SUCCEEDED','FAILED','CANCELLED') THEN
        IF (to_jsonb(NEW) - 'updated_at' - 'result_snapshot') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at' - 'result_snapshot')
            OR NEW.result_snapshot IS NOT NULL OR OLD.result_expires_at IS NULL OR OLD.result_expires_at > clock_timestamp() THEN
            RAISE EXCEPTION 'Finished query is immutable except expired result removal';
        END IF;
    ELSIF NEW.status = 'RUNNING' AND NEW.version_id IS NULL THEN RAISE EXCEPTION 'Running query needs a pinned version';
    ELSIF NEW.status = 'PENDING' AND OLD.status <> 'PENDING' THEN RAISE EXCEPTION 'Running query cannot return to queue';
    ELSIF NEW.status = 'SUCCEEDED' AND OLD.status <> 'RUNNING' THEN RAISE EXCEPTION 'Successful query must have been RUNNING';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_query_run BEFORE INSERT OR UPDATE ON text2sql.t2s_query_run
    FOR EACH ROW EXECUTE FUNCTION text2sql.guard_query_run();

CREATE FUNCTION text2sql.invalidate_metric_verification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.base_table_id,NEW.business_name,NEW.business_description,NEW.aliases,NEW.expression_sql,
        NEW.filter_definition,NEW.time_column_id,NEW.unit,NEW.business_timezone,NEW.aggregation_behavior,NEW.attribution_description)
        IS DISTINCT FROM (OLD.base_table_id,OLD.business_name,OLD.business_description,OLD.aliases,OLD.expression_sql,
        OLD.filter_definition,OLD.time_column_id,OLD.unit,OLD.business_timezone,OLD.aggregation_behavior,OLD.attribution_description) THEN
        IF NEW.status = 'APPROVED' THEN NEW.status := 'DRAFT'; END IF;
        NEW.verified_by := NULL; NEW.verified_at := NULL;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER invalidate_metric BEFORE UPDATE ON text2sql.t2s_metric
    FOR EACH ROW EXECUTE FUNCTION text2sql.invalidate_metric_verification();

CREATE FUNCTION text2sql.invalidate_dependency_verification() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_id UUID; new_id UUID;
BEGIN
    IF TG_TABLE_NAME = 't2s_relation_column' THEN
        IF TG_OP <> 'INSERT' THEN old_id := OLD.relation_id; END IF;
        IF TG_OP <> 'DELETE' THEN new_id := NEW.relation_id; END IF;
        UPDATE text2sql.t2s_relation SET verified = FALSE, verified_by = NULL, verified_at = NULL WHERE id IN (old_id,new_id);
    ELSE
        IF TG_OP <> 'INSERT' THEN old_id := OLD.metric_id; END IF;
        IF TG_OP <> 'DELETE' THEN new_id := NEW.metric_id; END IF;
        UPDATE text2sql.t2s_metric SET status = CASE WHEN status = 'APPROVED' THEN 'DRAFT' ELSE status END,
            verified_by = NULL, verified_at = NULL WHERE id IN (old_id,new_id);
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER invalidate_relation_pairs AFTER INSERT OR UPDATE OR DELETE ON text2sql.t2s_relation_column
    FOR EACH ROW EXECUTE FUNCTION text2sql.invalidate_dependency_verification();
CREATE TRIGGER invalidate_metric_columns AFTER INSERT OR UPDATE OR DELETE ON text2sql.t2s_metric_column
    FOR EACH ROW EXECUTE FUNCTION text2sql.invalidate_dependency_verification();
CREATE TRIGGER invalidate_metric_relations AFTER INSERT OR UPDATE OR DELETE ON text2sql.t2s_metric_relation
    FOR EACH ROW EXECUTE FUNCTION text2sql.invalidate_dependency_verification();

-- 归档：把可回收的旧 READY 版本切成 ARCHIVED，再由 purge 清掉知识（向量随外键级联）。
-- 活动版本、被查询历史/收藏/反馈引用的版本、以及最新 p_keep 个 READY 一律跳过。
CREATE FUNCTION text2sql.archive_versions(
        p_datasource_id UUID, p_keep INTEGER DEFAULT 3)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE archived INTEGER := 0; candidate UUID;
BEGIN
    IF p_keep < 0 THEN RAISE EXCEPTION 'p_keep must be >= 0'; END IF;
    FOR candidate IN
        SELECT v.id
          FROM text2sql.t2s_config_version v
         WHERE v.datasource_id = p_datasource_id
           AND v.status = 'READY'
           AND v.id IS DISTINCT FROM (
               SELECT d.active_version_id FROM text2sql.t2s_datasource d
                WHERE d.id = p_datasource_id)
           AND NOT EXISTS (SELECT 1 FROM text2sql.t2s_query_run r
                            WHERE r.version_id = v.id)
           AND NOT EXISTS (SELECT 1 FROM text2sql.t2s_favorite f
                            WHERE f.verified_version_id = v.id)
           AND NOT EXISTS (SELECT 1 FROM text2sql.t2s_feedback b
                            WHERE b.resolved_version_id = v.id)
           AND v.id NOT IN (
               SELECT v2.id FROM text2sql.t2s_config_version v2
                WHERE v2.datasource_id = p_datasource_id AND v2.status = 'READY'
                ORDER BY v2.revision DESC LIMIT p_keep)
         ORDER BY v.revision DESC
    LOOP
        UPDATE text2sql.t2s_config_version SET status = 'ARCHIVED' WHERE id = candidate;
        archived := archived + 1;
    END LOOP;
    RETURN archived;
END;
$$;

CREATE FUNCTION text2sql.purge_archived_knowledge(p_datasource_id UUID)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE removed INTEGER := 0;
BEGIN
    DELETE FROM text2sql.t2s_knowledge k
     WHERE k.datasource_id = p_datasource_id
       AND EXISTS (SELECT 1 FROM text2sql.t2s_config_version v
                    WHERE v.id = k.version_id AND v.status = 'ARCHIVED');
    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END;
$$;

DO $$
DECLARE tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['t2s_datasource','t2s_table','t2s_column','t2s_relation','t2s_value',
        't2s_metric','t2s_config_version','t2s_knowledge','t2s_index_job','t2s_query_run','t2s_favorite','t2s_feedback','t2s_workspace'] LOOP
        EXECUTE format('CREATE TRIGGER touch_updated_at BEFORE UPDATE ON text2sql.%I FOR EACH ROW EXECUTE FUNCTION text2sql.touch_updated_at()', tbl);
    END LOOP;
END;
$$;
COMMIT;
