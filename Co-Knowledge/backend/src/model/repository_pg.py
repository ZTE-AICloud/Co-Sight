"""``model_registry`` 表的 PostgreSQL 实现。

**放哪个库**：业务库 ``rag_studio``（mode ``'0'``，``_db_pool.get_db_conn()``）——
与 ``flow_*`` 同库。
建表由**本模块自己**保证（见下方 ``SCHEMA_STATEMENTS`` 的注释；本仓没有 alembic/flyway）。
⚠️ ``DatabaseOperator.__init__`` **不再**在启动期执行任何建表脚本
（``exec_sql_file()`` 连同 agent 记忆那套表已退役）—— 这段描述随之更新。

**三条取舍沿用 ``workflow/repository_pg.py``**（那里的理由写得更长，这里只列结论）：

1. 不用 ``_db_pool.exec_sql`` / ``exec_ddl`` —— 它们把错误折成返回值或只打 warn，
   会把「表不存在」变成静默空结果。这里自己拿连接、自己提交/回滚、**异常一律抛**。
2. 自己管事务 —— 「设为默认」要同时清掉同类型的其他默认行，必须原子。
3. 时间戳在 SQL 里格式化（``to_char(..., 'YYYY-MM-DD HH24:MI:SS')``），
   与 ``flow_*`` 一致，管理页直接显示这个串。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from shared.errors.api import KbStoreError
from model import crypto, thinking_presets
from model.models import (
    SOURCE_USER,
    ModelRecord,
    new_model_id,
)

from infrastructure.db.rows import rows as _rows

TABLE_REGISTRY = 'model_registry'

# ---------------------------------------------------------------------------
# 建表语句（**唯一来源**，见 _ensure_schema 的长注释）
#
# ⚠️ 不要挪回启动期建表脚本：
# 那份 DDL 由 DatabaseOperator.__init__ 执行，而它的构造是**惰性且与 import 顺序
# 赛跑**的（应用 import 期第一次查本表时它还没跑完，报 relation
# "model_registry" does not exist，播种因此静默跳过）。
# 表由本模块自己保证存在，才与「谁先 import」无关。
# ---------------------------------------------------------------------------
SCHEMA_STATEMENTS = (
    '''CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$''',
    f'''CREATE TABLE IF NOT EXISTS {TABLE_REGISTRY} (
    model_id        character varying(64) NOT NULL,
    model_kind      character varying(16) NOT NULL,
    model_name      character varying(255) NOT NULL,
    display_name    character varying(255),
    api_model       character varying(255),
    base_url        character varying(1000) NOT NULL,
    -- 加密后是 enc:v1:<base64>，比明文长 ~40%；2000 足够容纳常见凭据。
    api_key         character varying(2000),
    chat_path       character varying(255),
    embeddings_path character varying(255),
    models_path     character varying(255),
    rerank_path     character varying(255),
    dimension       integer,
    max_tokens      integer,
    temperature     numeric(6, 4),
    timeout         integer,
    is_reasoning    boolean NOT NULL DEFAULT FALSE,
    -- none / auto / preset / custom；仅 LLM 有意义。
    thinking_mode   character varying(16) NOT NULL DEFAULT 'none',
    thinking_preset character varying(64),
    thinking_payload jsonb,
    is_default      boolean NOT NULL DEFAULT FALSE,
    enabled         boolean NOT NULL DEFAULT TRUE,
    source          character varying(16) NOT NULL DEFAULT 'user',
    remark          character varying(500),
    created_by      character varying(255),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model_id)
)''',
    f'''CREATE OR REPLACE TRIGGER {TABLE_REGISTRY}_set_updated_at
    BEFORE UPDATE ON {TABLE_REGISTRY}
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()''',
    f'''CREATE UNIQUE INDEX IF NOT EXISTS {TABLE_REGISTRY}_kind_name_uidx
    ON {TABLE_REGISTRY} (model_kind, model_name)''',
)

#: 本进程是否已经确保过表结构（每条连接都建一次表没必要，也拖慢首查）
_schema_ready = False


_TIMESTAMP = "to_char({column}, 'YYYY-MM-DD HH24:MI:SS') AS {column}"

#: 查询列（时间戳格式化后返回，与 flow_* 同一约定）
_COLUMNS = (
    'model_id, model_kind, model_name, display_name, api_model, base_url, api_key, '
    'chat_path, embeddings_path, models_path, rerank_path, '
    'dimension, max_tokens, temperature, timeout, '
    'is_reasoning, thinking_mode, thinking_preset, thinking_payload, '
    'is_default, enabled, source, remark, created_by, '
    + _TIMESTAMP.format(column='created_at') + ', '
    + _TIMESTAMP.format(column='updated_at')
)

_INSERT_SQL = (
    f'INSERT INTO {TABLE_REGISTRY} ('
    'model_id, model_kind, model_name, display_name, api_model, base_url, api_key, '
    'chat_path, embeddings_path, models_path, rerank_path, '
    'dimension, max_tokens, temperature, timeout, '
    'is_reasoning, thinking_mode, thinking_preset, thinking_payload, '
    'is_default, enabled, source, remark, created_by, updated_at'
    ') VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '
    '%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)'
)

_UPDATE_SQL = (
    f'UPDATE {TABLE_REGISTRY} SET '
    'model_kind = %s, model_name = %s, display_name = %s, api_model = %s, base_url = %s, '
    'api_key = %s, chat_path = %s, embeddings_path = %s, models_path = %s, rerank_path = %s, '
    'dimension = %s, max_tokens = %s, temperature = %s, timeout = %s, '
    'is_reasoning = %s, thinking_mode = %s, '
    'thinking_preset = %s, thinking_payload = %s::jsonb, '
    'is_default = %s, enabled = %s, remark = %s, '
    'updated_at = CURRENT_TIMESTAMP '
    'WHERE model_id = %s'
)

_CLEAR_DEFAULT_SQL = (
    f'UPDATE {TABLE_REGISTRY} SET is_default = FALSE, updated_at = CURRENT_TIMESTAMP '
    "WHERE model_kind = %s AND is_default = TRUE AND model_id <> %s"
)


def _json_value(value) -> Optional[str]:
    """dict → JSON 文本（SQL 侧再 ``%s::jsonb``），避免依赖 psycopg2.Json。"""
    if not isinstance(value, dict):
        return None
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _payload_value(value) -> Optional[dict]:
    """jsonb 列 → dict（psycopg2 正常给 dict；旧行/测试替身可能给字符串）。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _row_to_record(row: dict) -> ModelRecord:
    """一行 → :class:`ModelRecord`（列名与字段名一一对应，只差类型转换）。"""
    mode = (row.get('thinking_mode') or thinking_presets.MODE_NONE).strip().lower()
    if mode not in thinking_presets.THINKING_MODES:
        mode = thinking_presets.MODE_NONE
    return ModelRecord(
        model_id=row['model_id'],
        model_kind=row['model_kind'],
        model_name=row['model_name'],
        display_name=row.get('display_name') or '',
        api_model=row.get('api_model') or '',
        base_url=row['base_url'],
        # 落库是 enc:v1 密文；对外透明解密。
        api_key=crypto.decrypt(row.get('api_key') or ''),
        chat_path=row.get('chat_path') or '',
        embeddings_path=row.get('embeddings_path') or '',
        models_path=row.get('models_path') or '',
        rerank_path=row.get('rerank_path') or '',
        dimension=row.get('dimension'),
        max_tokens=row.get('max_tokens'),
        temperature=(float(row['temperature']) if row.get('temperature') is not None else None),
        timeout=row.get('timeout'),
        is_reasoning=bool(row.get('is_reasoning')),
        thinking_mode=mode,
        thinking_preset=row.get('thinking_preset') or '',
        thinking_payload=_payload_value(row.get('thinking_payload')),
        is_default=bool(row.get('is_default')),
        enabled=bool(row.get('enabled')),
        source=row.get('source') or SOURCE_USER,
        remark=row.get('remark') or '',
        created_at=row.get('created_at') or '',
        updated_at=row.get('updated_at') or '',
        created_by=row.get('created_by') or '',
    )


def _insert_params(record: ModelRecord) -> tuple:
    return (
        record.model_id, record.model_kind, record.model_name, record.display_name,
        record.api_model, record.base_url, crypto.encrypt(record.api_key),
        record.chat_path, record.embeddings_path, record.models_path, record.rerank_path,
        record.dimension, record.max_tokens, record.temperature, record.timeout,
        record.is_reasoning,
        record.thinking_mode, record.thinking_preset, _json_value(record.thinking_payload),
        record.is_default, record.enabled,
        record.source, record.remark, record.created_by,
    )


def _update_params(record: ModelRecord) -> tuple:
    """UPDATE 的参数。

    **不含 ``source`` 与 ``created_by``** —— 用户改一行不该把它变成「自己登记的」：
    ``source`` 记录的是这一行**从哪来的**（env 播种 / 用户新建），
    改个显示名就把它抹掉，就再也分不清哪些行是部署自带的。
    """
    return (
        record.model_kind, record.model_name, record.display_name, record.api_model,
        record.base_url, crypto.encrypt(record.api_key),
        record.chat_path, record.embeddings_path, record.models_path, record.rerank_path,
        record.dimension, record.max_tokens, record.temperature, record.timeout,
        record.is_reasoning,
        record.thinking_mode, record.thinking_preset, _json_value(record.thinking_payload),
        record.is_default, record.enabled,
        record.remark, record.model_id,
    )


class PgModelStore:
    """``ModelStore`` 的 PostgreSQL 实现（协议见 ``store.py``）。"""

    # ------------------------------------------------------------------
    # 连接与语句执行（与 PgFlowStore 同形，见本模块 docstring 的三条取舍）
    # ------------------------------------------------------------------

    def _connect(self):
        """取业务库连接。

        延迟 import：``tool.utils.database_pool_operator`` 在模块级就构造连接池
        （import 期连库），单测环境不需要 psycopg2，不该被拖下水。
        """
        from infrastructure.db.pool import _db_pool

        return _db_pool.get_db_conn()

    def _ensure_schema(self, conn) -> None:
        """确保表存在（每进程一次）。

        **为什么不能只靠启动期建表脚本**：原 ``sql/init_table.sql`` 由
        ``DatabaseOperator.__init__`` 执行，而那个构造是惰性的、且与 import 顺序赛跑
        —— 实测应用 import 期第一次查本表时它还没跑完（另一个线程 11 秒后才建好表），
        于是「首次播种」静默跳过、管理页空着，而**日志里只有一条 warning**。
        （该文件已随旧 corpus 三表一起删除。）

        由本模块自己保证，就与「谁先 import、谁先连库」无关了。
        """
        global _schema_ready
        if _schema_ready:
            return
        with conn.cursor() as cursor:
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)
        _schema_ready = True

    def _execute(self, sql: str, params: tuple = (), *, fetch: Optional[str] = None) -> Any:
        import psycopg2
        from psycopg2 import errors as pg_errors

        conn = cursor = None
        try:
            conn = self._connect()
            self._ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(sql, params)
            result = None
            if fetch == 'all':
                result = _rows(cursor)
            elif fetch == 'one':
                rows = _rows(cursor)
                result = rows[0] if rows else None
            conn.commit()
            return result
        except pg_errors.UniqueViolation as e:
            if conn is not None:
                conn.rollback()
            raise KbStoreError(KbStoreError.DUPLICATE, str(e).strip(), 'duplicate key') from e
        except psycopg2.Error as e:
            if conn is not None:
                conn.rollback()
            # 「表还不存在」是最可能的第一现场：带原始报错出去，别变成空结果
            raise KbStoreError(KbStoreError.DB_ERROR, str(e).strip()) from e
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    def _execute_transaction(self, statements: list) -> None:
        """把多条语句放进同一事务；任一条失败整体回滚并抛出。"""
        import psycopg2
        from psycopg2 import errors as pg_errors

        conn = cursor = None
        try:
            conn = self._connect()
            self._ensure_schema(conn)
            cursor = conn.cursor()
            for sql, params in statements:
                cursor.execute(sql, params)
            conn.commit()
        except Exception as e:
            if conn is not None:
                conn.rollback()
            if isinstance(e, pg_errors.UniqueViolation):
                raise KbStoreError(KbStoreError.DUPLICATE, str(e).strip(), 'duplicate key') from e
            if isinstance(e, psycopg2.Error):
                raise KbStoreError(KbStoreError.DB_ERROR, str(e).strip()) from e
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    # ------------------------------------------------------------------
    # ModelStore 协议
    # ------------------------------------------------------------------

    def list_records(self, kind: Optional[str] = None) -> list[ModelRecord]:
        sql = f'SELECT {_COLUMNS} FROM {TABLE_REGISTRY}'
        params: tuple = ()
        if kind:
            sql += ' WHERE model_kind = %s'
            params = (kind,)
        # 默认模型排最前，其余按注册名 —— 管理页与下拉都不用人肉找
        sql += ' ORDER BY model_kind, is_default DESC, model_name'
        rows = self._execute(sql, params, fetch='all') or []
        return [_row_to_record(row) for row in rows]

    def get_record(self, model_id: str) -> Optional[ModelRecord]:
        sql = f'SELECT {_COLUMNS} FROM {TABLE_REGISTRY} WHERE model_id = %s'
        row = self._execute(sql, (model_id,), fetch='one')
        return _row_to_record(row) if row else None

    def find_by_name(self, kind: str, model_name: str) -> Optional[ModelRecord]:
        sql = (f'SELECT {_COLUMNS} FROM {TABLE_REGISTRY} '
               'WHERE model_kind = %s AND model_name = %s')
        row = self._execute(sql, (kind, model_name), fetch='one')
        return _row_to_record(row) if row else None

    def insert(self, record: ModelRecord) -> None:
        # 主键由调用方（service / 播种）分配；这里兜底补一个，免得插进一行 id 为空的记录
        if not record.model_id:
            record = record.with_changes(model_id=new_model_id())
        statements = []
        if record.is_default:
            statements.append((_CLEAR_DEFAULT_SQL, (record.model_kind, record.model_id)))
        statements.append((_INSERT_SQL, _insert_params(record)))
        self._execute_transaction(statements)

    def update(self, record: ModelRecord) -> None:
        statements = []
        if record.is_default:
            statements.append((_CLEAR_DEFAULT_SQL, (record.model_kind, record.model_id)))
        statements.append((_UPDATE_SQL, _update_params(record)))
        self._execute_transaction(statements)

    def delete(self, model_id: str) -> None:
        self._execute(f'DELETE FROM {TABLE_REGISTRY} WHERE model_id = %s', (model_id,))

    def clear_default(self, kind: str, keep_id: Optional[str] = None) -> None:
        self._execute(
            f'UPDATE {TABLE_REGISTRY} SET is_default = FALSE, updated_at = CURRENT_TIMESTAMP '
            'WHERE model_kind = %s AND is_default = TRUE AND model_id <> %s',
            (kind, keep_id or ''))
