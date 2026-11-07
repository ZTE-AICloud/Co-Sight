"""自研编排原语：融合检索（`QueryFusionRetriever` 的对位实现）。

替代 llama-index-core 0.10.31 的 `retrievers/fusion_retriever.py`。

**只实现同步取数路径**：本仓的 `FusionRetriever` 显式传 `use_async=False`
（`retriever/fusion_retriever.py:25`）。库的 `use_async=True` 默认值走
`aretrieve`/`run_async_tasks` —— 那条路在本服务里从未被走到，这里显式拒绝而不是
悄悄退化成同步（静默改变行为比报错难查得多）。

四种融合模式保持一致（本仓覆盖了 `_reciprocal_rerank_fusion`，其余三种原样保留）：
  * `RECIPROCAL_RANK`：RRF，k=60；
  * `RELATIVE_SCORE`：MinMax 归一到 [0,1] → 乘 retriever 权重 → 除 `num_queries` → 按文本去重求和；
  * `DIST_BASED_SCORE`：同上但 MinMax 用均值±3σ；
  * `SIMPLE`：按文本去重取 max 分。

⚠️ 权重归一化在**构造期**完成（`retriever_weights` 求和后逐项除总和）。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from engine.primitives.interfaces import RagRetriever
from engine.primitives.models import NodeWithScore, QueryBundle

DEFAULT_SIMILARITY_TOP_K = 2

QUERY_GEN_PROMPT = (
    'You are a helpful assistant that generates multiple search queries based on a '
    'single input query. Generate {num_queries} search queries, one on each line, '
    'related to the following input query:\n'
    'Query: {query}\n'
    'Queries:\n'
)


class FUSION_MODES(str, Enum):
    RECIPROCAL_RANK = 'reciprocal_rerank'
    RELATIVE_SCORE = 'relative_score'
    DIST_BASED_SCORE = 'dist_based_score'
    SIMPLE = 'simple'


class QueryFusionRetriever(RagRetriever):
    def __init__(
            self,
            retrievers: List[RagRetriever],
            llm: Optional[Any] = None,
            query_gen_prompt: Optional[str] = None,
            mode: FUSION_MODES = FUSION_MODES.SIMPLE,
            similarity_top_k: int = DEFAULT_SIMILARITY_TOP_K,
            num_queries: int = 4,
            use_async: bool = True,
            verbose: bool = False,
            retriever_weights: Optional[List[float]] = None,
    ) -> None:
        self.num_queries = num_queries
        self.query_gen_prompt = query_gen_prompt or QUERY_GEN_PROMPT
        self.similarity_top_k = similarity_top_k
        self.mode = mode
        self.use_async = use_async
        self._verbose = verbose

        self._retrievers = retrievers
        if retriever_weights is None:
            self._retriever_weights = [1.0 / len(retrievers)] * len(retrievers)
        else:
            total_weight = sum(retriever_weights)
            self._retriever_weights = [w / total_weight for w in retriever_weights]
        self._llm = llm

    # ---- 取数 -----------------------------------------------------------
    def _get_queries(self, original_query: str) -> List[QueryBundle]:
        prompt_str = self.query_gen_prompt.format(
            num_queries=self.num_queries - 1,
            query=original_query,
        )
        response = self._llm.complete(prompt_str)
        queries = response.text.split('\n')
        return [QueryBundle(q) for q in queries[: self.num_queries - 1]]

    def _run_sync_queries(self, queries: List[QueryBundle]) -> Dict[Tuple[str, int], List[NodeWithScore]]:
        results: Dict[Tuple[str, int], List[NodeWithScore]] = {}
        for query in queries:
            for i, retriever in enumerate(self._retrievers):
                results[(query.query_str, i)] = retriever.retrieve(query)
        return results

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        queries: List[QueryBundle] = [query_bundle]
        if self.num_queries > 1:
            queries.extend(self._get_queries(query_bundle.query_str))

        if self.use_async:
            raise NotImplementedError(
                'QueryFusionRetriever 的自研实现只支持 use_async=False（本仓唯一调用点即如此）。'
                '要用异步路径请先补齐 _run_nested_async_queries 的复刻与用例。'
            )
        results = self._run_sync_queries(queries)

        if self.mode == FUSION_MODES.RECIPROCAL_RANK:
            return self._reciprocal_rerank_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.RELATIVE_SCORE:
            return self._relative_score_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.DIST_BASED_SCORE:
            return self._relative_score_fusion(results, dist_based=True)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.SIMPLE:
            return self._simple_fusion(results)[: self.similarity_top_k]
        raise ValueError(f'Invalid fusion mode: {self.mode}')

    # ---- 四种融合（前两种与库完全一致；本仓子类会覆盖第一种） ------------
    def _reciprocal_rerank_fusion(
            self, results: Dict[Tuple[str, int], List[NodeWithScore]]) -> List[NodeWithScore]:
        k = 60.0
        fused_scores: Dict[str, float] = {}
        text_to_node: Dict[str, NodeWithScore] = {}

        for nodes_with_scores in results.values():
            for rank, node_with_score in enumerate(
                    sorted(nodes_with_scores, key=lambda x: x.score or 0.0, reverse=True)):
                text = node_with_score.node.get_content()
                text_to_node[text] = node_with_score
                if text not in fused_scores:
                    fused_scores[text] = 0.0
                fused_scores[text] += 1.0 / (rank + k)

        reranked_results = dict(sorted(fused_scores.items(), key=lambda x: x[1], reverse=True))

        reranked_nodes: List[NodeWithScore] = []
        for text, score in reranked_results.items():
            reranked_nodes.append(text_to_node[text])
            reranked_nodes[-1].score = score
        return reranked_nodes

    def _relative_score_fusion(
            self,
            results: Dict[Tuple[str, int], List[NodeWithScore]],
            dist_based: Optional[bool] = False,
    ) -> List[NodeWithScore]:
        min_max_scores: Dict[Tuple[str, int], Tuple[float, float]] = {}
        for query_tuple, nodes_with_scores in results.items():
            if not nodes_with_scores:
                min_max_scores[query_tuple] = (0.0, 0.0)
                continue
            scores = [node_with_score.score for node_with_score in nodes_with_scores]
            if dist_based:
                mean_score = sum(scores) / len(scores)
                std_dev = (sum((x - mean_score) ** 2 for x in scores) / len(scores)) ** 0.5
                min_score = mean_score - 3 * std_dev
                max_score = mean_score + 3 * std_dev
            else:
                min_score = min(scores)
                max_score = max(scores)
            min_max_scores[query_tuple] = (min_score, max_score)

        for query_tuple, nodes_with_scores in results.items():
            for node_with_score in nodes_with_scores:
                min_score, max_score = min_max_scores[query_tuple]
                if max_score == min_score:
                    node_with_score.score = 1.0 if max_score > 0 else 0.0
                else:
                    node_with_score.score = (node_with_score.score - min_score) / (max_score - min_score)
                retriever_idx = query_tuple[1]
                node_with_score.score *= self._retriever_weights[retriever_idx]
                node_with_score.score /= self.num_queries

        all_nodes: Dict[str, NodeWithScore] = {}
        for nodes_with_scores in results.values():
            for node_with_score in nodes_with_scores:
                text = node_with_score.node.get_content()
                if text in all_nodes:
                    all_nodes[text].score += node_with_score.score
                else:
                    all_nodes[text] = node_with_score

        return sorted(all_nodes.values(), key=lambda x: x.score or 0.0, reverse=True)

    def _simple_fusion(
            self, results: Dict[Tuple[str, int], List[NodeWithScore]]) -> List[NodeWithScore]:
        all_nodes: Dict[str, NodeWithScore] = {}
        for nodes_with_scores in results.values():
            for node_with_score in nodes_with_scores:
                text = node_with_score.node.get_content()
                if text in all_nodes:
                    max_score = max(node_with_score.score, all_nodes[text].score)
                    all_nodes[text].score = max_score
                else:
                    all_nodes[text] = node_with_score
        return sorted(all_nodes.values(), key=lambda x: x.score or 0.0, reverse=True)
