from abc import abstractmethod
from typing import Dict

from engine.primitives.components.selector import SingleSelector


class BaseRagSelector(SingleSelector):

    @classmethod
    @abstractmethod
    def from_args(cls, config_dict: Dict) -> "LLMSingleSelector":
        """
        todo
        """
