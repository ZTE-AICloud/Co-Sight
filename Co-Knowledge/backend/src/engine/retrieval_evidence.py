"""把一次 `/query` 的检索命中收敛成前端可展示的「知识库依据」。

数据来源是 `Response/StreamingResponse.source_nodes` —— 也就是**重排之后、真正交给
合成器**的那批 `RagNodeWithScore`。本模块只做纯函数转换，不碰检索流程：

    build_retrieval_evidence(source_nodes, query_str) -> dict
    prepare_retrieval_frame(conversation_id, evidence)    -> str（SSE data 载荷）

两点刻意的取舍：

1. **不透出完整 metadata**：节点 metadata 里有 `content_expand`、`type`
   等内部字段，前端展示只需要来源/切片号/分数。这里显式挑字段，既避免泄漏，也避免
   把 SSE 帧撑大。
2. **不改 Node.metadata**：文件名在适配器里被 `sourceDocId` 覆盖（见
   `core/gateways/knowledge_base_client.py`），可读文件名由 Node 上的 `source_name`
   动态属性带过来。属性不会进 `get_content(MetadataMode.LLM)`，因此不会污染
   合成/重排提示词。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional

from engine import json_utils
from engine.common import const, stage_timing

#: 单次响应最多返回多少条证据（正常 top_n ≤ 8，这个上限只防异常配置）
MAX_EVIDENCE_ITEMS = 20
#: 单条片段最多多少字符（与 agent_api 的 MAX_TEXT_CHARS 同口径）
MAX_EVIDENCE_TEXT_CHARS = 2000
#: 图谱知识库的 base 前缀（`graph_<uuid>`）
GRAPH_BASE_PREFIX = 'graph_'
#: 画布里的作用域后缀，例如 `doc_<uuid>|#|dev`
SCOPE_SEPARATOR = '|#|'

_MARKERS = (
    const.expand_format,
    const.source_format,
    const.base_format,
    const.node_id_format,
    const.chunk_index_format,
)


def _as_text(value: Any) -> str:
    return '' if value is None else str(value)


def _strip_markers(value: Any) -> str:
    """去掉检索链路包在字段两端的 `|*xxx#|` 标记。"""
    text = _as_text(value)
    for marker in _MARKERS:
        text = text.replace(marker, '')
    return text.strip()


def _clean_base(value: Any) -> str:
    """把 base 归一成展示用名称：脱标记 + 去掉 `|#|scope` 后缀。"""
    return _strip_markers(value).split(SCOPE_SEPARATOR, 1)[0].strip()


def _as_score(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_item(node_with_score: Any, max_text_chars: int) -> Optional[Dict[str, Any]]:
    """一条 `RagNodeWithScore` → 展示项；完全没内容的节点返回 None。"""
    node = getattr(node_with_score, 'node', None)
    if node is None:
        return None
    metadata = getattr(node, 'metadata', None)
    if not isinstance(metadata, dict):
        metadata = {}

    base_name = getattr(node_with_score, 'base_name', '')
    kb = _clean_base(base_name or metadata.get('knowledge_name', ''))

    # 文件名优先级：适配器带过来的 source_name（属性）→ metadata.file_name →
    # metadata.source。图谱节点的 metadata.source 本来就是文件名。
    stored_source = _strip_markers(getattr(node, 'source_name', ''))
    source = (stored_source
              or _strip_markers(metadata.get('file_name', ''))
              or _strip_markers(metadata.get('source', '')))
    raw_source = _strip_markers(metadata.get('source', ''))
    source_id = raw_source if raw_source and raw_source != source else ''

    text = _strip_markers(getattr(node, 'text', ''))
    label = _strip_markers(metadata.get('label', ''))
    if not text and not source and not label:
        return None

    truncated = len(text) > max_text_chars
    if truncated:
        text = text[:max_text_chars]

    chunk_id = (_strip_markers(metadata.get('node_id', ''))
                or _strip_markers(metadata.get('chunk_id', '')))
    chunk_index = (_strip_markers(metadata.get('chunk_index', ''))
                   or _strip_markers(metadata.get('chunk_order', '')))

    return {
        'index': 0,  # 过滤后统一编号
        'kind': 'graph' if kb.startswith(GRAPH_BASE_PREFIX) else 'document',
        'kb': kb,
        'source': source,
        'sourceId': source_id,
        'chunkId': chunk_id,
        'chunkIndex': chunk_index,
        'score': _as_score(getattr(node_with_score, 'score', None)),
        'label': label,
        'text': text,
        'truncated': truncated,
    }


#: 内部阶段名 → 对外契约字段。只映射这里列出的阶段，未知 key 一律丢弃。
#: `retrievalMs` 是检索合计；`vectorRetrievalMs` / `keywordRetrievalMs` /
#: `graphRetrievalMs` 是按检索器类型拆出的分项（展示层优先用分项，缺失时才回落合计）。
_TIMING_CONTRACT = (
    (stage_timing.STAGE_UNDERSTANDING, 'understandingMs'),
    (stage_timing.STAGE_RETRIEVAL, 'retrievalMs'),
    (stage_timing.STAGE_VECTOR_RETRIEVAL, 'vectorRetrievalMs'),
    (stage_timing.STAGE_KEYWORD_RETRIEVAL, 'keywordRetrievalMs'),
    (stage_timing.STAGE_GRAPH_RETRIEVAL, 'graphRetrievalMs'),
    (stage_timing.STAGE_RERANK, 'rerankMs'),
)


def _build_timings(raw: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """阶段耗时 → 契约字段；空结果表示「本轮没有测到任何阶段」。"""
    if not isinstance(raw, Mapping):
        return {}
    result: Dict[str, float] = {}
    for stage, key in _TIMING_CONTRACT:
        value = raw.get(stage)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if not math.isfinite(number) or number < 0:
            continue
        result[key] = round(number, 1)
    return result


def summarize_source_nodes(source_nodes: Optional[Iterable[Any]]) -> Dict[str, Any]:
    """给 `chat_query_trace` 用的命中统计（**不受** evidence 的 20 条截断影响）。

    复用 `_build_item` 的清洗规则（标记剥离、source_name 优先、图谱/文档判定），
    因此 `hit_count` 与面板的 `stats.total` 同口径；但这里遍历全部节点，
    `source_count/kb_count` 不是截断后的去重数。
    """
    items: List[Dict[str, Any]] = []
    for node_with_score in list(source_nodes or []):
        item = _build_item(node_with_score, 0)
        if item is not None:
            items.append(item)
    scores = [
        float(item['score']) for item in items
        if isinstance(item['score'], (int, float))
        and math.isfinite(float(item['score']))
    ]
    return {
        'hit_count': len(items),
        'source_count': len({item['source'] for item in items if item['source']}),
        'kb_count': len({item['kb'] for item in items if item['kb']}),
        'top_score': max(scores) if scores else None,
    }


def build_retrieval_evidence(
        source_nodes: Optional[Iterable[Any]],
        query_str: str = '',
        max_items: int = MAX_EVIDENCE_ITEMS,
        max_text_chars: int = MAX_EVIDENCE_TEXT_CHARS,
        *,
        timings: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """把 source_nodes 转成 `{query, items, stats, timings?}`。

    ``timings`` 是请求级阶段耗时（内部 key 见 :mod:`engine.common.stage_timing`），
    只有测到至少一个阶段才输出：

    ``{"understandingMs": ..., "retrievalMs": ..., "vectorRetrievalMs": ...,
    "keywordRetrievalMs": ..., "graphRetrievalMs": ..., "rerankMs": ...}``

    未启用的阶段缺 key（展示层用 ``—`` 区分「没跑」和「跑了 0ms」）。
    ``retrievalMs`` 与各分项是「合计 vs 分项」关系，混用会双计。

    绝不抛异常以外的东西给调用方：调用方（`app.py`）还要再包一层 try/except，
    这里只保证形状稳定、字段可序列化。
    """
    kept: List[Dict[str, Any]] = []
    for node_with_score in list(source_nodes or []):
        item = _build_item(node_with_score, max_text_chars)
        if item is not None:
            kept.append(item)

    total = len(kept)
    items = kept[:max(0, int(max_items or 0))]
    for index, item in enumerate(items, start=1):
        item['index'] = index

    sources = {item['source'] for item in items if item['source']}
    knowledge_bases = {item['kb'] for item in items if item['kb']}
    evidence: Dict[str, Any] = {
        'query': _as_text(query_str),
        'items': items,
        'stats': {
            'count': len(items),
            'total': total,
            'sources': len(sources),
            'knowledgeBases': len(knowledge_bases),
        },
    }
    timing_payload = _build_timings(timings)
    if timing_payload:
        evidence['timings'] = timing_payload
    return evidence


def prepare_retrieval_frame(conversation_id: str, evidence: Dict[str, Any]) -> str:
    """构造 ``event: retrieval`` 的 JSON ``data``。

    形状：`{"conversation_id": ..., "evidence": {...}}`。事件类型由 SSE 的 ``event:``
    字段表达，不再塞进 payload 的 `output.type`。
    """
    return json_utils.json_unescape_dumps({
        'conversation_id': conversation_id,
        'evidence': evidence,
    })
