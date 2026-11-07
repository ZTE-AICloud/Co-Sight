from abc import ABC, abstractmethod
from typing import List, Optional, Dict

from engine.primitives.interfaces import RagNodePostprocessor
from engine.primitives.models import NodeWithScore, QueryBundle


class BaseRagPostRetriever(RagNodePostprocessor, ABC):

    def _postprocess_nodes(self,
                           nodes: List[NodeWithScore],
                           query_bundle: Optional[QueryBundle] = None) -> List[NodeWithScore]:
        return nodes

    @classmethod
    @abstractmethod
    def from_args(cls, config_dict: Dict) -> "BaseNodePostprocessor":
        """
        todo
        """
