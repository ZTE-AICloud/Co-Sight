"""``auth_user`` / ``auth_session`` 的 DDL **单一来源**。

为什么单独一个模块（与 ``agent/schema.py`` 同因）：

- CLI 与测试不能 import FastAPI，
  所以 DDL 不能放在 ``repository.py`` 里跟着 Web 依赖一起被拉起；
- 空卷新装的 ``deploy/init/pg/00-schema.sql`` 无法 import 本模块，那里的 SQL
  必须与这里**完全一致**（文件末尾有交叉引用注释）；
- 本模块不 import 任何项目内模块，保持可被最小环境导入。

**无外键**：与 ``docs/database-schema.md`` 的既有约定一致（关系由应用维护）。
删除用户时在同一事务里删除其会话。

**命名**：用 ``auth_user`` 而不是历史 ``t_user``。后者是 NAE 身份镜像
（没有密码列），该表已 DROP；不要复活旧表语义。
"""

from __future__ import annotations

USER_TABLE = 'public.auth_user'
SESSION_TABLE = 'public.auth_session'

CREATE_USER_TABLE_SQL = f'''CREATE TABLE IF NOT EXISTS {USER_TABLE} (
    id                   bigserial PRIMARY KEY,
    username             character varying(64) NOT NULL,
    email                character varying(255),
    display_name         character varying(128),
    password_hash        character varying(255) NOT NULL,
    role                 character varying(16)  NOT NULL DEFAULT 'user',
    enabled              boolean      NOT NULL DEFAULT TRUE,
    must_change_password boolean      NOT NULL DEFAULT FALSE,
    last_login_at        timestamp with time zone,
    created_at           timestamp with time zone NOT NULL DEFAULT now(),
    updated_at           timestamp with time zone NOT NULL DEFAULT now()
)'''

#: 用户名大小写不敏感唯一（登录按 lower(username) 比较）。
CREATE_USER_USERNAME_INDEX_SQL = f'''CREATE UNIQUE INDEX IF NOT EXISTS auth_user_username_lower_uidx
    ON {USER_TABLE} (lower(username))'''

#: 邮箱可选；只有非 NULL 才参与唯一约束（空串在写入前归一成 NULL）。
CREATE_USER_EMAIL_INDEX_SQL = f'''CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_lower_uidx
    ON {USER_TABLE} (lower(email)) WHERE email IS NOT NULL'''

CREATE_SESSION_TABLE_SQL = f'''CREATE TABLE IF NOT EXISTS {SESSION_TABLE} (
    id           bigserial PRIMARY KEY,
    token_hash   character(64) NOT NULL,
    user_id      bigint        NOT NULL,
    created_at   timestamp with time zone NOT NULL DEFAULT now(),
    last_seen_at timestamp with time zone NOT NULL DEFAULT now(),
    expires_at   timestamp with time zone NOT NULL,
    revoked_at   timestamp with time zone,
    ip           character varying(64),
    user_agent   character varying(255),
    updated_at   timestamp with time zone NOT NULL DEFAULT now()
)'''

CREATE_SESSION_TOKEN_INDEX_SQL = f'''CREATE UNIQUE INDEX IF NOT EXISTS auth_session_token_hash_uidx
    ON {SESSION_TABLE} (token_hash)'''

CREATE_SESSION_USER_INDEX_SQL = f'''CREATE INDEX IF NOT EXISTS auth_session_user_id_idx
    ON {SESSION_TABLE} (user_id)'''

CREATE_SESSION_EXPIRES_INDEX_SQL = f'''CREATE INDEX IF NOT EXISTS auth_session_expires_at_idx
    ON {SESSION_TABLE} (expires_at)'''

CREATE_SET_UPDATED_AT_FUNCTION_SQL = '''CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$'''

CREATE_USER_UPDATED_AT_TRIGGER_SQL = f'''CREATE OR REPLACE TRIGGER auth_user_set_updated_at
    BEFORE UPDATE ON {USER_TABLE}
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()'''

CREATE_SESSION_UPDATED_AT_TRIGGER_SQL = f'''CREATE OR REPLACE TRIGGER auth_session_set_updated_at
    BEFORE UPDATE ON {SESSION_TABLE}
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()'''

#: CLI 的 ``ensure`` 按这个顺序执行；全部幂等。
SCHEMA_STATEMENTS = (
    CREATE_SET_UPDATED_AT_FUNCTION_SQL,
    CREATE_USER_TABLE_SQL,
    CREATE_USER_USERNAME_INDEX_SQL,
    CREATE_USER_EMAIL_INDEX_SQL,
    CREATE_USER_UPDATED_AT_TRIGGER_SQL,
    CREATE_SESSION_TABLE_SQL,
    CREATE_SESSION_TOKEN_INDEX_SQL,
    CREATE_SESSION_USER_INDEX_SQL,
    CREATE_SESSION_EXPIRES_INDEX_SQL,
    CREATE_SESSION_UPDATED_AT_TRIGGER_SQL,
)
