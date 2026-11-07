import time
from typing import Dict, List, Optional

from engine.primitives.components.rerank import LLMRerank
from engine.primitives.interfaces import RagNodePostprocessor
from engine.primitives.models import NodeWithScore, QueryBundle

from engine.settings import Config
from engine.custom_llm import get_custom_llm
from engine.retriever import RagNodeWithScore
from engine.logutil import logger


class LLMReranker(LLMRerank):

    @classmethod
    def from_args(cls, config_dict: Dict) -> "RagNodePostprocessor":
        # 画布显式写了 llm 就用它；否则用部署级重排模型（默认生成模型可能太慢，
        # 见 Config['generation_rerank_model'] 的注释）。
        model = config_dict.get('llm') or Config.get('generation_rerank_model') or ''
        # 重排是短输出，不需要思考；显式传了 thinking_profile 则以调用方为准。
        llm_config = dict(config_dict or {})
        llm_config.setdefault('thinking_profile', 'aux')
        return LLMReranker(
            llm=get_custom_llm(model or None, llm_config),
            top_n=config_dict.get('top_n')
        )

    def _postprocess_nodes(
            self,
            nodes: List[NodeWithScore],
            query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        if query_bundle is None:
            raise ValueError("Query bundle must be provided.")
        if len(nodes) == 0:
            return []

        started = time.perf_counter()
        batches = (len(nodes) + self.choice_batch_size - 1) // self.choice_batch_size
        logger.info('[reranker] start nodes=%s top_n=%s batch_size=%s batches=%s query_len=%s',
                    len(nodes), self.top_n, self.choice_batch_size, batches,
                    len(query_bundle.query_str or ''))

        initial_results: List[NodeWithScore] = []
        try:
            for batch_index, idx in enumerate(range(0, len(nodes), self.choice_batch_size)):
                batch_started = time.perf_counter()
                nodes_batch = [node.node for node in nodes[idx: idx + self.choice_batch_size]]
                base_names = [node.base_name for node in nodes[idx: idx + self.choice_batch_size]]
                query_str = query_bundle.query_str
                fmt_batch_str = self._format_node_batch_fn(nodes_batch)
                # call each batch independently
                raw_response = self.llm.predict(
                    self.choice_select_prompt,
                    context_str=fmt_batch_str,
                    query_str=query_str,
                )
                raw_choices, relevances = self._parse_choice_select_answer_fn(raw_response, len(nodes_batch))
                choice_idxs = [int(choice) - 1 for choice in raw_choices]
                choice_nodes = [nodes_batch[idx] for idx in choice_idxs]
                choice_base_names = [base_names[idx] for idx in choice_idxs]
                relevances = relevances or [1.0 for _ in choice_nodes]
                initial_results.extend(
                    [
                        RagNodeWithScore(node=node, score=relevance, base_name=base_name)
                        for node, relevance, base_name in zip(choice_nodes, relevances, choice_base_names)
                    ]
                )
                logger.info('[reranker] batch=%s/%s size=%s selected=%s response_len=%s '
                            'elapsed=%.3fs',
                            batch_index + 1, batches, len(nodes_batch), len(choice_nodes),
                            len(str(raw_response or '')), time.perf_counter() - batch_started)
        except Exception as e:
            logger.exception(e)
            logger.warning('[reranker] failed, falling back to first %s nodes (elapsed=%.3fs)',
                           self.top_n, time.perf_counter() - started)
            return nodes[:self.top_n]

        kept = sorted(initial_results, key=lambda x: x.score or 0.0, reverse=True)[: self.top_n]
        logger.info('[reranker] done nodes=%s kept=%s elapsed=%.3fs',
                    len(nodes), len(kept), time.perf_counter() - started)
        return kept
