import time
from abc import ABC
from typing import List, Dict

from engine.primitives.models import NodeWithScore, QueryBundle

from engine.common import stage_timing
from engine.common.const import retrieve_type
from engine.gateways.knowledge_base_client import invoke_knowledge_base_client
from engine.retriever.base import BaseRagRetriever
from engine.logutil import logger
from engine.http_utils import build_headers
from engine.rag_utils import append_dialogue_kb


def _build_request_body(question: str, config_info: dict, _retrieve_type: int) -> dict:
    bases = [
        {
            "baseList": config_info.get('knowledge_base_name', []),
            "priority": config_info.get('priority', 10),
            "top_k": config_info.get('top_k', 8),
            "score_threshold": config_info.get('score', 0)
        }
    ]
    append_dialogue_kb(bases, config_info.get("user_request", {}))
    return {
        "question": question,
        "type": _retrieve_type,
        "bases": bases
    }




class KeywordRetriever(BaseRagRetriever, ABC):

    def __init__(self, config_info: Dict):
        super().__init__()
        self.config_info = config_info
        self.header = config_info.get('headers')
        self.header.set_mode('0')

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        body = _build_request_body(query_bundle.query_str, self.config_info, retrieve_type['keyword'])
        bases = [name for base in body.get('bases', []) for name in base.get('baseList', [])]
        started = time.perf_counter()
        # 分项耗时：混合检索的 fusion 会串行调用本类与 VectorRetriever，
        # 只有分项才能让面板分别展示「向量检索 / 关键字检索」。
        with stage_timing.measure(stage_timing.STAGE_KEYWORD_RETRIEVAL):
            nodes = invoke_knowledge_base_client(build_headers(self.header), body)
        logger.info('[retriever][keyword] bases=%s nodes=%s elapsed=%.3fs',
                    bases, len(nodes or []), time.perf_counter() - started)
        return nodes


    def get_description(self) -> str:
        return self.config_info.get('desc_info', '')

    @classmethod
    def from_args(cls, config_dict: Dict) -> "BaseRagRetriever":
        return KeywordRetriever(config_dict)
