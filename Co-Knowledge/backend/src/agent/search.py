"""严格检索编排：向量 / 关键词 / 混合（RRF）。

失败语义（与 retrieve_service 的「一律空结果」相反）：

* **显式给了 knowledge_base_ids**：任一路/任一库的查询异常 → 直接 502 fail-fast；
* **隐式「全部库」**：能查的照常返回，失败的路/库记 warning + ``degraded=true``；
  两条路都没有一次成功查询且确有异常 → 502。

「表/索引不存在」是 KB 状态问题（未导入/未建索引），按 warning 处理，不算异常。
"""

from __future__ import annotations

from model import gateway as model_gateway
from shared.chunk_schema.vector import to_vector_literal
from infrastructure.logging.logutil import log

from agent import config, store_retrieval
from agent.auth import AgentPrincipal
from agent.errors import retrieval_failed
from agent.knowledge import name_map, resolve_kbases
from agent.schemas import SearchRequest

RRF_K = 60
MAX_CANDIDATES = 80
CANDIDATE_MULTIPLIER = 2
MAX_TEXT_CHARS = 2000


def _candidate_limit(top_k: int) -> int:
    return min(max(top_k * CANDIDATE_MULTIPLIER, top_k), MAX_CANDIDATES)


def _dedupe_key(hit: dict) -> tuple:
    kb_id = hit.get('knowledge_base_id') or ''
    chunk_id = hit.get('chunk_id')
    if chunk_id not in (None, ''):
        return (kb_id, 'chunk', str(chunk_id))
    node_id = hit.get('node_id')
    if node_id:
        return (kb_id, 'node', str(node_id))
    metadata = hit.get('metadata') or {}
    return (kb_id, 'text', hit.get('document_id') or '',
            metadata.get('chunk_index'), (hit.get('text') or '')[:64])


def _vector_path(rows: list[dict], question: str, top_k: int,
                 score_threshold: float, strict: bool):
    """返回 ``(hits, warnings, ok_count, error_count)``。"""
    hits: list[dict] = []
    warnings: list[dict] = []
    ok = errors = 0

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault((row.get('embedding_model') or '').strip(), []).append(row)

    for model, group in groups.items():
        try:
            embedding = model_gateway.embed_query(question, model or None)
            literal = to_vector_literal(embedding)
        except Exception as error:                                 # noqa: BLE001
            log.warning('agent api: embedding failed for model=%s kb=%s',
                        model, [row.get('kbase_id') for row in group], exc_info=True)
            if strict:
                raise retrieval_failed(
                    f'embedding failed for model {model or "(default)"}') from error
            errors += len(group)
            warnings.append(store_retrieval.warning(
                'vector_path_failed',
                f'embedding failed for model {model or "(default)"}'))
            continue

        for row in group:
            kb_id = row.get('kbase_id') or ''
            try:
                kb_hits, warning = store_retrieval.vector_hits(
                    row, literal, min(top_k * CANDIDATE_MULTIPLIER, MAX_CANDIDATES),
                    score_threshold)
            except Exception as error:                             # noqa: BLE001
                log.warning('agent api: vector search failed kb=%s', kb_id, exc_info=True)
                if strict:
                    raise retrieval_failed(f'vector search failed for knowledge base {kb_id}') from error
                errors += 1
                warnings.append(store_retrieval.warning(
                    'vector_path_failed', 'vector search failed', kb_id))
                continue
            if warning:
                warnings.append(warning)
            store_retrieval.fill_document_ids(kb_id, kb_hits)
            hits.extend(kb_hits)
            ok += 1
    return hits, warnings, ok, errors


def _keyword_path(rows: list[dict], question: str, top_k: int, strict: bool):
    hits: list[dict] = []
    warnings: list[dict] = []
    ok = errors = 0
    for row in rows:
        kb_id = row.get('kbase_id') or ''
        try:
            kb_hits, warning = store_retrieval.keyword_hits(
                row, question, min(top_k * CANDIDATE_MULTIPLIER, MAX_CANDIDATES))
        except Exception as error:                                 # noqa: BLE001
            log.warning('agent api: keyword search failed kb=%s', kb_id, exc_info=True)
            if strict:
                raise retrieval_failed(f'keyword search failed for knowledge base {kb_id}') from error
            errors += 1
            warnings.append(store_retrieval.warning(
                'keyword_path_failed', 'keyword search failed', kb_id))
            continue
        if warning:
            warnings.append(warning)
            continue
        hits.extend(kb_hits)
        ok += 1
    return hits, warnings, ok, errors


def _dedupe_ranked(hits: list[dict]) -> list[dict]:
    """同一路内先按 key 去重（保留最高分），再按分数降序。

    RRF 的 rank 必须建立在**去重后的排名**上：底层的向量/关键词结果可能包含同一
    切片的重复行（联合查询或 ES 的重复命中），若直接对原始列表排名，同一 key 会被
    累加多次，RRF 分数被虚高（实测 0.0328 被抬到 0.1891）。
    """
    best: dict[tuple, dict] = {}
    for hit in hits:
        key = _dedupe_key(hit)
        current = best.get(key)
        if current is None or float(hit.get('score') or 0.0) > float(current.get('score') or 0.0):
            best[key] = hit
    return sorted(best.values(), key=lambda item: float(item.get('score') or 0.0),
                  reverse=True)


def _single_path_results(hits: list[dict], top_k: int) -> list[dict]:
    """去重后按原始分数取前 top_k。"""
    return _dedupe_ranked(hits)[:top_k]


def _hybrid_results(vector_hits: list[dict], keyword_hits: list[dict],
                    top_k: int) -> list[dict]:
    """RRF 融合；同一 key 保留两路的原始分数。"""
    merged: dict[tuple, dict] = {}
    for source, hits in (('vector', vector_hits), ('keyword', keyword_hits)):
        for rank, hit in enumerate(_dedupe_ranked(hits), start=1):
            key = _dedupe_key(hit)
            item = merged.get(key)
            if item is None:
                item = {'hit': dict(hit), 'scores': {}, 'rrf': 0.0}
                merged[key] = item
            item['rrf'] += 1.0 / (RRF_K + rank)
            item['scores'][source] = float(hit.get('score') or 0.0)

    ordered = sorted(merged.values(), key=lambda item: item['rrf'], reverse=True)[:top_k]
    results = []
    for item in ordered:
        hit = item['hit']
        hit['score'] = item['rrf']
        hit['scores'] = item['scores']
        results.append(hit)
    return results


def _format_results(rows: list[dict], hits: list[dict]) -> list[dict]:
    names = name_map(rows)
    results = []
    for index, hit in enumerate(hits, start=1):
        metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else None
        results.append({
            'citation_id': f'S{index}',
            'knowledge_base_id': hit.get('knowledge_base_id') or '',
            'knowledge_base_name': names.get(hit.get('knowledge_base_id')),
            'chunk_id': hit.get('chunk_id'),
            'document_id': hit.get('document_id'),
            'source': hit.get('source'),
            'score': float(hit.get('score') or 0.0),
            'scores': hit.get('scores'),
            'text': (hit.get('text') or '')[:MAX_TEXT_CHARS],
            'metadata': metadata,
        })
    return results


def search(principal: AgentPrincipal, request: SearchRequest) -> dict:
    """执行检索，返回 :class:`agent_api.schemas.SearchData` 形状的 dict。"""
    rows, explicit = resolve_kbases(principal, request.knowledge_base_ids)
    top_k = min(request.top_k, config.max_top_k())
    mode = request.mode
    # auto 的职责就是「一路坏了用另一路」，所以永远不 fail-fast；
    # vector/keyword/hybrid 在显式 ID 下才严格。
    strict = explicit and mode in ('vector', 'keyword', 'hybrid')

    vector_hits: list[dict] = []
    keyword_hits: list[dict] = []
    warnings: list[dict] = []
    vector_ok = keyword_ok = 0
    vector_err = keyword_err = 0

    if mode in ('auto', 'hybrid', 'vector'):
        vector_hits, vector_warnings, vector_ok, vector_err = _vector_path(
            rows, request.query, top_k, request.score_threshold, strict)
        warnings.extend(vector_warnings)

    if mode in ('auto', 'hybrid', 'keyword'):
        keyword_hits, keyword_warnings, keyword_ok, keyword_err = _keyword_path(
            rows, request.query, top_k, strict)
        warnings.extend(keyword_warnings)

    if mode == 'vector':
        results = _single_path_results(vector_hits, top_k)
        if not results and vector_err and not vector_ok:
            raise retrieval_failed('vector retrieval failed')
        degraded = vector_err > 0
        effective_mode = 'vector'
    elif mode == 'keyword':
        results = _single_path_results(keyword_hits, top_k)
        if not results and keyword_err and not keyword_ok:
            raise retrieval_failed('keyword retrieval failed')
        degraded = keyword_err > 0
        effective_mode = 'keyword'
    elif mode == 'hybrid':
        if not vector_ok and not keyword_ok and (vector_err or keyword_err):
            raise retrieval_failed('retrieval failed on both vector and keyword paths')
        if vector_ok and keyword_ok:
            results = _hybrid_results(vector_hits, keyword_hits, top_k)
            effective_mode = 'hybrid'
        elif vector_ok:
            results = _single_path_results(vector_hits, top_k)
            effective_mode = 'vector'
        elif keyword_ok:
            results = _single_path_results(keyword_hits, top_k)
            effective_mode = 'keyword'
        else:
            results = []
            effective_mode = 'hybrid'
        degraded = bool(vector_err or keyword_err or not (vector_ok and keyword_ok))
    else:                                                          # auto
        if vector_ok and keyword_ok:
            results = _hybrid_results(vector_hits, keyword_hits, top_k)
            effective_mode = 'hybrid'
            degraded = bool(vector_err or keyword_err)
        elif vector_ok:
            results = _single_path_results(vector_hits, top_k)
            effective_mode = 'vector'
            degraded = True                          # 关键词路没参与
        elif keyword_ok:
            results = _single_path_results(keyword_hits, top_k)
            effective_mode = 'keyword'
            degraded = True                          # 向量路没参与
        elif vector_err or keyword_err:
            raise retrieval_failed('retrieval failed on both vector and keyword paths')
        else:
            results = []
            effective_mode = 'auto'
            degraded = False

    return {
        'query': request.query,
        'mode': effective_mode,
        'results': _format_results(rows, results),
        'degraded': degraded,
        'warnings': warnings,
    }
