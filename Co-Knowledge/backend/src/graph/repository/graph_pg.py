"""PostgreSQL 图谱存储。

每个图谱知识库两张表（schema ``kb_index``，与 ``graph_<uuid>`` 基名一致）：

* ``graph_<uuid>_vertex``：``entity_id`` 主键 + ``entity_type`` + 属性 JSONB；
* ``graph_<uuid>_edge``：``edge_id`` 主键 + ``edge_type`` + 两端 + 属性 JSONB。

行在返回时**保留图行形状**（``@rid`` / ``@class`` / ``out`` / ``in`` + 平铺属性），
这样 ``graph_common.to_entity/to_edge`` 与查询层不用改响应装配。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from graph.constants import GRAPH_TABLE_PREFIX
from graph.errors import GraphException
from infrastructure.logging.logutil import log

SCHEMA = 'kb_index'


class PgGraphClient:
    """轻量客户端：只带基名（``graph_<uuid>``），不持有连接（连接走池）。"""

    def __init__(self, dbname: str):
        self.dbname = dbname

    def __repr__(self) -> str:
        return f'PgGraphClient({self.dbname!r})'


def new_client(dbname: str) -> PgGraphClient:
    return PgGraphClient(dbname)


def vertex_table(dbname: str) -> str:
    return f'{dbname}_vertex'


def edge_table(dbname: str) -> str:
    return f'{dbname}_edge'


def _connect():
    from infrastructure.db.kb import connection

    return connection()


def _ident(name: str) -> str:
    from infrastructure.db.identifiers import validate_identifier

    validate_identifier(name)
    return f'{SCHEMA}.{name}'


def ensure_database_exists(client: PgGraphClient, dbname: Optional[str] = None) -> bool:
    """建两张表（幂等）。返回是否**新建**了表。"""
    name = dbname or client.dbname
    vtable, etable = _ident(vertex_table(name)), _ident(edge_table(name))
    ddl = f'''
    CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$;
    CREATE TABLE IF NOT EXISTS {vtable} (
        id           BIGSERIAL PRIMARY KEY,
        entity_id    VARCHAR(255) NOT NULL UNIQUE,
        entity_type  VARCHAR(255),
        properties   JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS {vertex_table(name)}_type_idx
        ON {vtable} (entity_type);
    CREATE INDEX IF NOT EXISTS {vertex_table(name)}_props_idx
        ON {vtable} USING gin (properties);
    CREATE OR REPLACE TRIGGER {vertex_table(name)}_set_updated_at
        BEFORE UPDATE ON {vtable}
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    CREATE TABLE IF NOT EXISTS {etable} (
        id           BIGSERIAL PRIMARY KEY,
        edge_id      VARCHAR(255) NOT NULL UNIQUE,
        edge_type    VARCHAR(255),
        source_id    VARCHAR(255) NOT NULL,
        target_id    VARCHAR(255) NOT NULL,
        properties   JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS {edge_table(name)}_type_idx
        ON {etable} (edge_type);
    CREATE INDEX IF NOT EXISTS {edge_table(name)}_source_idx
        ON {etable} (source_id);
    CREATE INDEX IF NOT EXISTS {edge_table(name)}_target_idx
        ON {etable} (target_id);
    CREATE INDEX IF NOT EXISTS {edge_table(name)}_props_idx
        ON {etable} USING gin (properties);
    CREATE OR REPLACE TRIGGER {edge_table(name)}_set_updated_at
        BEFORE UPDATE ON {etable}
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    '''
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(ddl)
    log.info('ensured PG graph tables for %s', name)
    return True


def is_database_exists(client: PgGraphClient) -> bool:
    from infrastructure.db.ddl import table_exists

    try:
        return table_exists(vertex_table(client.dbname)) and table_exists(
            edge_table(client.dbname))
    except Exception:                                              # noqa: BLE001
        return False


def count_entities_and_edges(dbname: str) -> Optional[dict[str, int]]:
    """Exact row counts of the vertex/edge tables for ``dbname``.

    ``None`` means the graph store has not been created yet (still building or
    never extracted), which callers must distinguish from an empty graph
    (``{'entityCount': 0, 'edgeCount': 0}``).  These are physical table counts
    — deliberately independent of any query filter or page size.
    """
    if not is_database_exists(new_client(dbname)):
        return None
    vtable, etable = _ident(vertex_table(dbname)), _ident(edge_table(dbname))
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT (SELECT count(*) FROM {vtable}), '
                f'(SELECT count(*) FROM {etable})')
            row = cursor.fetchone()
    if row is None:
        return {'entityCount': 0, 'edgeCount': 0}
    return {'entityCount': int(row[0] or 0), 'edgeCount': int(row[1] or 0)}


def drop_database(client: PgGraphClient, target_dbname: str,
                  *, missing_ok: bool = False) -> None:
    vtable, etable = _ident(vertex_table(target_dbname)), _ident(edge_table(target_dbname))
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS {etable}')
            cursor.execute(f'DROP TABLE IF EXISTS {vtable}')
    log.info('dropped PG graph tables for %s', target_dbname)


# ----------------------------------------------------------------------
# 行形状
# ----------------------------------------------------------------------


_DATE_RE = __import__('re').compile(r'^\d{4}-\d{2}-\d{2}$')


def _normalize_value(value):
    """图存储的 DATE 属性会把 ``YYYY-MM-DD`` 回显成 ``YYYY-MM-DD 00:00:00``。

    PG 存 JSONB 不会做类型推导，这里按同样形状归一，保证响应形状一致。
    """
    if isinstance(value, str) and _DATE_RE.match(value):
        return value + ' 00:00:00'
    return value


def _split_properties(properties: dict, reserved: set[str]) -> dict:
    result = {}
    for key, value in (properties or {}).items():
        if key in reserved or key.startswith('@'):
            continue
        result[str(key)] = _normalize_value(value)
    return result


def _vertex_row(row: dict) -> dict:
    entity_id, entity_type, raw = row[0], row[1], row[2]
    properties = raw if isinstance(raw, dict) else json.loads(raw or '{}')
    shaped = {'@rid': f'#{row[3]}:0', '@class': entity_type, 'entity_id': entity_id}
    shaped.update(properties)
    return shaped


def _edge_row(row: dict) -> dict:
    edge_id, edge_type, source_id, target_id, raw = row[0], row[1], row[2], row[3], row[4]
    properties = raw if isinstance(raw, dict) else json.loads(raw or '{}')
    # ``out``/``in`` 必须是**顶点 RID**（路径提取按 RID 匹配实体）；
    # ``source_id``/``target_id`` 继续是业务 entity_id。
    source_rid = f'#{row[6]}:0' if row[6] is not None else source_id
    target_rid = f'#{row[7]}:0' if row[7] is not None else target_id
    shaped = {
        '@rid': f'#{row[5]}:0', '@class': edge_type,
        'edge_id': edge_id, 'source_id': source_id, 'target_id': target_id,
        'out': source_rid, 'in': target_rid,
    }
    shaped.update(properties)
    return shaped


_VERTEX_SELECT = 'entity_id, entity_type, properties, id'


def _edge_select(dbname: str) -> str:
    """边查询列：额外带两端顶点的 RID 数字部分（用于 ``out``/``in``）。"""
    vtable = _ident(vertex_table(dbname))
    return (f'e.edge_id, e.edge_type, e.source_id, e.target_id, e.properties, e.id, '
            f'(SELECT v.id FROM {vtable} v WHERE v.entity_id = e.source_id) AS source_vid, '
            f'(SELECT v.id FROM {vtable} v WHERE v.entity_id = e.target_id) AS target_vid')


# ----------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------


def entity_exists(client: PgGraphClient, entity_type: str, entity_id: str) -> bool:
    try:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT 1 FROM {_ident(vertex_table(client.dbname))} '
                    'WHERE entity_id = %s LIMIT 1', (entity_id,))
                return cursor.fetchone() is not None
    except Exception:                                              # noqa: BLE001
        return False


def edge_exists(client: PgGraphClient, edge_type: str, edge_id: str) -> bool:
    try:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT 1 FROM {_ident(edge_table(client.dbname))} '
                    'WHERE edge_id = %s LIMIT 1', (edge_id,))
                return cursor.fetchone() is not None
    except Exception:                                              # noqa: BLE001
        return False


def get_entity_properties(client: PgGraphClient, entity_type: str, entity_id: str) -> dict:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT {_VERTEX_SELECT} FROM {_ident(vertex_table(client.dbname))} '
                'WHERE entity_id = %s LIMIT 1', (entity_id,))
            row = cursor.fetchone()
    if not row:
        raise GraphException('KG020', f'Entity not found: {entity_id}')
    return _vertex_row(row)


def get_edge_properties(client: PgGraphClient, edge_type: str, edge_id: str) -> dict:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT {_edge_select(client.dbname)} FROM {_ident(edge_table(client.dbname))} AS e '
                'WHERE e.edge_id = %s LIMIT 1', (edge_id,))
            row = cursor.fetchone()
    if not row:
        raise GraphException('KG022', f'Edge not found: {edge_id}')
    return _edge_row(row)


#: 批量导入时一条 INSERT 的行数（4 列 × 500 = 2000 个参数，远低于 PG 上限）
_BULK_BATCH_SIZE = 500


def upsert_entities_bulk(dbname: str, rows: Iterable[tuple]) -> None:
    """批量 upsert 实体；一行 SQL 插 500 条，避免每行一次借连接/提交。

    ``rows``：``(entity_type, entity_id, properties, labels)``。
    """
    payload = []
    for entity_type, entity_id, properties, labels in rows:
        props = _split_properties(properties or {}, {'entity_id', 'entity_type'})
        if isinstance(labels, list) and labels:
            props['#labels'] = labels
        payload.append((entity_id, entity_type,
                        json.dumps(props, ensure_ascii=False)))
    if not payload:
        return
    with _connect() as conn:
        with conn.cursor() as cursor:
            for start in range(0, len(payload), _BULK_BATCH_SIZE):
                chunk = payload[start:start + _BULK_BATCH_SIZE]
                values = ','.join(['(%s, %s, %s::jsonb)'] * len(chunk))
                cursor.execute(
                    f'INSERT INTO {_ident(vertex_table(dbname))} AS t '
                    '(entity_id, entity_type, properties) VALUES ' + values +
                    ' ON CONFLICT (entity_id) DO UPDATE SET '
                    'entity_type = EXCLUDED.entity_type, '
                    'properties = t.properties || EXCLUDED.properties, '
                    'updated_at = CURRENT_TIMESTAMP',
                    [value for row in chunk for value in row])


def upsert_edges_bulk(dbname: str, rows: Iterable[tuple]) -> None:
    """批量 upsert 边。``rows``：``(edge_type, edge_id, source_id, target_id,
    properties, labels)``。"""
    payload = []
    for edge_type, edge_id, source_id, target_id, properties, labels in rows:
        props = _split_properties(
            properties or {}, {'edge_id', 'source_id', 'target_id', 'edge_type'})
        if isinstance(labels, list) and labels:
            props['#labels'] = labels
        payload.append((edge_id, edge_type, source_id, target_id,
                        json.dumps(props, ensure_ascii=False)))
    if not payload:
        return
    with _connect() as conn:
        with conn.cursor() as cursor:
            for start in range(0, len(payload), _BULK_BATCH_SIZE):
                chunk = payload[start:start + _BULK_BATCH_SIZE]
                values = ','.join(['(%s, %s, %s, %s, %s::jsonb)'] * len(chunk))
                cursor.execute(
                    f'INSERT INTO {_ident(edge_table(dbname))} AS t '
                    '(edge_id, edge_type, source_id, target_id, properties) '
                    'VALUES ' + values +
                    ' ON CONFLICT (edge_id) DO UPDATE SET '
                    'edge_type = EXCLUDED.edge_type, '
                    'source_id = EXCLUDED.source_id, '
                    'target_id = EXCLUDED.target_id, '
                    'properties = t.properties || EXCLUDED.properties, '
                    'updated_at = CURRENT_TIMESTAMP',
                    [value for row in chunk for value in row])


def upsert_entity(dbname: str, entity_type: str, entity_id: str,
                  properties: dict, labels=None) -> None:
    """导入引擎用的 upsert（等价 ``UPDATE ... UPSERT WHERE entity_id``）。"""
    props = _split_properties(properties or {}, {'entity_id', 'entity_type'})
    if isinstance(labels, list) and labels:
        props['#labels'] = labels
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {_ident(vertex_table(dbname))} AS t '
                '(entity_id, entity_type, properties) VALUES (%s, %s, %s::jsonb) '
                'ON CONFLICT (entity_id) DO UPDATE SET '
                'entity_type = EXCLUDED.entity_type, '
                'properties = t.properties || EXCLUDED.properties, '
                'updated_at = CURRENT_TIMESTAMP',
                (entity_id, entity_type, json.dumps(props, ensure_ascii=False)))


def upsert_edge(dbname: str, edge_type: str, edge_id: str, source_id: str,
                target_id: str, properties: dict, labels=None) -> None:
    props = _split_properties(
        properties or {}, {'edge_id', 'source_id', 'target_id', 'edge_type'})
    if isinstance(labels, list) and labels:
        props['#labels'] = labels
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {_ident(edge_table(dbname))} AS t '
                '(edge_id, edge_type, source_id, target_id, properties) '
                'VALUES (%s, %s, %s, %s, %s::jsonb) '
                'ON CONFLICT (edge_id) DO UPDATE SET '
                'edge_type = EXCLUDED.edge_type, source_id = EXCLUDED.source_id, '
                'target_id = EXCLUDED.target_id, '
                'properties = t.properties || EXCLUDED.properties, '
                'updated_at = CURRENT_TIMESTAMP',
                (edge_id, edge_type, source_id, target_id,
                 json.dumps(props, ensure_ascii=False)))


def add_entity(client: PgGraphClient, entity) -> None:
    properties = _split_properties(entity.properties,
                                   {'entity_id', 'entity_type'})
    try:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'INSERT INTO {_ident(vertex_table(client.dbname))} '
                    '(entity_id, entity_type, properties) VALUES (%s, %s, %s::jsonb)',
                    (entity.entity_id, entity.entity_type,
                     json.dumps(properties, ensure_ascii=False)))
    except Exception as error:                                     # noqa: BLE001
        raise GraphException('KG007', f'Failed to add entity: {error}') from error


def add_edge(client: PgGraphClient, edge) -> None:
    properties = _split_properties(
        edge.properties, {'edge_id', 'source_id', 'target_id', 'edge_type'})
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT 1 FROM {_ident(vertex_table(client.dbname))} '
                'WHERE entity_id = %s', (edge.source_id,))
            if cursor.fetchone() is None:
                raise GraphException('KG012', f'Source entity not found: {edge.source_id}')
            cursor.execute(
                f'SELECT 1 FROM {_ident(vertex_table(client.dbname))} '
                'WHERE entity_id = %s', (edge.target_id,))
            if cursor.fetchone() is None:
                raise GraphException('KG012', f'Target entity not found: {edge.target_id}')
            try:
                cursor.execute(
                    f'INSERT INTO {_ident(edge_table(client.dbname))} '
                    '(edge_id, edge_type, source_id, target_id, properties) '
                    'VALUES (%s, %s, %s, %s, %s::jsonb)',
                    (edge.edge_id, edge.edge_type, edge.source_id, edge.target_id,
                     json.dumps(properties, ensure_ascii=False)))
            except Exception as error:                             # noqa: BLE001
                raise GraphException('KG012', f'Failed to add edge: {error}') from error


def update_entity(client: PgGraphClient, entity_type: str, entity_id: str,
                  properties: dict) -> None:
    if not properties:
        raise GraphException('KG014', 'Properties cannot be empty')
    cleaned = _split_properties(properties, {'entity_id', 'entity_type'})
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {_ident(vertex_table(client.dbname))} SET '
                'properties = properties || %s::jsonb, updated_at = CURRENT_TIMESTAMP '
                'WHERE entity_id = %s',
                (json.dumps(cleaned, ensure_ascii=False), entity_id))
            if cursor.rowcount == 0:
                raise GraphException('KG014', f'{entity_type} {entity_id} not updated')


def update_edge(client: PgGraphClient, edge_type: str, edge_id: str,
                properties: dict) -> None:
    if not properties:
        raise GraphException('KG024', 'Properties cannot be empty')
    cleaned = _split_properties(
        properties, {'edge_id', 'source_id', 'target_id', 'edge_type'})
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {_ident(edge_table(client.dbname))} SET '
                'properties = properties || %s::jsonb, updated_at = CURRENT_TIMESTAMP '
                'WHERE edge_id = %s',
                (json.dumps(cleaned, ensure_ascii=False), edge_id))
            if cursor.rowcount == 0:
                raise GraphException('KG024', f'{edge_type} {edge_id} not updated')


def delete_entity(client: PgGraphClient, entity_type: str, entity_id: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {_ident(edge_table(client.dbname))} '
                'WHERE source_id = %s OR target_id = %s', (entity_id, entity_id))
            cursor.execute(
                f'DELETE FROM {_ident(vertex_table(client.dbname))} '
                'WHERE entity_id = %s', (entity_id,))
            if cursor.rowcount == 0:
                raise GraphException('KG017', f'Entity not deleted: {entity_id}')


def delete_edge(client: PgGraphClient, edge_type: str, edge_id: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {_ident(edge_table(client.dbname))} WHERE edge_id = %s',
                (edge_id,))
            if cursor.rowcount == 0:
                raise GraphException('KG027', f'Edge not deleted: {edge_id}')


# ----------------------------------------------------------------------
# 列表/批量删除（导出、回填、删文件）
# ----------------------------------------------------------------------


def list_all_vertices(client: PgGraphClient, page_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT {_VERTEX_SELECT} FROM {_ident(vertex_table(client.dbname))} '
                    'ORDER BY id LIMIT %s OFFSET %s', (page_size, offset))
                page = cursor.fetchall()
        rows.extend(_vertex_row(row) for row in page)
        if len(page) < page_size:
            return rows
        offset += page_size


def list_all_edges(client: PgGraphClient, page_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT {_edge_select(client.dbname)} FROM {_ident(edge_table(client.dbname))} AS e '
                    'ORDER BY e.id LIMIT %s OFFSET %s', (page_size, offset))
                page = cursor.fetchall()
        rows.extend(_edge_row(row) for row in page)
        if len(page) < page_size:
            return rows
        offset += page_size


def list_vertices_by_chunk_ids(client: PgGraphClient, chunk_ids: Iterable[str]) -> list[dict]:
    targets = {str(value) for value in chunk_ids if value}
    if not targets:
        return []
    matched = []
    for row in list_all_vertices(client):
        raw = row.get('chunk_id')
        if raw is None:
            continue
        parts = [part.strip() for part in str(raw).split(',') if part.strip()]
        if any(part in targets for part in parts):
            matched.append({'@class': row.get('@class'),
                            'entity_id': row.get('entity_id'),
                            'chunk_id': row.get('chunk_id')})
    return matched


def delete_entities_by_chunk_ids(client: PgGraphClient, chunk_ids: Iterable[str]) -> list[str]:
    deleted = []
    for row in list_vertices_by_chunk_ids(client, chunk_ids):
        try:
            delete_entity(client, str(row.get('@class')), str(row.get('entity_id')))
            deleted.append(str(row.get('entity_id')))
        except Exception as error:                                 # noqa: BLE001
            log.warning('failed to delete PG entity %s by chunk id: %s',
                        row.get('entity_id'), error)
    return deleted


# ----------------------------------------------------------------------
# 查询（graph/query 与图检索共用）
# ----------------------------------------------------------------------

_SAFE_KEY = __import__('re').compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_NUMERIC_OPS = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}


def _keyword_sql(keyword: Optional[str]) -> tuple[str, list]:
    """详情页搜索框的模糊匹配：实体 ID + **所有属性值**。

    为什么不写死 ``properties->>'name'``：属性名随 schema 变 —— 同一套图里
    「通用知识图谱算子」建出来的是 ``entity_name`` / ``entity_description``，
    另一个 schema 可能是 ``name`` / ``title``。写死某一个键会让搜索在另一半图上
    静默失效（实测：按「星辰人工智能科技（深圳）有限公司」搜，用 ``->>'name'``
    返回 0 条，而该实体就叫这个名字）。

    只比对**值**、不比键：直接 ``(properties)::text ILIKE`` 会让任何作为键名子串的
    关键字（如 ``name``）命中全表。``chunk_id`` 是系统字段（每个实体都带同一个
    UUID），不参与匹配。

    用 ``ILIKE`` 而不是 ``LIKE``：搜索框对大小写不做承诺（实测用户会输小写英文）。
    关键字里的 ``%`` / ``_`` 按字面量处理（用户输入不是通配符）。
    """
    text = (keyword or '').strip()
    if not text:
        return '', []
    escaped = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    pattern = f'%{escaped}%'
    return ("(COALESCE(e.entity_id, '') ILIKE %s"
            " OR EXISTS (SELECT 1 FROM jsonb_each_text(properties) AS kv(k, v)"
            "            WHERE kv.k <> 'chunk_id' AND kv.v ILIKE %s))",
            [pattern, pattern])


def _json_key(key: str) -> str:
    if not _SAFE_KEY.match(str(key)):
        raise ValueError(f'illegal property name: {key!r}')
    return f"properties->>'{key}'"


def _condition(key: str, value: Any, params: list) -> str:
    if not isinstance(value, dict):
        if isinstance(value, (list, tuple)):
            if not value:
                return 'FALSE'
            params.append(list(value))
            return f'{_json_key(key)} = ANY(%s)'
        if value is None:
            return f'{_json_key(key)} IS NULL'
        params.append(value)
        return f'{_json_key(key)} = %s'

    op = value.get('op')
    operand = value.get('value')
    if op in ('and', 'or'):
        if not isinstance(operand, list) or not operand:
            return 'FALSE'
        parts = [_condition(key, item, params) for item in operand]
        return '(' + f' {op.upper()} '.join(parts) + ')'
    if op == 'eq':
        params.append(operand)
        return f'{_json_key(key)} = %s'
    if op == 'ne':
        params.append(operand)
        return f'{_json_key(key)} <> %s'
    if op in _NUMERIC_OPS:
        params.append(operand)
        return f'({_json_key(key)})::numeric {_NUMERIC_OPS[op]} %s'
    if op == 'like':
        params.append(operand)
        return f'{_json_key(key)} LIKE %s'
    if op == 'in':
        if not isinstance(operand, (list, tuple)) or not operand:
            return 'FALSE'
        params.append(list(operand))
        return f'{_json_key(key)} = ANY(%s)'
    if op == 'between':
        if not isinstance(operand, (list, tuple)) or len(operand) != 2:
            return 'FALSE'
        params.extend([operand[0], operand[1]])
        return f'({_json_key(key)})::numeric BETWEEN %s AND %s'
    if op == 'contains':
        params.append(json.dumps([operand], ensure_ascii=False))
        return f"properties->'{key}' @> %s::jsonb"
    if op in ('contains_all', 'contains_any'):
        if not isinstance(operand, (list, tuple)) or not operand:
            return 'FALSE'
        if op == 'contains_all':
            params.append(json.dumps(list(operand), ensure_ascii=False))
            return f"properties->'{key}' @> %s::jsonb"
        params.append(list(operand))
        return (f"EXISTS (SELECT 1 FROM jsonb_array_elements_text("
                f"properties->'{key}') AS item WHERE item = ANY(%s))")
    return 'FALSE'


def _groups_sql(groups: list, type_key: str, type_column: str) -> tuple[str, list]:
    group_sql, params = [], []
    for item in groups or []:
        conditions = []
        types = item.get(type_key)
        if types:
            params.append(list(types))
            conditions.append(f'{type_column} = ANY(%s)')
        for key, value in (item.get('properties') or {}).items():
            built = _condition(key, value, params)
            if built != 'FALSE':
                conditions.append(built)
        if conditions:
            group_sql.append('(' + ' AND '.join(conditions) + ')')
    return (' OR '.join(group_sql), params)


def _parse_rid(cursor: Optional[str]) -> Optional[int]:
    if not cursor:
        return None
    text = str(cursor).strip().lstrip('#')
    try:
        return int(text.split(':', 1)[0])
    except (ValueError, IndexError):
        return None


def query_vertices(dbname: str, groups: list, limit: int, offset: int,
                   cursor: Optional[str] = None,
                   keyword: Optional[str] = None) -> list[dict]:
    """按类型/属性组查实体。

    ``keyword`` 为**跨字段模糊搜索**（名称 / 实体 ID / 描述），与 ``groups`` 是
    **AND** 关系 —— 详情页搜索框用它。以前这个框只在客户端过一遍已加载的实体
    （``performEntitySearch``），既不看 ID/描述，也搜不到分页之外的数据，
    点「查询」时 keyword 根本不在请求体里，于是「搜什么都是全量」。
    """
    where, params = _groups_sql(groups, 'entity_type', 'entity_type')
    sql = f'SELECT {_VERTEX_SELECT} FROM {_ident(vertex_table(dbname))} AS e'
    keyword_sql, keyword_params = _keyword_sql(keyword)
    if keyword_sql:
        conditions = [f'({where})'] if where else []
        conditions.append(keyword_sql)
        where = ' AND '.join(conditions)
        params.extend(keyword_params)
    if where:
        sql += f' WHERE ({where})'
    cursor_id = _parse_rid(cursor)
    if cursor_id is not None:
        sql += (' AND ' if where else ' WHERE ') + f'e.id > {cursor_id}'
    sql += ' ORDER BY e.id LIMIT %s OFFSET %s'
    params.extend([limit, 0 if cursor_id is not None else offset])
    with _connect() as conn:
        with conn.cursor() as cursor_obj:
            cursor_obj.execute(sql, params)
            return [_vertex_row(row) for row in cursor_obj.fetchall()]


def query_edges(dbname: str, groups: list, limit: int, offset: int,
                cursor: Optional[str] = None) -> list[dict]:
    where, params = _groups_sql(groups, 'edge_type', 'edge_type')
    sql = f'SELECT {_edge_select(dbname)} FROM {_ident(edge_table(dbname))} AS e'
    if where:
        sql += f' WHERE ({where})'
    cursor_id = _parse_rid(cursor)
    if cursor_id is not None:
        sql += (' AND ' if where else ' WHERE ') + f'e.id > {cursor_id}'
    sql += ' ORDER BY e.id LIMIT %s OFFSET %s'
    params.extend([limit, 0 if cursor_id is not None else offset])
    with _connect() as conn:
        with conn.cursor() as cursor_obj:
            cursor_obj.execute(sql, params)
            return [_edge_row(row) for row in cursor_obj.fetchall()]


def edges_between_entities(dbname: str, entity_ids: list[str]) -> list[dict]:
    if not entity_ids:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_edge_select(dbname)} FROM {_ident(edge_table(dbname))} AS e '
                'WHERE e.source_id = ANY(%s) AND e.target_id = ANY(%s) ORDER BY e.id',
                (entity_ids, entity_ids))
            return [_edge_row(row) for row in cur.fetchall()]


def vertices_by_entity_ids(dbname: str, entity_ids: list[str]) -> list[dict]:
    if not entity_ids:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_VERTEX_SELECT} FROM {_ident(vertex_table(dbname))} '
                'WHERE entity_id = ANY(%s) ORDER BY id', (entity_ids,))
            return [_vertex_row(row) for row in cur.fetchall()]


def vertices_by_rids(dbname: str, rids: list[str]) -> list[dict]:
    ids = [rid for rid in (_parse_rid(value) for value in rids) if rid is not None]
    if not ids:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_VERTEX_SELECT} FROM {_ident(vertex_table(dbname))} '
                'WHERE id = ANY(%s) ORDER BY id', (ids,))
            return [_vertex_row(row) for row in cur.fetchall()]


def resolve_entity_id_by_rid(dbname: str, rid: str) -> Optional[str]:
    row_id = _parse_rid(rid)
    if row_id is None:
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT entity_id FROM {_ident(vertex_table(dbname))} WHERE id = %s',
                (row_id,))
            row = cur.fetchone()
    return str(row[0]) if row else None


def start_entity_ids(dbname: str, filters: list) -> set[str]:
    ids: set[str] = set()
    for item in filters or []:
        value = (item.get('start_entity_properties') or {}).get('entity_id')
        if isinstance(value, (list, tuple)):
            ids.update(str(entry) for entry in value if entry is not None)
        elif value is not None:
            ids.add(str(value))
        rid = item.get('start_entity_rid')
        if rid:
            resolved = resolve_entity_id_by_rid(dbname, str(rid))
            if resolved:
                ids.add(resolved)
    groups = [
        {'entity_type': item.get('start_entity_type'),
         'properties': item.get('start_entity_properties') or {}}
        for item in (filters or [])
        if item.get('start_entity_type') or item.get('start_entity_properties')
    ]
    if groups:
        for row in query_vertices(dbname, groups, 10000, 0):
            ids.add(str(row.get('entity_id')))
    return ids


def _select_edge_ids(edge_levels: dict[int, int], *, limit: int, offset: int,
                     cursor_id: Optional[int],
                     prioritize_levels: bool) -> list[int]:
    """按 BFS 层级挑出要返回的边（纯函数，便于单测）。

    * 默认按 id 排序，保持图详情页 offset/cursor 分页语义不变。
    * ``prioritize_levels`` 且无 cursor/offset 时按层配额：先给每层
      ``limit // 层数`` 条，余量再按层序补。否则 level0 一多就会把 1000 条
      全吃光，2/3-hop 的深层边一条都进不来。
    * 有 cursor 时回落 id 序（分页语义）。
    """
    limit = max(0, limit)
    if cursor_id is not None:
        ids = sorted(edge_levels)
        return [edge_id for edge_id in ids if edge_id > cursor_id][:limit]

    ids = sorted(edge_levels)
    if prioritize_levels and offset == 0 and limit:
        by_level: dict[int, list[int]] = {}
        for edge_id in ids:
            by_level.setdefault(edge_levels[edge_id], []).append(edge_id)
        levels = sorted(by_level)
        quota = max(1, limit // max(1, len(levels)))
        selected: list[int] = []
        chosen: set[int] = set()
        for level in levels:
            for edge_id in by_level[level][:quota]:
                selected.append(edge_id)
                chosen.add(edge_id)
        if len(selected) < limit:
            for level in levels:
                for edge_id in by_level[level]:
                    if edge_id in chosen:
                        continue
                    selected.append(edge_id)
                    chosen.add(edge_id)
                    if len(selected) >= limit:
                        break
                if len(selected) >= limit:
                    break
        return selected[:limit]

    if prioritize_levels:
        ids.sort(key=lambda edge_id: (edge_levels[edge_id], edge_id))
    return ids[offset:offset + limit]


def subgraph(dbname: str, seed_ids: Optional[set[str]], depth: int,
             direction: str, edge_types: list[str], edge_properties: dict,
             vertex_groups: list, limit: int, offset: int,
             cursor: Optional[str] = None,
             prioritize_levels: bool = False) -> tuple[list[dict], list[dict]]:
    """BFS 子图：返回 ``(edge_rows, vertex_rows)``。

    边行带 ``out_entity_id``/``in_entity_id`` 两个临时列（与图存储查询一致，
    调用方取完会 pop 掉）。无种子时等价于「从所有顶点出发」，返回全部边。

    ``prioritize_levels=True``（检索路径）时：
    * 边按 BFS 层级排序后再截断，靠近种子的边优先保留；
    * **顶点只取种子 + 实际返回边的端点**，不要把 BFS 访问过但边被截断的
      顶点也塞进响应（否则 1000 条边能带出 3.8 万个孤立顶点，序列化 20s+，
      且这些顶点对 LLM 没有可用关系）。
    """
    etable = _ident(edge_table(dbname))
    vtable = _ident(vertex_table(dbname))
    # 与图存储的 ``_traverse_function`` 一致：未知方向按 both 处理。
    if direction not in ('out', 'in', 'both'):
        direction = 'both'
    visited: set[str] = set(seed_ids or [])
    frontier: set[str] = set(seed_ids or [])
    edge_levels: dict[int, int] = {}

    def edge_where(extra: str, params: list) -> str:
        clauses = [extra]
        if edge_types:
            clauses.append('edge_type = ANY(%s)')
            params.append(list(edge_types))
        for key, value in (edge_properties or {}).items():
            built = _condition(key, value, params)
            if built != 'FALSE':
                clauses.append(built)
        return ' AND '.join(clauses)

    with _connect() as conn:
        with conn.cursor() as cur:
            if not seed_ids:
                sql = f'SELECT {_edge_select(dbname)} FROM {etable} AS e'
                params: list = []
                where = edge_where('TRUE', params)
                cur.execute(sql + ' WHERE ' + where + ' ORDER BY id', params)
                edges = cur.fetchall()
                cursor_id = _parse_rid(cursor)
                if cursor_id is not None:
                    edges = [row for row in edges if row[5] > cursor_id]
                    offset = 0
                edges = edges[offset:offset + limit]
                cur.execute(f'SELECT {_VERTEX_SELECT} FROM {vtable} ORDER BY id')
                vertices = cur.fetchall()
            else:
                for _level in range(max(1, depth)):
                    if not frontier:
                        break
                    next_frontier: set[str] = set()
                    conds, params = [], []
                    if direction in ('out', 'both'):
                        conds.append('source_id = ANY(%s)')
                        params.append(list(frontier))
                    if direction in ('in', 'both'):
                        if direction == 'both':
                            conds = ['(source_id = ANY(%s) OR target_id = ANY(%s))']
                            params = [list(frontier), list(frontier)]
                        else:
                            conds.append('target_id = ANY(%s)')
                            params.append(list(frontier))
                    where = edge_where('(' + ' OR '.join(conds) + ')', params)
                    cur.execute(f'SELECT {_edge_select(dbname)} FROM {etable} AS e '
                                f'WHERE {where} ORDER BY e.id', params)
                    rows = cur.fetchall()
                    for row in rows:
                        edge_levels.setdefault(row[5], _level)
                        next_frontier.add(row[2])
                        next_frontier.add(row[3])
                    frontier = next_frontier - visited
                    visited |= next_frontier
                ids = _select_edge_ids(
                    edge_levels, limit=limit, offset=offset,
                    cursor_id=_parse_rid(cursor),
                    prioritize_levels=prioritize_levels)
                if not ids:
                    # 没有边但有种子的情况：返回种子顶点本身（语义一致）。
                    cur.execute(f'SELECT {_VERTEX_SELECT} FROM {vtable} '
                                'WHERE entity_id = ANY(%s) ORDER BY id',
                                (list(seed_ids),))
                    return [], [_vertex_row(row) for row in cur.fetchall()]
                cur.execute(f'SELECT {_edge_select(dbname)} FROM {etable} AS e '
                            'WHERE e.id = ANY(%s) ORDER BY e.id', (ids,))
                rows = cur.fetchall()
                order = {edge_id: pos for pos, edge_id in enumerate(ids)}
                rows.sort(key=lambda row: order.get(row[5], 0))
                edges = rows
                # 只返回种子 + 实际返回边的端点；visited 里被截断的顶点不再带出。
                all_ids = set(seed_ids)
                all_ids.update(row[2] for row in edges if row[2])
                all_ids.update(row[3] for row in edges if row[3])
                cur.execute(f'SELECT {_VERTEX_SELECT} FROM {vtable} '
                            'WHERE entity_id = ANY(%s) ORDER BY id', (list(all_ids),))
                vertices = cur.fetchall()

    shaped_edges = []
    for row in edges:
        shaped = _edge_row(row)
        shaped['out_entity_id'] = row[2]
        shaped['in_entity_id'] = row[3]
        shaped_edges.append(shaped)
    shaped_vertices = [_vertex_row(row) for row in vertices]

    # 路径顶点过滤：只保留两端都满足（或至少一端满足）过滤的边 ——
    # 图存储的语义是「沿途顶点满足」，这里按端点做保守过滤。
    if vertex_groups:
        allowed = {row.get('entity_id') for row in
                   vertices_by_matching_groups(dbname, vertex_groups)}
        shaped_edges = [edge for edge in shaped_edges
                        if edge['source_id'] in allowed or edge['target_id'] in allowed]

    return shaped_edges, shaped_vertices


def vertices_by_matching_groups(dbname: str, groups: list) -> list[dict]:
    return query_vertices(dbname, groups, 100000, 0)


def entity_names(dbname: str, limit: int = 100000) -> list[tuple[str, str]]:
    """返回 ``(entity_id, name)``，供词面实体提及匹配建 trie。

    ``name`` 取 ``properties->>'name'``；没有该属性时回落到 entity_id。
    大图最多取 ``limit`` 条（默认 10 万），避免把进程内存打爆。
    """
    vtable = _ident(vertex_table(dbname))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT entity_id, properties->>'name' FROM {vtable} "
                'ORDER BY id LIMIT %s', (max(1, int(limit)),))
            return [(str(row[0]), str(row[1] or row[0]))
                    for row in cur.fetchall() if row[0]]


def present_ids(dbname: str, id_field: str, ids: Iterable[str]) -> set[str]:
    """导入后回查：返回库里实际存在的 id 集合（``entity_id``/``edge_id``）。"""
    if id_field not in ('entity_id', 'edge_id'):
        raise ValueError(f'illegal id field: {id_field}')
    values = [str(value) for value in ids if value]
    if not values:
        return set()
    table = vertex_table(dbname) if id_field == 'entity_id' else edge_table(dbname)
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT {id_field} FROM {_ident(table)} WHERE {id_field} = ANY(%s)',
                (values,))
            return {str(row[0]) for row in cursor.fetchall()}


def delete_edges_by_entity(client: PgGraphClient, entity_type: str, entity_id: str) -> int:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {_ident(edge_table(client.dbname))} '
                'WHERE source_id = %s OR target_id = %s', (entity_id, entity_id))
            return cursor.rowcount


# ----------------------------------------------------------------------
# 身份辅助
# ----------------------------------------------------------------------


def graph_db_name(kb_id: str) -> str:
    return f'{GRAPH_TABLE_PREFIX}{kb_id}'


def graph_db_name_for_query(kb_id: str) -> str:
    """查询 API 的库名规则：已带前缀就原样用，不重复拼接。"""
    if kb_id.startswith(GRAPH_TABLE_PREFIX):
        return kb_id
    return GRAPH_TABLE_PREFIX + kb_id


def extract_entity_id_from_rid(value: Any) -> Optional[str]:
    """PG 行没有 RID：``out``/``in`` 已经是 entity_id，原样返回。"""
    if value is None:
        return None
    text = str(value)
    return text or None


def extract_entity_type_from_id(entity_id: Optional[str]) -> Optional[str]:
    if not entity_id or '_' not in str(entity_id):
        return None
    return str(entity_id).split('_', 1)[0]
