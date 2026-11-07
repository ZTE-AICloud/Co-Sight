from abc import ABC
from collections import defaultdict
from typing import Dict, List, Tuple

from engine.custom_llm import Qwen
from engine.primitives.components.fusion import FUSION_MODES, QueryFusionRetriever
from engine.primitives.interfaces import RagRetriever
from engine.primitives.models import NodeWithScore


class FusionRetriever(QueryFusionRetriever, ABC):

    @classmethod
    def from_args(cls, config_dict: Dict):
        return FusionRetriever(
            retrievers=[],
            similarity_top_k=500,
            mode=FUSION_MODES.RELATIVE_SCORE,
            retriever_weights=config_dict.get('weights', []),
            num_queries=1,
            llm=Qwen(),
            use_async=False
        )

    def update_retrievers(self, retrievers: List[RagRetriever]):
        self._retrievers = retrievers
        weights_size = len(self._retriever_weights)
        if weights_size == 1 or weights_size != len(retrievers):
            self.mode = FUSION_MODES.RECIPROCAL_RANK

    def _reciprocal_rerank_fusion(
            self,
            results: Dict[Tuple[str, int], List[NodeWithScore]],
            k: float = 60.0
    ) -> List[NodeWithScore]:
        """
        Apply Reciprocal Rank Fusion (RRF) with preference for nodes that contain 'related_chunk_ids'.

        For duplicate content (by text), the representative node is updated only if:
            - The current node has non-empty 'related_chunk_ids' in metadata, AND
            - The previously stored node does NOT have 'related_chunk_ids'.

        Otherwise, the first encountered node is retained.

        Reference: Cormack et al., SIGIR 2009 (RRF).
        """
        fused_scores: Dict[str, float] = defaultdict(float)
        text_to_node: Dict[str, NodeWithScore] = {}

        for nodes_with_scores in results.values():
            sorted_nodes = sorted(
                nodes_with_scores,
                key=lambda x: x.score if x.score is not None else 0.0,
                reverse=True
            )

            for rank, node in enumerate(sorted_nodes):
                text = node.node.get_content()
                current_has_related = bool(node.node.metadata.get("related_chunk_ids"))

                if text not in text_to_node:
                    text_to_node[text] = node
                elif current_has_related and not bool(text_to_node[text].node.metadata.get("related_chunk_ids")):
                    text_to_node[text] = node

                fused_scores[text] += 1.0 / (rank + k)

        reranked_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        reranked_nodes: List[NodeWithScore] = []
        for text, score in reranked_results:
            reranked_nodes.append(text_to_node[text])
            reranked_nodes[-1].score = score

        return reranked_nodes
