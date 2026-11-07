from abc import ABC, abstractmethod
from typing import List, Dict

from engine.primitives.interfaces import RagRetriever
from engine.primitives.models import NodeWithScore, QueryBundle


class BaseRagRetriever(RagRetriever, ABC):

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """
        call knowledge base
        """
        pass

    def get_description(self) -> str:
        """
        todo
        """

    @classmethod
    @abstractmethod
    def from_args(cls, config_dict: Dict) -> "BaseRetriever":
        """
        todo
        """
