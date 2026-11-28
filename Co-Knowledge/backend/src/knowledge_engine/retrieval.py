"""混合检索：向量 + 词法（BM25）→ RRF →（可选）重排。

三路信号各管一段：

* **向量**：语义相近（「支付金额」↔「实收」）；
* **词法**：字面命中（表名 ``order_info``、字段 ``city_name``）；
* **重排**：把前两者融合后的候选按问题重新打分，只对 top-N 调用。

词法这一路刻意不引入外部依赖：知识集是「几十到几百条」量级，中文按字符二元组
切分后在本进程算 BM25 就够，不需要 ES、也不需要 ``pg_trgm`` 扩展。

对上层只暴露 :func:`hybrid_search`：调用方给出「怎么按向量查」和「怎么取全量正文」
两个函数，其余（融合、预算、重排）由本模块负责。知识集合是版本化的不可变数据，
所以分词结果按 ``corpus_key`` 缓存。
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable, Optional

RRF_K = 60
BM25_K1 = 1.5
BM25_B = 0.75
#: 重排只对融合后的前 N 条调用：端点很贵，且 20 条之后基本不会进上下文。
RERANK_TOP_N = 20
_CACHE_LIMIT = 4

_CJK = re.compile(r'[一-鿿]+')
_WORD = re.compile(r'[a-z0-9_]+')
_TOKEN_CACHE: dict[str, list[tuple[dict[str, Any], Counter]]] = {}


def hybrid_search(
        *, question: str, embedding: list[float],
        vector_search: Callable[[list[float], int], list[dict[str, Any]]],
        corpus_loader: Callable[[str], list[dict[str, Any]]],
        corpus_key: str,
        limit: int = 24,
        rerank_model: Optional[str] = None,
) -> dict[str, Any]:
    """返回 ``{'hits', 'sources', 'reranked'}``；``hits`` 已按融合分数排序。"""
    vector_hits = vector_search(embedding, limit)
    lexical_hits = _lexical(corpus_loader, corpus_key, question, limit=limit)
    hits = _rrf([vector_hits, lexical_hits])
    reranked = 0
    if rerank_model:
        hits, reranked = _rerank(question, hits, rerank_model)
    return {
        'hits': hits[:limit],
        'sources': {'vector': len(vector_hits), 'lexical': len(lexical_hits),
                    'reranked': reranked},
        'reranked': bool(reranked),
    }


def lexical_search(*, question: str,
                   corpus_loader: Callable[[str], list[dict[str, Any]]],
                   corpus_key: str, limit: int = 24) -> list[dict[str, Any]]:
    """只跑 BM25 的那一路（没有向量索引的领域，例如 ES mapping 检索）。"""
    return _lexical(corpus_loader, corpus_key, question, limit=limit)


def clear_cache(corpus_key: Optional[str] = None) -> None:
    """测试与运维用：清掉某个语料（或全部）的分词缓存。"""
    if corpus_key is None:
        _TOKEN_CACHE.clear()
    else:
        _TOKEN_CACHE.pop(corpus_key, None)


# ---------------------------------------------------------------------------
# 词法（BM25）
# ---------------------------------------------------------------------------
def _lexical(corpus_loader, corpus_key: str, question: str,
             *, limit: int) -> list[dict[str, Any]]:
    corpus = _corpus(corpus_loader, corpus_key)
    if not corpus:
        return []
    query_terms = Counter(_tokens(question))
    if not query_terms:
        return []
    document_frequency: Counter = Counter()
    for _row, bag in corpus:
        document_frequency.update(bag.keys())
    total = len(corpus)
    average_length = sum(sum(bag.values()) for _row, bag in corpus) / total or 1.0

    scored: list[tuple[float, dict[str, Any]]] = []
    for row, bag in corpus:
        length = sum(bag.values())
        score = 0.0
        for term in query_terms:
            frequency = bag.get(term, 0)
            if not frequency:
                continue
            idf = math.log(1 + (total - document_frequency[term] + 0.5)
                           / (document_frequency[term] + 0.5))
            score += idf * frequency * (BM25_K1 + 1) / (
                frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / average_length))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], str(item[1].get('object_key'))))
    return [{**row, 'score': score} for score, row in scored[:limit]]


def _corpus(corpus_loader: Callable[[str], list[dict[str, Any]]],
            corpus_key: str) -> list[tuple[dict[str, Any], Counter]]:
    cached = _TOKEN_CACHE.get(corpus_key)
    if cached is not None:
        return cached
    rows = corpus_loader(corpus_key)
    corpus = [(row, Counter(_tokens(f"{row.get('title') or ''} "
                                    f"{row.get('content') or ''}")))
              for row in rows]
    if len(_TOKEN_CACHE) >= _CACHE_LIMIT:
        _TOKEN_CACHE.pop(next(iter(_TOKEN_CACHE)))
    _TOKEN_CACHE[corpus_key] = corpus
    return corpus


def _tokens(text: str) -> list[str]:
    """中文按字符二元组、其余按 ASCII 词切分。"""
    lowered = (text or '').lower()
    tokens = _WORD.findall(lowered)
    for run in _CJK.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


# ---------------------------------------------------------------------------
# 融合与重排
# ---------------------------------------------------------------------------
def _rrf(ranked_lists: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion：只用名次，不比较各路分值的量纲。"""
    fused: dict[tuple[str, str], float] = defaultdict(float)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for ranked in ranked_lists:
        for rank, row in enumerate(ranked, start=1):
            key = (str(row.get('object_type')), str(row.get('object_key')))
            fused[key] += 1.0 / (RRF_K + rank)
            rows.setdefault(key, row)
    ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return [{**rows[key], 'score': round(score, 6)} for key, score in ordered]


def _rerank(question: str, hits: list[dict[str, Any]],
            model: str) -> tuple[list[dict[str, Any]], int]:
    """调用注册表里的重排端点；任何失败都退回融合顺序（可用性优先）。"""
    if len(hits) <= 1:
        return hits, 0
    candidates = hits[:RERANK_TOP_N]
    try:
        scores = _call_rerank(question, [row.get('content') or row.get('title') or ''
                                         for row in candidates], model)
    except Exception:                                      # noqa: BLE001
        return hits, 0
    if not scores:
        return hits, 0
    ranked = sorted(zip(candidates, scores), key=lambda pair: -pair[1])
    for row, score in ranked:
        row['rerank_score'] = float(score)
    return ([row for row, _score in ranked] + hits[RERANK_TOP_N:], len(ranked))


def _call_rerank(question: str, documents: list[str], model: str) -> list[float]:
    from infrastructure.http import egress
    from model.resolver import resolve

    endpoint = resolve('rerank', model)
    if not endpoint.url:
        return []
    response = egress.post(endpoint.url,
                           json={'model': endpoint.api_model or model,
                                 'query': question, 'documents': documents},
                           headers=endpoint.headers(), timeout=60)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f'rerank status {response.status_code}')
    payload = response.json()
    results = payload.get('results') or payload.get('data') or []
    ordered: list[Optional[float]] = [None] * len(documents)
    for item in results:
        index = item.get('index')
        score = item.get('relevance_score')
        if isinstance(index, int) and 0 <= index < len(documents) and score is not None:
            ordered[index] = float(score)
    return [score if score is not None else 0.0 for score in ordered]
