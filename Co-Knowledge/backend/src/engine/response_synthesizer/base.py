from abc import ABC, abstractmethod
from typing import Dict

from engine.primitives.interfaces import RagSynthesizer


class BaseRagResponseSynthesizer(RagSynthesizer, ABC):

    @classmethod
    @abstractmethod
    def from_args(cls, config_dict: Dict) -> "BaseSynthesizer":
        """
        todo
        """
