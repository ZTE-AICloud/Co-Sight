"""严格检索的底层访问（向量 / 关键词 / 关系回填）。

**为什么不调用 ``retrieve_service.retrieve()``**：那条路径用 ``except Exception``
把一切失败收敛成 ``bo=[]``，且刻意保留了 ``records[0]`` 的缺陷（新库 0 命中时
IndexError → 整个请求空结果）。Agent 接口必须能区分「没命中」与「检索坏了」。

这里只复用它的**纯映射函数**（``_build_docs`` / ``_keyword_node_with_score`` /
``to_search_doc``），查询与异常处理自己写：任何 store 异常都向上抛，由上层按
显式/隐式 KB 选择决定 fail-fast 还是 degraded。
"""

from __future__ import annotations

from typing import Optional

from retrieval.service import retrieve_service as retrieve_service
from retrieval.service import search as search_service
from retrieval.service.node_mapper import to_search_doc
from infrastructure.db import identifiers
from infrastructure.logging.logutil import log


def warning(code: str, message: str, kb_id: Optional[str] = None) -> dict:
    item = {'code': code, 'message': message}
    if kb_id:
        item['knowledge_base_id'] = kb_id
    return item


def vector_table_name(row: dict) -> str:
    """``kb_kbase.table_name``（通常为 ``doc_<id>_vector``）；为空时按规则回落。"""
    name = (row.get('table_name') or '').strip()
    if name:
        return name
    return identifiers.doc_vector_table(str(row.get('kbase_id') or ''))


def chunk_table_name(row: dict) -> str:
    return identifiers.chunk_table_for(vector_table_name(row))


def _hit_from_mapped(mapped: dict, kb_id: str) -> Optional[dict]:
    node = mapped.get('node') or {}
    doc = to_search_doc(mapped)
    text = doc.get('content')
    if not text:
        return None
    metadata = doc.get('metadata') if isinstance(doc.get('metadata'), dict) else None
    return {
        'knowledge_base_id': kb_id,
        'node_id': node.get('id_'),
        'chunk_id': doc.get('chunkId'),
        'document_id': doc.get('sourceDocId'),
        'source': doc.get('source') or (metadata or {}).get('source'),
        'score': float(doc.get('score') or 0.0),
        'text': text,
        'metadata': metadata,
    }


def vector_hits(row: dict, embedding_literal: str, top_k: int,
                score_threshold: float) -> tuple[list[dict], Optional[dict]]:
    """向量路。表不存在 → 空结果 + warning；查询异常 → 向上抛。"""
    kb_id = row.get('kbase_id') or ''
    table = vector_table_name(row)
    if not search_service.table_exists(table):
        return [], warning('vector_table_missing',
                           f'vector table {table} does not exist', kb_id)

    chunk_table = chunk_table_name(row)
    records = search_service.query_by_embedding_with_chunk(
        table, chunk_table, embedding_literal, score_threshold, top_k)

    # 复用检索服务的节点映射；这里只绕过 retrieve() 的异常收敛与 records[0] 缺陷。
    mapped_docs = retrieve_service.build_docs(records)               # noqa: SLF001
    hits = []
    for mapped in mapped_docs:
        hit = _hit_from_mapped(mapped, kb_id)
        if hit is not None:
            hits.append(hit)
    return hits, None


def keyword_hits(row: dict, question: str, top_k: int) -> tuple[list[dict], Optional[dict]]:
    """关键词路。索引不存在 → 空结果 + warning；搜索后端异常 → 向上抛。"""
    kb_id = row.get('kbase_id') or ''
    name = search_service.index_name_for_row(row)
    if not search_service.index_exists(name):
        return [], warning('keyword_index_missing',
                           f'search index {name} does not exist', kb_id)

    hits = []
    for raw in search_service.search_index(name, question, top_k):
        mapped = retrieve_service.keyword_node_with_score(raw)       # noqa: SLF001
        hit = _hit_from_mapped(mapped, kb_id)
        if hit is None:
            continue
        source = raw.get('_source') or {}
        hit['document_id'] = hit.get('document_id') or source.get('file_id')
        hits.append(hit)
    return hits, None


def fill_document_ids(kb_id: str, hits: list[dict]) -> None:
    """用 ``kb_node_relation`` 批量补 ``document_id``（原地改 hits）。

    向量表没有 ``file_id`` 列，新库分支的 ``sourceDocId`` 恒为 null；关系表里
    ``(kbase_id, node_id) -> directory_id`` 是文件 ID 的权威来源。关键词路径通常
    已经带了 ``_source.file_id``，只补缺的。

    这是「锦上添花」：表缺失/查询失败只记日志，不让整次检索失败。
    """
    missing = [hit for hit in hits if not hit.get('document_id') and hit.get('node_id')]
    if not missing:
        return
    node_ids = list({str(hit['node_id']) for hit in missing})
    try:
        from infrastructure.db.kb import connection
        from infrastructure.db.rows import rows as _rows

        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT node_id, directory_id FROM public.kb_node_relation '
                    'WHERE kbase_id = %s AND node_id = ANY(%s)',
                    (kb_id, node_ids),
                )
                mapping = {
                    str(row['node_id']): row.get('directory_id')
                    for row in _rows(cursor)
                }
    except Exception:                                              # noqa: BLE001
        log.warning('agent api: fill document_id failed for kb=%s', kb_id, exc_info=True)
        return
    for hit in missing:
        document_id = mapping.get(str(hit.get('node_id')))
        if document_id:
            hit['document_id'] = document_id
