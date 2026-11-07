"""图谱库的向量索引与切片表（``graph_<uuid>_vector`` / ``graph_<uuid>_chunk``）。

## 写入的链路

导入图数据后要写三类数据（实体/边向量、切片、切片向量）。缺任何一类，
图谱检索（``core/graph/service/graph_query_service.py``）查的
``graph_<uuid>_vector`` 表就不完整，接口会 ``code: 0`` + 空结果、**静默失败**：

| 步骤 | 写什么 | 谁读 |
|---|---|---|
| 实体/边向量化 | ``graph_<uuid>_vector`` 的 ``key_type='entity'/'edge'`` 行 | ``_build_retrieve_sql`` |
| 切片落表 | ``graph_<uuid>_chunk``（列与文档库切片表相同） | ``_query_chunks_by_ids`` |
| 切片向量化 | ``_vector`` 的 ``key_type='chunk'`` 行 | ``_retrieve_seed_ids`` |

## 检索端对表结构的硬要求（别改）

* ``_build_retrieve_sql`` SELECT ``key_id`` / ``embedding``，WHERE ``key_type``、
  ``labels && ARRAY[...]`` —— 所以列必须有 ``key_id / key_type / labels / embedding``；
* 边身份：``key_id = edge_id``、端点落 ``source_id``/``target_id`` 列；
  检索端只读端点列，不拆 ``key_id``；
* 切片表的列与 ``ddl.create_chunk_table`` 完全一致
  （``_query_chunks_by_ids`` 用 ``SELECT *`` 再按键取名）。

## 文本怎么拼（影响召回，不影响正确性）

文本用**确定性的键值行**组装：
实体 = ``entity_type`` + properties；边 = ``edge_type`` + 两个端点 + properties；
切片 = ``content_expand`` 原文。向量化的目标只是「让问题和实体/边语义相近」，
真正的展示数据仍从图存储取。
"""

from __future__ import annotations

import json
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Optional

from infrastructure.db.kb import connection
from infrastructure.db import ddl
from infrastructure.db.identifiers import SCHEMA, validate_identifier
from infrastructure.logging.logutil import log
from shared.chunk_schema.vector import to_vector_literal_fast

#: 一次 HTTP 请求向量化的条数（批量导入 128 比 64 吞吐高约 10%）
EMBED_BATCH_SIZE = 128

#: 同时向模型网关发起的 embedding 请求数。16 路、128 条/批约 2.2k 条/s；
#: 超过 16 路不再增长（32 路约 2.1k 条/s）。可用环境变量覆盖。
EMBED_CONCURRENCY = max(1, min(32, int(os.getenv('GRAPH_INDEX_EMBED_CONCURRENCY', '16') or '16')))

#: 在途 embedding 批次数 = 并发数 × 该系数（给 DB 写入留出重叠窗口）
EMBED_WINDOW_FACTOR = 2

#: 空表批量装载时的并行写入连接数（无唯一索引，批次互不重叠，可安全并发）
WRITE_CONCURRENCY = max(1, min(8, int(
    os.getenv('GRAPH_INDEX_WRITE_CONCURRENCY', '4') or '4')))

#: HNSW 建索引时给 pgvector 用的内存；只在建索引的那个事务里 SET LOCAL。
_MAINTENANCE_WORK_MEM = os.getenv('GRAPH_INDEX_MAINTENANCE_WORK_MEM', '256MB')
if not re.fullmatch(r'\d+(MB|GB)', _MAINTENANCE_WORK_MEM or ''):
    _MAINTENANCE_WORK_MEM = '256MB'

#: 并行建 HNSW 的 worker 数。pgvector 0.6+ 支持并行建 HNSW；/dev/shm 不够时
#: 代码会自动回落到 0（串行），不会让导入失败。
_PARALLEL_WORKERS = max(0, min(8, int(
    os.getenv('GRAPH_INDEX_PARALLEL_WORKERS', '4') or '4')))

#: 一次 INSERT 的行数
WRITE_BATCH_SIZE = 500

KEY_TYPE_ENTITY = 'entity'
KEY_TYPE_EDGE = 'edge'
KEY_TYPE_CHUNK = 'chunk'

ENTITIES_ENTRY = 'entities.jsonl'
EDGES_ENTRY = 'edges.jsonl'
CHUNKS_ENTRY = 'document_chunk.jsonl'


class GraphIndexError(Exception):
    """索引构建失败（zip 损坏 / 网关失败 / 维度不符）—— 调用方降级为「部分成功」。"""


# ----------------------------------------------------------------------
# 文本与键（纯函数，单测直接钉）
# ----------------------------------------------------------------------


def _properties_text(properties: Any) -> str:
    if not isinstance(properties, dict):
        return ''
    return '\n'.join(
        f'{name}: {value}'
        for name, value in properties.items()
        if value is not None and str(value).strip())


def entity_text(record: dict) -> str:
    """实体向量化文本：``entity_type`` + 属性键值行（两者都没有 → 空串，调用方跳过）。"""
    entity_type = str(record.get('entity_type') or '').strip()
    lines = [f'entity_type: {entity_type}'] if entity_type else []
    body = _properties_text(record.get('properties'))
    if body:
        lines.append(body)
    return '\n'.join(lines)


def edge_text(record: dict) -> str:
    """边向量化文本：``edge_type`` + 两端 + 属性键值行（全空 → 空串）。"""
    lines = []
    for field in ('edge_type', 'source_id', 'target_id'):
        value = str(record.get(field) or '').strip()
        if value:
            lines.append(f'{field}: {value}')
    body = _properties_text(record.get('properties'))
    if body:
        lines.append(body)
    return '\n'.join(lines)


def chunk_text(record: dict) -> str:
    """切片向量化文本：``content_expand``（没有就退回落 ``text``）。"""
    text = record.get('content_expand')
    if text is None or not str(text).strip():
        text = record.get('text')
    return str(text or '').strip()


def entity_key_id(record: dict) -> str:
    return str(record.get('entity_id') or '').strip()


def edge_key_id(record: dict) -> str:
    """边的业务身份：``edge_id``（平行边各占一行，不会在唯一索引上相撞）。"""
    return str(record.get('edge_id') or '').strip()


def chunk_key_id(record: dict) -> str:
    return str(record.get('id') or '').strip()


def _labels(record: dict) -> list[str]:
    labels = record.get('labels')
    if not isinstance(labels, list):
        return []
    return [str(label) for label in labels if label is not None and str(label).strip()]


# ----------------------------------------------------------------------
# 建表
# ----------------------------------------------------------------------


def vector_table(base: str) -> str:
    return f'{base}_vector'


def chunk_table(base: str) -> str:
    return f'{base}_chunk'


def ensure_vector_table(base: str, dimension: int | None = None, *,
                        with_hnsw: bool = True,
                        with_secondary_indexes: bool = True) -> None:
    """建 ``graph_<uuid>_vector``（幂等）。

    列按检索端 SQL 反推：``key_id`` / ``key_type`` / ``labels`` / ``embedding``，
    另加 ``key``（落原文，排障用）。``key_type + key_id`` 唯一 —— 重复导入按它 upsert。
    ``embedding`` 必须带维度，否则 pgvector 无法建 HNSW 索引。

    批量导入时用两个开关把索引维护从「逐行」改成「导完一次性建」：

    * ``with_secondary_indexes=False`` —— 删掉唯一/端点 btree（空表直接不建），
      行插入不再每行维护索引；导完由 :func:`ensure_vector_indexes` 一次建好。
    * ``with_hnsw=False`` —— 只删 HNSW，保留唯一索引供 ``ON CONFLICT`` 使用。

    默认值保持「在线索引」，增量写入（抽图/手工编辑）行为不变。
    """
    table = vector_table(base)
    validate_identifier(table)
    dim = int(dimension or ddl.DEFAULT_VECTOR_DIMENSION)
    if dim <= 0:
        raise ValueError(f'illegal vector dimension: {dimension!r}')
    hnsw = with_hnsw and dim <= ddl.HNSW_MAX_DIMENSIONS
    if with_hnsw and not hnsw:
        log.warning('%s dimension %s exceeds HNSW limit %s; skip HNSW (exact scan)',
                    table, dim, ddl.HNSW_MAX_DIMENSIONS)
    indexes = _index_statements(table, with_hnsw=hnsw,
                                with_secondary_indexes=with_secondary_indexes)
    ddl_sql = f'''
    CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$;
    CREATE TABLE IF NOT EXISTS {SCHEMA}.{table} (
        id INT8 GENERATED BY DEFAULT AS IDENTITY,
        key_id VARCHAR NOT NULL,
        key_type VARCHAR(16) NOT NULL,
        "key" TEXT NULL,
        labels TEXT[] NULL,
        embedding vector({dim}) NULL,
        -- 边身份：key_id = edge_id，端点单独落列，检索/删除不再拆 key_id。
        edge_id VARCHAR(255) NULL,
        source_id VARCHAR(255) NULL,
        target_id VARCHAR(255) NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT {table}_pkey PRIMARY KEY (id)
    );
    {indexes};
    CREATE OR REPLACE TRIGGER {table}_set_updated_at
        BEFORE UPDATE ON {SCHEMA}.{table}
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    '''
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(ddl_sql)


def ensure_vector_indexes(base: str, dimension: int | None = None) -> None:
    """批量导入结束后一次性建齐所有索引（含 HNSW）。

    HNSW 建索引在**一个事务**里完成，``SET LOCAL maintenance_work_mem`` 只影响
    这一次；pgvector 建图比逐行插入快一个数量级，且不会产生逐行随机 I/O。

    优先并行建（pgvector 0.6+ 支持）；容器 ``/dev/shm`` 太小导致 DSM 申请失败时
    自动回落串行——报错信息里是 "No space left on device"，不能让它把导入判死。
    """
    dim = int(dimension or ddl.DEFAULT_VECTOR_DIMENSION)
    with_hnsw = dim <= ddl.HNSW_MAX_DIMENSIONS
    if not with_hnsw:
        log.warning('%s dimension %s exceeds HNSW limit %s; build secondary indexes only',
                    vector_table(base), dim, ddl.HNSW_MAX_DIMENSIONS)
    try:
        _create_indexes(base, parallel=_PARALLEL_WORKERS, with_hnsw=with_hnsw)
    except Exception as error:                                     # noqa: BLE001
        message = str(error)
        if 'shared memory' not in message and 'No space left on device' not in message:
            raise
        log.warning('[graph-index] parallel index build failed (%s); retrying serially',
                    message)
        _create_indexes(base, parallel=0, with_hnsw=with_hnsw)


def _create_indexes(base: str, *, parallel: int, with_hnsw: bool = True) -> None:
    table = vector_table(base)
    validate_identifier(table)
    statements = _index_statements(table, with_hnsw=with_hnsw,
                                   with_secondary_indexes=True)
    statements = [statement for statement in statements.split(';') if statement.strip()]
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SET LOCAL maintenance_work_mem = '{_MAINTENANCE_WORK_MEM}'")
            # 部署默认 statement_timeout=30s，HNSW 建 178k×1024 会超时被取消。
            cursor.execute('SET LOCAL statement_timeout = 0')
            cursor.execute(f'SET LOCAL max_parallel_maintenance_workers = {int(parallel)}')
            log.info('[graph-index] building indexes for %s (maintenance_work_mem=%s, '
                     'parallel_workers=%s)', table, _MAINTENANCE_WORK_MEM, parallel)
            for statement in statements:
                cursor.execute(statement)


def _index_statements(table: str, *, with_hnsw: bool,
                      with_secondary_indexes: bool) -> str:
    """建/删索引的 SQL 片段；``DROP`` 用在批量导入前的「卸索引」阶段。"""
    statements: list[str] = []
    secondary = (
        (f'{table}_type_key_uidx',
         f'CREATE UNIQUE INDEX IF NOT EXISTS {table}_type_key_uidx '
         f'ON {SCHEMA}.{table} (key_type, key_id)'),
        (f'{table}_edge_source_idx',
         f'CREATE INDEX IF NOT EXISTS {table}_edge_source_idx '
         f'ON {SCHEMA}.{table} (source_id) WHERE key_type = \'edge\''),
        (f'{table}_edge_target_idx',
         f'CREATE INDEX IF NOT EXISTS {table}_edge_target_idx '
         f'ON {SCHEMA}.{table} (target_id) WHERE key_type = \'edge\''),
    )
    for name, create_sql in secondary:
        statements.append(create_sql if with_secondary_indexes
                          else f'DROP INDEX IF EXISTS {SCHEMA}.{name}')
    # 按 key_type 建 partial HNSW：检索 SQL 恒带 key_type 过滤，单一全局索引
    # 会把 ef_search 的候选先给 entity/edge/chunk 混合再过滤，top-10 实体召回
    # 只有 48–58%（ef_search=40）；partial 索引让过滤条件下推到索引本身。
    hnsw_indexes = (
        (f'{table}_entity_hnsw', "key_type = 'entity'"),
        (f'{table}_edge_hnsw', "key_type = 'edge'"),
        (f'{table}_chunk_hnsw', "key_type = 'chunk'"),
    )
    if with_hnsw:
        for name, predicate in hnsw_indexes:
            statements.append(
                f'CREATE INDEX IF NOT EXISTS {name} ON {SCHEMA}.{table} '
                f'USING hnsw (embedding vector_cosine_ops) WHERE {predicate}')
    else:
        for name, _predicate in hnsw_indexes:
            statements.append(f'DROP INDEX IF EXISTS {SCHEMA}.{name}')
    return ';\n'.join(statements)


def ensure_chunk_table(base: str) -> None:
    """建 ``graph_<uuid>_chunk``（图谱契约列；已存在则跳过）。"""
    table = chunk_table(base)
    validate_identifier(table)
    if not ddl.table_exists(table):
        ddl.create_graph_chunk_table(table)


# ----------------------------------------------------------------------
# 写向量
# ----------------------------------------------------------------------


def upsert_vectors(base: str, key_type: str, rows: Iterable[tuple], *,
                   bulk: bool = False, on_conflict: bool = True) -> int:
    """按 ``(key_type,key_id)`` 写入；一条 SQL 插一整批，不再逐行 execute。

    ``rows`` 支持两种形状：

    * ``(key_id, key, labels, embedding)`` —— 实体/切片；
    * ``(key_id, key, labels, embedding, edge_id, source_id, target_id)`` —— 边行。

    边的端点单独落列（``source_id``/``target_id``），检索/删除不再拆 ``key_id``。

    :param bulk: 批量导入模式：事务级 ``synchronous_commit=off``，避免每批 fsync。
    :param on_conflict: ``False`` 时用于**空表批量装载**（索引已提前卸掉），
        不生成 ``ON CONFLICT``；调用方保证 key_id 已去重。
    """
    table = vector_table(base)
    validate_identifier(table)
    payload = []
    for row in rows:
        key_id, key, labels, embedding = row[:4]
        if not key_id:
            continue
        edge_id, source_id, target_id = (list(row[4:7]) + [None, None, None])[:3]
        payload.append((key_id, key_type, key, labels or None, embedding,
                        edge_id, source_id, target_id))
    if not payload:
        return 0
    columns = ('(key_id, key_type, "key", labels, embedding, edge_id, '
               'source_id, target_id)')
    conflict = ''
    if on_conflict:
        conflict = (
            ' ON CONFLICT (key_type, key_id) DO UPDATE SET '
            '"key" = EXCLUDED."key", labels = EXCLUDED.labels, '
            'embedding = EXCLUDED.embedding, edge_id = EXCLUDED.edge_id, '
            'source_id = EXCLUDED.source_id, target_id = EXCLUDED.target_id')
    with connection() as conn:
        with conn.cursor() as cursor:
            if bulk:
                cursor.execute('SET LOCAL synchronous_commit = off')
            for start in range(0, len(payload), WRITE_BATCH_SIZE):
                chunk = payload[start:start + WRITE_BATCH_SIZE]
                values = ','.join(['(%s, %s, %s, %s, %s::vector, %s, %s, %s)'] * len(chunk))
                sql = (f'INSERT INTO {SCHEMA}.{table} {columns} VALUES {values}{conflict}')
                cursor.execute(sql, [value for row in chunk for value in row])
    return len(payload)


# ----------------------------------------------------------------------
# 写切片
# ----------------------------------------------------------------------


def delete_chunks_by_sources(base: str, sources: Iterable[str]) -> int:
    """删切片行，并清掉它们在 ``_vector`` 里的 chunk 向量。

    文档库没有 ``_vector`` 表 → 只删切片行（与 ``ddl.delete_chunks_by_source`` 等价）；
    图谱库两样都删，否则 ``_vector`` 会留下指向已删切片的 ``key_id``。
    """
    values = [str(source) for source in sources if source]
    if not values:
        return 0
    table = chunk_table(base)
    if not ddl.table_exists(table):
        return 0
    chunk_ids = _select_chunk_ids(table, values)
    deleted = ddl.delete_chunks_by_source(table, values)
    vector = vector_table(base)
    if chunk_ids and ddl.table_exists(vector):
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'DELETE FROM {SCHEMA}.{vector} '
                    "WHERE key_type = %s AND key_id = ANY(%s)", (KEY_TYPE_CHUNK, chunk_ids))
    return deleted


def _select_chunk_ids(table: str, sources: list[str]) -> list[str]:
    validate_identifier(table)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT id FROM {SCHEMA}.{table} WHERE source = ANY(%s)', (sources,))
            return [row[0] for row in cursor.fetchall() if row[0]]


def chunk_ids_for_sources(base: str, sources: Iterable[str]) -> list[str]:
    """取这些 source（文件名）在切片表里的 id 集合（删文件前调用）。

    表不存在（老图谱库）返回空列表。
    """
    values = [str(source) for source in sources if source]
    if not values:
        return []
    table = chunk_table(base)
    if not ddl.table_exists(table):
        return []
    return _select_chunk_ids(table, values)


def delete_vector_keys(base: str, key_type: str, key_ids: Iterable[str]) -> int:
    """按 ``(key_type, key_id)`` 批量删 ``_vector`` 行；表不存在返回 0。"""
    ids = [str(key_id) for key_id in key_ids if key_id]
    if not ids:
        return 0
    table = vector_table(base)
    if not ddl.table_exists(table):
        return 0
    validate_identifier(table)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {SCHEMA}.{table} '
                'WHERE key_type = %s AND key_id = ANY(%s)', (key_type, ids))
            return cursor.rowcount


def _delete_edge_vectors_touching(base: str, entity_ids: set[str]) -> int:
    """删掉端点命中 ``entity_ids`` 的边向量（按 ``source_id``/``target_id`` 列判定）。"""
    if not entity_ids:
        return 0
    table = vector_table(base)
    if not ddl.table_exists(table):
        return 0
    validate_identifier(table)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT key_id, source_id, target_id FROM {SCHEMA}.{table} '
                'WHERE key_type = %s', (KEY_TYPE_EDGE,))
            rows = cursor.fetchall() or []
    victims = []
    for key_id, source_id, target_id in rows:
        hit = (str(source_id) in entity_ids if source_id else False) or \
              (str(target_id) in entity_ids if target_id else False)
        if hit and key_id:
            victims.append(key_id)
    return delete_vector_keys(base, KEY_TYPE_EDGE, victims)


def delete_edge_vectors_touching(base: str, entity_ids: Iterable[str]) -> int:
    """公开包装：删端点命中 ``entity_ids`` 的边向量（手工删实体时用）。"""
    return _delete_edge_vectors_touching(base, {str(value) for value in entity_ids if value})


def delete_source_graph_data(base: str, kbase_id: str,
                             chunk_ids: Iterable[str]) -> dict:
    """删文件时同步清图存储实体/边与 ``_vector`` 行。

    只删 ``graph_<uuid>_chunk`` 与 chunk 向量会遗漏图存储里的实体/边及其向量，
    已删文件抽取出的知识仍可被检索。

    顺序：先删图实体（连带边），拿到实际删掉的 entity_id 后再清 PG：
    ``entity`` 行按这些 id 删，``edge`` 行按端点命中删，``chunk`` 行按传入的
    chunk id 删。图存储删除失败会抛出（文件删除整体失败、可重试），
    不静默跳过。
    """
    ids = [str(chunk_id) for chunk_id in chunk_ids if chunk_id]
    if not ids:
        return {'entities': 0, 'edges': 0, 'chunks': 0}

    from graph.repository import graph_pg

    client = graph_pg.new_client(graph_pg.graph_db_name(str(kbase_id)))
    deleted_entity_ids = graph_pg.delete_entities_by_chunk_ids(client, ids)
    entity_set = set(deleted_entity_ids)

    entities = delete_vector_keys(base, KEY_TYPE_ENTITY, deleted_entity_ids)
    edges = _delete_edge_vectors_touching(base, entity_set)
    chunks = delete_vector_keys(base, KEY_TYPE_CHUNK, ids)
    log.info('[graph-index] purge base=%s chunks=%s entities=%s edges=%s',
             base, chunks, entities, edges)
    return {'entities': entities, 'edges': edges, 'chunks': chunks}


def replace_chunks(base: str, kbase_id: str, records: list[dict]) -> int:
    """按 ``source`` 覆盖写切片行（先删同源旧行，再插）。

    与文档库的 ``deleteChunksBySource`` 同一套幂等语义：重复导入同一批文件
    不会产生重复切片。
    """
    if not records:
        return 0
    table = chunk_table(base)
    validate_identifier(table)
    sources = sorted({str(record.get('source')) for record in records
                      if record.get('source')})
    sql = (
        f'INSERT INTO {SCHEMA}.{table} '
        '(id, kb_id, source, chunk_order, spilt_type, text, label, table_name, table_id, '
        ' chunk_index, content_expand, chunk_id, type, created_by, updated_by) '
        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '
        ' %s, %s, %s, %s, %s, %s) '
        'ON CONFLICT (id) DO NOTHING'
    )
    payload = []
    for record in records:
        chunk_id = chunk_key_id(record)
        if not chunk_id:
            continue
        payload.append((
            chunk_id,
            kbase_id,
            record.get('source'),
            record.get('chunk_id'),
            'system',
            chunk_text(record),
            record.get('label'),
            record.get('table_name'),
            record.get('table_id'),
            record.get('chunk_index'),
            record.get('content_expand'),
            record.get('chunk_id'),
            record.get('type'),
            record.get('create_user'),
            record.get('update_user'),
        ))
    if not payload:
        return 0
    with connection() as conn:
        with conn.cursor() as cursor:
            if sources:
                cursor.execute(
                    f'DELETE FROM {SCHEMA}.{table} WHERE source = ANY(%s)', (sources,))
            for start in range(0, len(payload), WRITE_BATCH_SIZE):
                cursor.executemany(sql, payload[start:start + WRITE_BATCH_SIZE])
    return len(payload)


# ----------------------------------------------------------------------
# zip 读取
# ----------------------------------------------------------------------


def read_jsonl(zip_path: str, entry_name: str) -> list[dict]:
    """读 zip 里的 JSONL 条目；条目不存在 → 空列表；坏行跳过并计数（不抛）。"""
    rows: list[dict] = []
    bad = 0
    try:
        with zipfile.ZipFile(zip_path) as archive:
            if entry_name not in archive.namelist():
                log.info('[graph-index] %s not present in zip, treated as empty', entry_name)
                return []
            with archive.open(entry_name) as handle:
                for line_no, raw in enumerate(handle, start=1):
                    line = raw.decode('utf-8').strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except ValueError:
                        bad += 1
                        log.warning('[graph-index] %s:%s invalid JSON, skipped',
                                    entry_name, line_no)
                        continue
                    if isinstance(parsed, dict):
                        rows.append(parsed)
                    else:
                        bad += 1
    except zipfile.BadZipFile as error:
        raise GraphIndexError(f'Invalid zip: {error}') from error
    if bad:
        log.warning('[graph-index] %s: %s bad line(s) skipped', entry_name, bad)
    return rows


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------


def _allowed(index: Optional[dict], type_name, item_id) -> bool:
    """``index`` 为 ``None`` 表示不过滤；否则按 ``{type: {id, ...}}`` 精确匹配。"""
    if index is None:
        return True
    if type_name is None or item_id is None:
        return False
    return str(item_id) in index.get(str(type_name), set())


def _entity_context(edges: list[dict], limit: int = 8) -> dict[str, str]:
    """``entity_id -> 'Rel: neighbor; ...'``（一跳邻居，最多 ``limit`` 条）。"""
    neighbors: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        source = str(edge.get('source_id') or '').strip()
        target = str(edge.get('target_id') or '').strip()
        relation = str(edge.get('edge_type') or '').strip()
        if not source or not target or not relation:
            continue
        neighbors.setdefault(source, []).append((relation, target))
        neighbors.setdefault(target, []).append((relation, source))
    return {
        entity_id: '; '.join(f'{relation}: {neighbor}'
                             for relation, neighbor in relations[:limit])
        for entity_id, relations in neighbors.items()
    }


def build_index(base: str, kbase_id: str, zip_path: str,
                embedding_model: Optional[str], embed_many,
                entity_ids: Optional[dict] = None,
                edge_ids: Optional[dict] = None,
                dimension: Optional[int] = None, *,
                bulk: bool = False,
                progress_cb: Optional[Callable[[int], None]] = None) -> dict:
    """把 zip 里的实体/边/切片写进向量表与切片表。返回统计。

    :param base: 动态表基名（``kb_kbase.table_name``，形如 ``graph_<uuid>``）
    :param kbase_id: 业务 id（写 ``chunk.kb_id``）
    :param embed_many: ``model_gateway.embed_many``（注入以便单测）
    :param entity_ids: ``{entity_type: {entity_id}}``；传入时只索引**导入成功**的实体
    :param edge_ids: ``{edge_type: {edge_id}}``；同上
    :param bulk: 批量导入模式。空表时卸掉全部二级索引 → 多行插入 → 导完一次建齐；
        非空表时只卸 HNSW、保留唯一索引做 ``ON CONFLICT``。
    :param progress_cb: 进度回调（0–100），每完成约 5% 调一次；用于回写导入任务。
    """
    fast_load = bulk and _vector_table_empty(base)
    ensure_vector_table(base, dimension,
                        with_hnsw=not bulk,
                        with_secondary_indexes=not fast_load)

    entities = read_jsonl(zip_path, ENTITIES_ENTRY)
    edges = read_jsonl(zip_path, EDGES_ENTRY)
    chunks = read_jsonl(zip_path, CHUNKS_ENTRY)

    stats = {'entities': 0, 'edges': 0, 'chunks': 0, 'chunk_rows': 0,
             'skipped': 0, 'collisions': 0}
    if entity_ids is not None:
        kept = [record for record in entities
                if _allowed(entity_ids, record.get('entity_type'), entity_key_id(record))]
        stats['skipped'] += len(entities) - len(kept)
        entities = kept
    if edge_ids is not None:
        kept = [record for record in edges
                if _allowed(edge_ids, record.get('edge_type'), record.get('edge_id'))]
        stats['skipped'] += len(edges) - len(kept)
        edges = kept

    # 实体向量文本加入一跳邻居上下文：问题不提实体名、只描述其关系/邻居时，
    # 仍能靠邻居名与关系词召回该实体（MetaQA 掩名实验 context 76% vs name-only 0%）。
    context = _entity_context(edges)

    def entity_text_with_context(record: dict) -> str:
        base = entity_text(record)
        extra = context.get(entity_key_id(record), '')
        return f'{base}\nrelations: {extra}' if extra else base

    total_records = len(entities) + len(edges) + len(chunks)
    done_by_type: dict[str, int] = {}

    def on_batch(key_type: str, done: int, _total: int) -> None:
        if not progress_cb:
            return
        done_by_type[key_type] = done
        cap = 95 if bulk else 100
        percent = int(cap * sum(done_by_type.values()) / total_records) \
            if total_records else 0
        progress_cb(min(cap, percent))

    common = dict(progress_cb=on_batch, bulk=bulk, fast_load=fast_load)
    stats['entities'] = _embed_and_write(
        base, KEY_TYPE_ENTITY, entities, entity_key_id, entity_text_with_context,
        embedding_model, embed_many, stats,
        # 抽取算子不产 labels；默认按类型打标，否则请求带 labels 时恒不匹配。
        label_fn=lambda record: ([str(record['entity_type'])]
                                 if record.get('entity_type') else []),
        **common)
    stats['edges'] = _embed_and_write(
        base, KEY_TYPE_EDGE, edges, edge_key_id, edge_text,
        embedding_model, embed_many, stats,
        label_fn=lambda record: ([str(record['edge_type'])]
                                 if record.get('edge_type') else []),
        **common)

    if chunks:
        ensure_chunk_table(base)
        stats['chunk_rows'] = replace_chunks(base, kbase_id, chunks)
        stats['chunks'] = _embed_and_write(
            base, KEY_TYPE_CHUNK, chunks, chunk_key_id, chunk_text,
            embedding_model, embed_many, stats, **common)

    if bulk:
        if progress_cb:
            progress_cb(95)
        started = time.perf_counter()
        ensure_vector_indexes(base, dimension)
        log.info('[graph-index] base=%s indexes built in %.1fs',
                 base, time.perf_counter() - started)
        if progress_cb:
            progress_cb(100)

    log.info('[graph-index] base=%s entities=%s edges=%s chunk_rows=%s chunk_vectors=%s '
             'skipped=%s collisions=%s', base, stats['entities'], stats['edges'],
             stats['chunk_rows'], stats['chunks'], stats['skipped'], stats['collisions'])
    return stats


def _vector_table_empty(base: str) -> bool:
    """空表（或表还不存在）才走「卸索引 → 装载 → 一次建索引」的快速路径。"""
    table = vector_table(base)
    validate_identifier(table)
    if not ddl.table_exists(table):
        return True
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT 1 FROM {SCHEMA}.{table} LIMIT 1')
            return cursor.fetchone() is None


def _embed_and_format(embed_many, texts: list[str], embedding_model) -> list[str]:
    """在 embedding 线程里顺手格式化 pgvector 文本字面量。

    直接把 ``list[float]`` 交给 psycopg2 会在 ``cursor.execute`` 里逐值做数组
    adaptation —— 实测 128×1024 维一批要 ~400ms，把写入线程卡成 ~300 行/s。
    预格式化成 ``[a,b,c]`` 后同一批只要 ~50ms；格式化成本被 16 路并发摊掉。
    """
    vectors = embed_many(texts, embedding_model)
    return [to_vector_literal_fast(vector) for vector in vectors]


def _embed_and_write(base: str, key_type: str, records: list[dict], key_fn, text_fn,
                     embedding_model, embed_many, stats: dict, label_fn=None, *,
                     progress_cb: Optional[Callable[[str, int, int], None]] = None,
                     bulk: bool = False, fast_load: bool = False) -> int:
    """过滤空文本 → 按 key_id 合并冲突 → 流水线向量化 + 多行写入。

    同一 ``key_id`` 出现多次（跨 class 同 entity_id，或同端点多条平行边）时，
    把文本按确定性顺序拼接、labels 取并集，**不静默丢弃后一条**；``collisions``
    计数留给任务日志/调用方观测。

    向量化用线程池并发（默认 16 路），DB 写入保持单线程有序；两者通过
    ``EMBED_WINDOW_FACTOR`` 个在途批次重叠，实测网关 16 路 × 128 条约 2.2k 条/s。

    :param label_fn: 记录没有显式 ``labels`` 时的默认标签（实体/边按类型打标）。
    :param progress_cb: ``(key_type, done, total)``，每约 5% 调一次。
    :param bulk: 批量导入：事务级 ``synchronous_commit=off``。
    :param fast_load: 空表装载：索引已提前卸掉，INSERT 不带 ``ON CONFLICT``。
    """
    merged: dict[str, dict] = {}
    for record in records:
        key_id = key_fn(record)
        text = text_fn(record)
        if not key_id or not text:
            stats['skipped'] += 1
            continue
        labels = _labels(record)
        if not labels and label_fn is not None:
            labels = label_fn(record)
        if key_id in merged:
            previous = merged[key_id]
            previous['text'] = previous['text'] + '\n' + text
            previous['labels'] = sorted(set(previous['labels']) | set(labels))
            stats['collisions'] += 1
        else:
            merged[key_id] = {
                'text': text, 'labels': labels,
                'edge_id': str(record.get('edge_id') or '').strip() or None,
                'source_id': str(record.get('source_id') or '').strip() or None,
                'target_id': str(record.get('target_id') or '').strip() or None,
            }
    prepared = [(key_id, value['text'], value['labels'],
                 value['edge_id'], value['source_id'], value['target_id'])
                for key_id, value in merged.items()]
    if not prepared:
        return 0

    batches = [prepared[start:start + EMBED_BATCH_SIZE]
               for start in range(0, len(prepared), EMBED_BATCH_SIZE)]
    total = len(prepared)
    workers = max(1, min(EMBED_CONCURRENCY, len(batches)))
    window = workers * EMBED_WINDOW_FACTOR
    log_every = max(1, len(batches) // 20)
    started = time.perf_counter()
    written = 0
    done = 0
    embed_ms = 0.0
    write_ms = 0.0
    futures = {}
    write_pool = None
    write_futures = []
    if fast_load and bulk and WRITE_CONCURRENCY > 1:
        # 空表装载没有唯一索引，批次互不重叠；多连接并发写入把 128 行的
        # 解析/传输时间摊到多个 PG backend 上。
        write_pool = ThreadPoolExecutor(max_workers=WRITE_CONCURRENCY,
                                        thread_name_prefix=f'write-{key_type}')
    pool = ThreadPoolExecutor(max_workers=workers,
                              thread_name_prefix=f'embed-{key_type}')
    next_index = 0
    try:
        for index, batch in enumerate(batches):
            while next_index < len(batches) and next_index < index + window:
                futures[next_index] = pool.submit(
                    _embed_and_format, embed_many,
                    [row[1] for row in batches[next_index]], embedding_model)
                next_index += 1
            start = index * EMBED_BATCH_SIZE
            wait_started = time.perf_counter()
            try:
                vectors = futures.pop(index).result()
            except Exception as error:                            # noqa: BLE001
                raise GraphIndexError(
                    f'embedding failed for {key_type} batch at {start}: {error}') from error
            embed_ms += (time.perf_counter() - wait_started) * 1000
            if len(vectors) != len(batch):
                raise GraphIndexError(
                    f'embedding count mismatch for {key_type}: '
                    f'sent {len(batch)}, got {len(vectors)}')
            rows = [(key_id, text, labels, vector, edge_id, source_id, target_id)
                    for (key_id, text, labels, edge_id, source_id, target_id), vector
                    in zip(batch, vectors)]
            if write_pool is not None:
                write_futures.append(write_pool.submit(
                    upsert_vectors, base, key_type, rows,
                    bulk=bulk, on_conflict=False))
                written += len(rows)
                if len(write_futures) >= WRITE_CONCURRENCY * 2:
                    _wait_write(write_futures.pop(0), key_type)
            else:
                write_started = time.perf_counter()
                written += upsert_vectors(base, key_type, rows,
                                          bulk=bulk, on_conflict=not fast_load)
                write_ms += (time.perf_counter() - write_started) * 1000
            done += len(batch)
            if index % log_every == 0 or index == len(batches) - 1:
                elapsed = max(time.perf_counter() - started, 1e-9)
                rate = done / elapsed
                eta = (total - done) / rate if rate else 0.0
                completed_batches = index + 1
                write_note = (f'write=async({WRITE_CONCURRENCY})'
                              if write_pool is not None else
                              f'write={write_ms / completed_batches:.0f}ms/batch')
                log.info('[graph-index] %s %s/%s (%.1f%%) %.1f rows/s ETA %.0fs '
                         'workers=%s embed=%.0fms/batch %s',
                         key_type, done, total, 100.0 * done / total, rate, eta,
                         workers, embed_ms / completed_batches, write_note)
                if progress_cb:
                    progress_cb(key_type, done, total)
        if write_pool is not None:
            for future in write_futures:
                _wait_write(future, key_type)
            write_futures.clear()
    finally:
        for future in futures.values():
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        if write_pool is not None:
            write_pool.shutdown(wait=False, cancel_futures=True)
    return written


def _wait_write(future, key_type: str) -> None:
    try:
        future.result()
    except Exception as error:                                    # noqa: BLE001
        raise GraphIndexError(f'write failed for {key_type}: {error}') from error
