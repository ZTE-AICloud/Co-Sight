"""导入链的三写：chunk 表、向量表、ES 索引。

**三写不在一个事务里**（PG + ES 跨存储），这里不额外加补偿 ——
失败会把任务标记成失败并重试，重试靠 ``ON CONFLICT DO NOTHING`` 保幂等。
"""

from __future__ import annotations

import json
from typing import Iterable

from infrastructure.db.kb import connection
from retrieval.repository import es_store as es_store
from shared.chunk_schema import node_columns
from infrastructure.db.identifiers import SCHEMA, validate_identifier
from shared.chunk_schema.vector import to_vector_literal
from infrastructure.logging.logutil import log
from retrieval.repository.kbase_lookup import get_kbase_row

CHUNK_BATCH_SIZE = 1000
VECTOR_BATCH_SIZE = 500
ES_BATCH_SIZE = 10

def _as_text(value):
    return None if value is None else str(value)


def _as_int(name: str, value):
    """``chunk_id``/``type`` 必须是整数；UUID 或其他脏值直接跳过并告警。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        log.warning('es document field %s is not an integer: %r, skip', name, value)
        return None


def flat_document(node_id: str, file_id, text, metadata: dict) -> dict:
    """v2 扁平文档：只保留检索/响应需要的字段，``None`` 不落盘。

    字段顺序与 ``es_store.ES_DOCUMENT_FIELDS`` 一致；``chunk_index`` 的空串
    和 ``type`` 的 0 都是合法值，必须保留。
    """
    metadata = metadata or {}
    doc: dict = {}
    if node_id is not None:
        doc['node_id'] = str(node_id)
    if file_id is not None:
        doc['file_id'] = str(file_id)
    if text is not None:
        doc['text'] = text

    source = _as_text(metadata.get('source'))
    if source is not None:
        doc['source'] = source
    chunk_index = _as_text(metadata.get('chunk_index'))
    if chunk_index is not None:
        doc['chunk_index'] = chunk_index

    chunk_id = _as_int('chunk_id', metadata.get('chunk_id'))
    if chunk_id is not None:
        doc['chunk_id'] = chunk_id
    type_value = _as_int('type', metadata.get('type'))
    if type_value is not None:
        doc['type'] = type_value
    return doc


def build_metadata(metadata: dict, chunk_id) -> dict:
    """构造切片元数据：``content_expand`` 指向 chunk 表主键。"""
    metadata = dict(metadata or {})
    if chunk_id is not None:
        metadata['content_expand'] = chunk_id
    return metadata


def save_chunks(chunk_table: str, chunks: Iterable[dict]) -> None:
    """``saveChunks``：写切片表。"""
    rows = list(chunks or [])
    if not rows:
        return
    validate_identifier(chunk_table)
    sql = (
        f'INSERT INTO {SCHEMA}.{chunk_table} '
        '(id, kb_id, source, text, chunk_id, type) '
        'VALUES (%s, %s, %s, %s, %s, %s) '
        'ON CONFLICT (id) DO NOTHING'
    )
    with connection() as conn:
        with conn.cursor() as cursor:
            for start in range(0, len(rows), CHUNK_BATCH_SIZE):
                batch = rows[start:start + CHUNK_BATCH_SIZE]
                cursor.executemany(sql, [_chunk_params(chunk) for chunk in batch])
    log.info('saved %d chunk rows into %s', len(rows), chunk_table)


def _chunk_params(chunk: dict) -> tuple:
    """chunk dict → 文档库 chunk 表 6 列的值。

    文档库切片表只保留活列（``id/kb_id/source/text/chunk_id/type``）
    + 审计列；``chunk_order`` / ``spilt_type`` / ``label`` / ``table_name`` /
    ``table_id`` / ``tenant_id`` 是图谱导入导出契约字段，文档库不再落库。
    """
    cols = node_columns.columns_from_metadata(chunk.get('metadata') or {})
    return (
        chunk.get('id'), chunk.get('kbId'), chunk.get('source'), chunk.get('text'),
        cols['chunk_id'], cols['type'],
    )


def save_vectors(vector_table: str, rows: list[dict]) -> None:
    """把 ``(node_id, text, metadata, embedding)`` 批量写进动态向量表。

    ``metadata_`` 已展开成物理列（见 ``node_columns.py``），这里按
    ``columns_from_metadata()`` 落列。``embedding`` 直接传 pgvector 的文本字面量。

    **正文只存 ``chunk.text``**：``vector.text`` 普通行留 NULL；读侧用
    ``COALESCE(vector.text, chunk.text)`` 兜住 LLM 优化行（它把生成的问题写进
    ``vector.text``）。
    """
    if not rows:
        return
    validate_identifier(vector_table)
    sql = (
        f'INSERT INTO {SCHEMA}.{vector_table} '
        '(text, node_id, embedding, source, content_expand, '
        ' chunk_id, type) '
        'VALUES (%s, %s, %s::vector, %s, %s, %s, %s) '
        # 重试幂等：node_id 是向量行的业务身份；唯一索引由 ddl 保证。
        'ON CONFLICT (node_id) DO NOTHING'
    )
    with connection() as conn:
        with conn.cursor() as cursor:
            for start in range(0, len(rows), VECTOR_BATCH_SIZE):
                batch = rows[start:start + VECTOR_BATCH_SIZE]
                cursor.executemany(sql, [_vector_params(row) for row in batch])
    log.info('saved %d vector rows into %s', len(rows), vector_table)


def _vector_params(row: dict) -> tuple:
    """``metadata`` dict → 展开列的值；``vector.text`` 恒为 NULL。"""
    cols = node_columns.columns_from_metadata(row.get('metadata'))
    return (
        None,
        row['node_id'], to_vector_literal(row['embedding']),
        cols['source'], cols['content_expand'],
        cols['chunk_id'], cols['type'],
    )


def _bulk_index(client, index: str, nodes: list[dict], file_id) -> list[int]:
    """Bulk 写一批节点；返回失败项在 ``nodes`` 中的下标。"""
    failed: list[int] = []
    for start in range(0, len(nodes), ES_BATCH_SIZE):
        batch = nodes[start:start + ES_BATCH_SIZE]
        body_lines: list[str] = []
        for node in batch:
            node_id = node.get('node_id')
            if not node_id:
                raise ValueError('es document missing node_id')
            metadata = node.get('metadata') or {}
            doc = flat_document(node_id, file_id, node.get('text'), metadata)
            body_lines.append(json.dumps(
                {'index': {'_index': index, '_id': node_id}},
                ensure_ascii=False))
            body_lines.append(json.dumps(doc, ensure_ascii=False))

        result = client.bulk(body_lines) or {}
        if not result.get('errors'):
            continue
        items = result.get('items') or []
        if not items:
            failed.extend(range(start, start + len(batch)))
            continue
        for offset, item in enumerate(items):
            operation = item.get('index') or item.get('create') or item.get('update') or {}
            status = operation.get('status', 200)
            if status >= 300:
                failed.append(start + offset)
                log.warning('es bulk item failed: id=%s status=%s error=%s',
                            operation.get('_id'), status, operation.get('error'))
    return failed


def save_es_documents(kbase_id: str, file_id: str, nodes: list[dict]) -> None:
    """``FullTextClient.saveDocument``：每 10 条一批 bulk 进 ES。

    文档形状是扁平 v2，以 ``node_id`` 作为 ``_id``，重复导入幂等。
    索引不存在时抛错（否则 PG 有数据、关键词路永远为空且任务仍成功）。
    """
    if not nodes:
        return

    row = get_kbase_row(kbase_id)
    index = es_store.index_name(row.get('table_name') if row else None,
                                row.get('id') if row else 0, kbase_id)
    client = es_store._client()
    if not client.indices.exists(index):
        raise RuntimeError(f'es index {index} does not exist')

    failed = _bulk_index(client, index, nodes, file_id)
    if failed:
        raise RuntimeError(
            f'es bulk write failed for {len(failed)} docs into {index}')
    log.info('saved %d es documents into %s', len(nodes), index)


def _es_index_for(kbase_id: str) -> str | None:
    """算 ES 索引名；索引不存在时返回 None（这几处都是**只打日志**就返回）。"""
    
    row = get_kbase_row(kbase_id)
    index = es_store.index_name(row.get('table_name') if row else None,
                                row.get('id') if row else 0, kbase_id)
    client = es_store._client()
    if not client.indices.exists(index):
        log.info('index %s not exists, skip es operation', index)
        return None
    return index


def _flat_update_script(key: str, metadata: dict) -> dict:
    """整篇重写扁平字段；本次没有值的字段要从文档里删掉。"""
    fields = flat_document(None, None, key, metadata)
    text = fields.pop('text', None)
    return {
        'lang': 'painless',
        'source': (
            "ctx._source.remove('source');"
            "ctx._source.remove('chunk_index');"
            "ctx._source.remove('chunk_id');"
            "ctx._source.remove('type');"
            "if (params.text == null) { ctx._source.remove('text'); }"
            " else { ctx._source['text'] = params.text; }"
            "for (def entry : params.fields.entrySet()) {"
            " ctx._source[entry.getKey()] = entry.getValue(); }"
        ),
        'params': {'text': text, 'fields': fields},
    }


def update_es_document_by_node_id(kbase_id: str, node_id: str, key: str,
                                  metadata: dict) -> None:
    """``FullTextClient.updateIssueDocumentByNodeId``：按 ``node_id`` 命中并重写字段。"""
    index = _es_index_for(kbase_id)
    if index is None:
        return
    script = _flat_update_script(key, metadata)
    # ⚠️ ``conflicts='proceed'``：默认的 ``abort`` 在这里会 **409 version_conflict**
    # —— 同一个毫秒里连着改+删，内部快照看到的还是旧版本。proceed 让 ES 对冲突
    # 文档重试，**终态不变**，不是掩盖错误。
    result = es_store._client().update_by_query(index, {
        'query': {'bool': {'must': [{'term': {'node_id': node_id}}]}},
        'script': script,
    }, conflicts='proceed')
    result = result or {}
    updated = result.get('updated', 0)
    if updated == 0:
        log.warning('es update matched no docs for node_id %s in %s', node_id, index)
    if result.get('failures'):
        log.warning('es update failures for node_id %s in %s: %s',
                    node_id, index, result.get('failures'))
    if result.get('version_conflicts'):
        log.warning('es update version conflicts for node_id %s in %s: %s',
                    node_id, index, result.get('version_conflicts'))


def delete_es_documents_by_query(kbase_id: str, field_name: str,
                                 values: list) -> None:
    """``FullTextClient.deleteDocumentsByQuery``：``terms`` 查询后删。"""
    if not values:
        return
    index = _es_index_for(kbase_id)
    if index is None:
        return
    es_store._client().delete_by_query(
        index, {'query': {'bool': {'must': [{'terms': {field_name: list(values)}}]}}},
        conflicts='proceed')
