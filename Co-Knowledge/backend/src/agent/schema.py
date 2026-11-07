"""``public.agent_api_key`` 的 DDL **单一来源**。

为什么单独一个模块：
- CLI 与测试都不能 import
  FastAPI / MCP（最小运行环境不一定装齐），所以 DDL 不能放在 ``repository_pg.py``
  里跟着业务依赖一起被拉起；
- 空卷新装的 ``deploy/init/pg/00-schema.sql`` 是静态快照，无法 import 本模块，
  那里的 SQL 必须与这里完全一致（文件末尾有交叉引用注释）。

表放 ``public``：与 ``model_registry`` / ``flow_*`` 同库（``rag_studio``），
由 ``infrastructure.db.kb.connection()`` 访问。
"""

from __future__ import annotations

TABLE_NAME = 'public.agent_api_key'

#: 只在创建时返回明文；库里只存 key_prefix 与 HMAC-SHA256 哈希。
CREATE_TABLE_SQL = f'''CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id                 bigserial PRIMARY KEY,
    name               character varying(128) NOT NULL,
    description        character varying(200),
    key_prefix         character varying(32) NOT NULL,
    key_hash           character(64) NOT NULL,
    scopes             text[] NOT NULL DEFAULT ARRAY[]::text[],
    kb_ids             text[] NOT NULL DEFAULT ARRAY[]::text[],
    rate_limit_per_min integer NOT NULL DEFAULT 60,
    enabled            boolean NOT NULL DEFAULT TRUE,
    expires_at         timestamp with time zone,
    last_used_at       timestamp with time zone,
    created_by         character varying(128),
    created_at         timestamp with time zone NOT NULL DEFAULT now(),
    updated_at         timestamp with time zone NOT NULL DEFAULT now()
)'''

CREATE_UNIQUE_INDEX_SQL = f'''CREATE UNIQUE INDEX IF NOT EXISTS agent_api_key_prefix_uidx
    ON {TABLE_NAME} (key_prefix)'''

CREATE_SET_UPDATED_AT_FUNCTION_SQL = '''CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$'''

CREATE_UPDATED_AT_TRIGGER_SQL = f'''CREATE OR REPLACE TRIGGER agent_api_key_set_updated_at
    BEFORE UPDATE ON {TABLE_NAME}
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()'''

#: 用途说明字段；单独一条幂等 ALTER，供 CLI 的 ``ensure`` 复用。
ADD_DESCRIPTION_SQL = (
    f'ALTER TABLE {TABLE_NAME} '
    'ADD COLUMN IF NOT EXISTS description character varying(200)'
)

#: 每 Key 每自然日的调用计数。
#:
#: 「总调用量」与「最近 7 天请求数」都从这一张表聚合，不再给 ``agent_api_key``
#: 加计数器列：两个口径共用一个来源，删 Key 时由外键级联清空历史。
#: 计量口径是**鉴权通过**的请求（401/429 不计），日期按 Asia/Shanghai 切分。
USAGE_TABLE_NAME = 'public.agent_api_key_usage'

CREATE_USAGE_TABLE_SQL = f'''CREATE TABLE IF NOT EXISTS {USAGE_TABLE_NAME} (
    key_prefix    character varying(32) NOT NULL,
    usage_date    date        NOT NULL,
    request_count bigint      NOT NULL DEFAULT 0,
    created_at    timestamp with time zone NOT NULL DEFAULT now(),
    updated_at    timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT agent_api_key_usage_pkey PRIMARY KEY (key_prefix, usage_date),
    CONSTRAINT fk_agent_api_key_usage_agent_api_key
        FOREIGN KEY (key_prefix) REFERENCES {TABLE_NAME} (key_prefix)
        ON DELETE CASCADE
)'''

#: 「最近 N 天」按 ``usage_date`` 过滤，大表时避免全表扫描。
CREATE_USAGE_DATE_INDEX_SQL = (
    f'CREATE INDEX IF NOT EXISTS idx_agent_api_key_usage_usage_date '
    f'ON {USAGE_TABLE_NAME} (usage_date)'
)

CREATE_USAGE_UPDATED_AT_TRIGGER_SQL = f'''CREATE OR REPLACE TRIGGER agent_api_key_usage_set_updated_at
    BEFORE UPDATE ON {USAGE_TABLE_NAME}
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()'''

#: 只含调用计数表的语句。
USAGE_SCHEMA_STATEMENTS = (
    CREATE_USAGE_TABLE_SQL,
    CREATE_USAGE_DATE_INDEX_SQL,
    CREATE_USAGE_UPDATED_AT_TRIGGER_SQL,
)

#: CLI 的 ``ensure`` 按这个顺序执行；全部幂等。
SCHEMA_STATEMENTS = (
    CREATE_SET_UPDATED_AT_FUNCTION_SQL,
    CREATE_TABLE_SQL,
    CREATE_UNIQUE_INDEX_SQL,
    ADD_DESCRIPTION_SQL,
    CREATE_UPDATED_AT_TRIGGER_SQL,
    *USAGE_SCHEMA_STATEMENTS,
)
