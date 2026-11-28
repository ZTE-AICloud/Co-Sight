"""Schema 知识检索：把 Text2SQL 的仓储接到通用混合检索上。

融合、BM25、重排的实现在 :mod:`knowledge_engine.retrieval`；这里只负责说明
「向量怎么查」「正文从哪取」，并把版本作为语料键。

保留本模块是为了让调用方（查询编排、单测）不必知道引擎的存在；
想复用到别的算子时，直接用 ``knowledge_engine.retrieval.hybrid_search``。
"""

from __future__ import annotations

from typing import Any, Optional

from knowledge_engine import retrieval

RRF_K = retrieval.RRF_K
RERANK_TOP_N = retrieval.RERANK_TOP_N


def search(repository, version_id: str, question: str, embedding: list[float],
           *, limit: int = 24, rerank_model: Optional[str] = None,
           datasource_id: Optional[str] = None) -> dict[str, Any]:
    """返回 ``{'hits', 'sources', 'reranked'}``。"""
    return retrieval.hybrid_search(
        question=question,
        embedding=embedding,
        vector_search=lambda vector, size: repository.search_knowledge(
            version_id, vector, limit=size, datasource_id=datasource_id),
        corpus_loader=repository.list_knowledge_text,
        corpus_key=version_id,
        limit=limit,
        rerank_model=rerank_model,
    )


def clear_cache(version_id: Optional[str] = None) -> None:
    """测试与运维用：清掉某个版本（或全部）的分词缓存。"""
    retrieval.clear_cache(version_id)
