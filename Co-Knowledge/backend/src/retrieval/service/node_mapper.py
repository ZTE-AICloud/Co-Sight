"""把向量表/ES 的原始行加工成 ``SearchResultVO``。

**这里全是「保真」代码，不是「设计」代码** —— 三个分支的键集互不相同、
``metadata`` 取的是嵌套的 ``_node_content.metadata``、``sourceDocId`` 在新库分支恒为 null，
都是线上真实行为，前端与编排层按它解析。改之前先做对比。

> 存储侧写平铺 metadata；``metadata`` 由 ``node_format.node_envelope`` 组装，
> 键集与键序即对外契约（有 ``test_kb_api_node_format.py`` 钉住）。
"""

from __future__ import annotations

from typing import Optional

from shared.chunk_schema import node_columns
from shared.chunk_schema import node_format
from infrastructure.logging.logutil import log

# **只有这两个键**会被从 metadata 里剔除。
# chunk_id / type / source / chunk_index / node_id / file_id 等一律原样透出。
INTERNAL_METADATA_KEYS = {'content_expand', 'context_expand_method'}


def as_string(value) -> Optional[str]:
    """字符串化：null → null，其余按字符串处理。

    注意布尔：产出 ``"true"``/``"false"``；Python 的 ``str(True)`` 是 ``"True"``，
    这里显式对齐，避免 metadata 里出现大小写不同的字面量。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def as_double(value) -> Optional[float]:
    """``asDouble``：只有 Number 才转，其余 null（字符串数字**不**转）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ``metadata`` 展开成列之后，不再有 JSON 列需要"归一成 dict"，
# 读侧统一走 ``node_columns.metadata_from_row()``。


def process_vector_record(record: dict) -> dict:
    """处理向量表的原始行。

    两条要命的细节（都还在）：

    1. **没有 metadata 的行返回空 map**（不是 ``{node:…}`` 包装）—— 于是这条 doc
       在响应里退化成 ``{}``，字段全是 null。这是对外契约行为
       （展开成列后判「5 个列全为 NULL」）。
    2. 响应里的 ``metadata`` 是**切片元数据本体**（去掉存储内部键），
       **缺失时不回落成空 dict**。

    ``metadata`` 从展开列拼回（``node_columns.metadata_from_row``），
    键集/键序与契约一致（有 ``test_kb_api_node_format.py`` 钉住）。
    """
    metadata = record.get('metadata')
    if not isinstance(metadata, dict):
        metadata = node_columns.metadata_from_row(record)
    if not metadata:
        log.warning('process_vector_record: 该行没有 metadata')
        return {}

    # node 信封由 node_format 统一构造（键集/键序即对外契约）。
    node = node_format.node_envelope(metadata, record.get('text'),
                                     row_id=record.get('id'),
                                     node_id=record.get('node_id'))

    return {
        'node': node,
        'score': record.get('cosine_similarity'),
        'class_name': 'NodeWithScore',
    }


def enrich_metadata_with_chunk_text(record: dict, chunk_text, chunk_id) -> None:
    """用 chunk 正文**原地改** ``record['metadata_']``。

    联合查询把 chunk 正文以 ``chunk.text AS chunk_text`` 带出来，这里用它替换
    ``metadata.content_expand``（那里存的是 chunk id）。

    全程吞异常 —— 这是「锦上添花」的一步，失败不该让整次检索报废。
    """
    try:
        # ``metadata`` 已展开成列；联合查询那一侧会拼好 ``record['metadata']``。
        metadata = record.get('metadata')
        if metadata is None:
            return
        if chunk_id is None or not chunk_text:
            return

        if not isinstance(metadata, dict):
            log.warning('enrich: metadata is not a map, skip')
            return

        if metadata.get('content_expand') is not None and str(metadata['content_expand']) == str(chunk_id):
            metadata['content_expand'] = chunk_text

        record['metadata'] = metadata
    except Exception:
        log.warning('enrich metadata with chunk text failed', exc_info=True)


def to_search_doc(raw_doc) -> dict:
    """``RetrieveServiceImpl.toSearchDoc``：``SearchDocVO`` 的五个字段。"""
    node = (raw_doc or {}).get('node') or {}
    metadata = node.get('metadata')
    if isinstance(metadata, dict):
        clean_metadata = {
            str(key): value
            for key, value in metadata.items()
            if str(key) not in INTERNAL_METADATA_KEYS
        }
    else:
        clean_metadata = None

    return {
        'chunkId': as_string(metadata.get('chunk_id') if isinstance(metadata, dict) else None),
        'content': as_string(node.get('text')),
        'score': as_double((raw_doc or {}).get('score')),
        'sourceDocId': as_string(node.get('file_id')),
        'metadata': clean_metadata,
    }


def to_search_results(raw_results: list[dict]) -> list[dict]:
    """``RetrieveServiceImpl.toSearchResults``：``{baseName, docs}``。"""
    out = []
    for raw in raw_results or []:
        docs = raw.get('docs')
        out.append({
            'baseName': as_string(raw.get('base_name')),
            'docs': [to_search_doc(doc) for doc in docs if isinstance(doc, dict)]
            if isinstance(docs, list) else [],
        })
    return out
