"""`chat_query_trace` 的 DDL 常量（可执行 DDL 的唯一来源）。

同一份 DDL 还会被镜像到 ``deploy/init/pg/00-schema.sql``。两处必须保持一致：
快照测试校验 SQL 快照包含同一张表。

本模块**只放常量**，不 import FastAPI/psycopg2/infrastructure。
"""
from __future__ import annotations

TABLE_NAME = 'chat_query_trace'
TABLE = f'public.{TABLE_NAME}'

#: 终态枚举。`running` 只存在于内存 TraceState，不写库。
STATUS_OK = 'ok'
STATUS_ERROR = 'error'
STATUS_CLIENT_DISCONNECT = 'client_disconnect'
STATUS_VALUES = (STATUS_OK, STATUS_ERROR, STATUS_CLIENT_DISCONNECT)

#: INSERT 的列顺序（repository 与测试共用，避免两边各写一份）
COLUMN_NAMES = (
    'trace_id',
    'conversation_id',
    'workflow_id',
    'org_id',
    'is_stream',
    'status',
    'error_code',
    'http_status',
    'error_status',
    'question_len',
    'answer_len',
    'understanding_ms',
    'retrieval_ms',
    'rerank_ms',
    'generate_ms',
    'first_token_ms',
    'total_ms',
    'hit_count',
    'source_count',
    'kb_count',
    'top_score',
)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id               bigserial PRIMARY KEY,
    trace_id         varchar(64)  NOT NULL DEFAULT '',
    conversation_id      varchar(128) NOT NULL DEFAULT '',
    workflow_id      varchar(128) NOT NULL DEFAULT '',
    org_id           varchar(128) NOT NULL DEFAULT '',
    is_stream        boolean      NOT NULL DEFAULT false,
    status           varchar(24)  NOT NULL
                     CHECK (status IN ('ok','error','client_disconnect')),
    error_code       varchar(128) NOT NULL DEFAULT '',
    http_status      smallint,
    error_status     smallint,
    question_len     integer      NOT NULL DEFAULT 0,
    answer_len       integer      NOT NULL DEFAULT 0,
    understanding_ms numeric(12,1),
    retrieval_ms     numeric(12,1),
    rerank_ms        numeric(12,1),
    generate_ms      numeric(12,1),
    first_token_ms   numeric(12,1),
    total_ms         numeric(12,1),
    hit_count        integer      NOT NULL DEFAULT 0,
    source_count     integer      NOT NULL DEFAULT 0,
    kb_count         integer      NOT NULL DEFAULT 0,
    top_score        numeric(12,4),
    created_at       timestamptz  NOT NULL DEFAULT now(),
    updated_at       timestamptz  NOT NULL DEFAULT now()
)
""".strip()

CREATE_SET_UPDATED_AT_FUNCTION_SQL = '''CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$'''

CREATE_UPDATED_AT_TRIGGER_SQL = f'''CREATE OR REPLACE TRIGGER chat_query_trace_set_updated_at
    BEFORE UPDATE ON {TABLE}
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()'''

CREATE_INDEX_STATEMENTS = (
    f'CREATE INDEX IF NOT EXISTS idx_chat_query_trace_created '
    f'ON {TABLE} (created_at DESC, id DESC)',
    f'CREATE INDEX IF NOT EXISTS idx_chat_query_trace_workflow_created '
    f'ON {TABLE} (workflow_id, created_at DESC, id DESC)',
    f'CREATE INDEX IF NOT EXISTS idx_chat_query_trace_conversation_created '
    f'ON {TABLE} (conversation_id, created_at DESC, id DESC)',
    f'CREATE INDEX IF NOT EXISTS idx_chat_query_trace_org_created '
    f'ON {TABLE} (org_id, created_at DESC, id DESC)',
    f'CREATE INDEX IF NOT EXISTS idx_chat_query_trace_trace_id '
    f'ON {TABLE} (trace_id)',
)

INDEX_NAMES = (
    'idx_chat_query_trace_created',
    'idx_chat_query_trace_workflow_created',
    'idx_chat_query_trace_conversation_created',
    'idx_chat_query_trace_org_created',
    'idx_chat_query_trace_trace_id',
)

SCHEMA_STATEMENTS = (
    CREATE_SET_UPDATED_AT_FUNCTION_SQL,
    CREATE_TABLE_SQL,
    *CREATE_INDEX_STATEMENTS,
    CREATE_UPDATED_AT_TRIGGER_SQL,
)
