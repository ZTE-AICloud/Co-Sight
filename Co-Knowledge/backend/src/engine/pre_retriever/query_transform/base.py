from abc import abstractmethod
from typing import Dict

from engine.primitives.interfaces import RagQueryTransform
from engine.primitives.models import QueryBundle


class BaseRagQueryTransform(RagQueryTransform):

    def __init__(self, config_info):
        self.config_info = config_info

    @classmethod
    @abstractmethod
    def from_args(cls, config_dict: Dict) -> "BaseRagQueryTransform":
        """
        todo
        """

    @abstractmethod
    def _run(self, query_bundle: QueryBundle, metadata: Dict) -> QueryBundle:
        """
        todo
        """

    # 自研原语层没有 PromptMixin（提示词不参与库的 introspection 体系），
    # `_get_prompts` / `_update_prompts` 与 `PromptDictType` 一起删除了 —— 全仓无调用方。
