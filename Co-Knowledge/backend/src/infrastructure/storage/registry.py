"""``kb_storage_registry``：知识库存储生命周期表（P2）。

P1 时它是一张**只读视图**（从 ``kb_kbase`` + ``model_registry`` +
``information_schema`` 现算）。视图不会说谎，但有两个缺口：

* 建库中途失败（表建了一半）没有地方记录「这个库处于 creating/failed」；
* 删除中途失败后，只能靠人工对比 ``information_schema`` 找残留。

P2 改成**表 + 状态机**，由建库/删库流程显式推进：

    creating → ready
        ↓         ↓
      failed   deleting → (row removed)

写入是**尽力而为**：注册表失败只记 ERROR，不阻断建库/删库（它是运维观测面，
不是业务事实源）。可用 ``reconcile()`` 把表与 ``kb_kbase`` / 物理表对账。
"""

from __future__ import annotations

from typing import Optional

from infrastructure.db.identifiers import chunk_table_for
from infrastructure.db.kb import connection
from infrastructure.logging.logutil import log

TABLE = 'public.kb_storage_registry'

STATE_CREATING = 'creating'
STATE_READY = 'ready'
STATE_FAILED = 'failed'
STATE_DELETING = 'deleting'

_DDL = f'''
CREATE TABLE IF NOT EXISTS {TABLE} (
    kbase_id          varchar(64) PRIMARY KEY,
    name              varchar(255) NOT NULL,
    category          smallint,
    vector_table      varchar(255),
    chunk_table       varchar(255),
    graph_vector_table varchar(255),
    embedding_model   varchar(255),
    embedding_dim     integer,
    state             varchar(16) NOT NULL,
    detail            text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kb_storage_registry_state_idx
    ON {TABLE} (state);
CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;
CREATE OR REPLACE TRIGGER kb_storage_registry_set_updated_at
    BEFORE UPDATE ON {TABLE}
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
'''


_ready = False


def ensure_table() -> None:
    global _ready
    if _ready:
        return
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(_DDL)
    _ready = True


def _write(sql: str, params: tuple) -> None:
    """生命周期写入：失败只记 ERROR，不影响主流程。"""
    try:
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
    except Exception:                                              # noqa: BLE001
        log.exception('kb_storage_registry write failed: %s', sql.split()[0])


def begin_create(kbase_id: str, name: str, category, vector_table: str,
                 embedding_model: Optional[str], embedding_dim: Optional[int]) -> None:
    ensure_table()
    chunk_table = chunk_table_for(vector_table)
    graph_vector = f'{vector_table}_vector' if str(category) == '10' else None
    _write(
        f'INSERT INTO {TABLE} (kbase_id, name, category, vector_table, chunk_table, '
        'graph_vector_table, embedding_model, embedding_dim, state, detail) '
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL) "
        'ON CONFLICT (kbase_id) DO UPDATE SET '
        'name = EXCLUDED.name, category = EXCLUDED.category, '
        'vector_table = EXCLUDED.vector_table, chunk_table = EXCLUDED.chunk_table, '
        'graph_vector_table = EXCLUDED.graph_vector_table, '
        'embedding_model = EXCLUDED.embedding_model, '
        'embedding_dim = EXCLUDED.embedding_dim, '
        'state = EXCLUDED.state, detail = NULL, updated_at = now()',
        (kbase_id, name, category, vector_table, chunk_table, graph_vector,
         embedding_model, embedding_dim, STATE_CREATING))


def mark_ready(kbase_id: str) -> None:
    _write(
        f"UPDATE {TABLE} SET state = %s, detail = NULL, updated_at = now() "
        'WHERE kbase_id = %s', (STATE_READY, kbase_id))


def mark_failed(kbase_id: str, detail: str) -> None:
    _write(
        f"UPDATE {TABLE} SET state = %s, detail = %s, updated_at = now() "
        'WHERE kbase_id = %s', (STATE_FAILED, str(detail)[:1000], kbase_id))


def begin_delete(kbase_id: str) -> None:
    _write(
        f"UPDATE {TABLE} SET state = %s, updated_at = now() WHERE kbase_id = %s",
        (STATE_DELETING, kbase_id))


def remove(kbase_id: str) -> None:
    _write(f'DELETE FROM {TABLE} WHERE kbase_id = %s', (kbase_id,))


def list_rows() -> list[dict]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT kbase_id, name, category, vector_table, chunk_table, '
                f'graph_vector_table, embedding_model, embedding_dim, state, detail, '
                f'created_at, updated_at FROM {TABLE} ORDER BY created_at')
            names = [description[0] for description in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]


def reconcile() -> dict:
    """把注册表与 ``kb_kbase`` / 物理表对账。

    * 已启用但注册表没有的库 → 补一行（表在 = ready，表不在 = failed）；
    * ready/creating/deleting 行但向量表不存在 → 标 failed（detail=vector table missing）；
    * 已不存在（物理删）的库仍有行 → 删除该行。

    返回 ``{inserted, failed, removed, checked}``，供运维脚本打印。
    """
    stats = {'inserted': 0, 'failed': 0, 'removed': 0, 'checked': 0}
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT kbase_id, name, category, table_name, embedding_model '
                "FROM public.kb_kbase")
            kbases = cursor.fetchall()
            cursor.execute(f'SELECT kbase_id, state FROM {TABLE}')
            registry = {row[0]: row[1] for row in cursor.fetchall()}
            enabled_ids = {row[0] for row in kbases}

            for kbase_id, name, category, table_name, embedding_model in kbases:
                stats['checked'] += 1
                exists = _table_exists(cursor, table_name)
                state = STATE_READY if exists else STATE_FAILED
                if kbase_id not in registry:
                    cursor.execute(
                        f'INSERT INTO {TABLE} (kbase_id, name, category, vector_table, '
                        'chunk_table, graph_vector_table, embedding_model, state, detail) '
                        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) '
                        'ON CONFLICT (kbase_id) DO NOTHING',
                        (kbase_id, name, category, table_name, chunk_table_for(table_name),
                         f'{table_name}_vector' if str(category) == '10' else None,
                         embedding_model, state,
                         None if exists else 'vector table missing'))
                    stats['inserted'] += 1
                elif not exists and registry[kbase_id] != STATE_DELETING:
                    cursor.execute(
                        f"UPDATE {TABLE} SET state = %s, detail = %s, updated_at = now() "
                        'WHERE kbase_id = %s',
                        (STATE_FAILED, 'vector table missing', kbase_id))
                    stats['failed'] += 1

            for kbase_id in list(registry):
                if kbase_id not in enabled_ids:
                    cursor.execute(f'DELETE FROM {TABLE} WHERE kbase_id = %s', (kbase_id,))
                    stats['removed'] += 1
        conn.commit()
    return stats


def _table_exists(cursor, table_name: Optional[str]) -> bool:
    if not table_name:
        return False
    cursor.execute(
        'SELECT EXISTS (SELECT 1 FROM information_schema.tables '
        "WHERE table_schema = 'kb_index' AND table_name = %s)", (table_name,))
    return bool(cursor.fetchone()[0])
