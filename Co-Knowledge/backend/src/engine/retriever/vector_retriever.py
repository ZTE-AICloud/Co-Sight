import time
from abc import ABC
from typing import Dict, List

from engine.primitives.models import NodeWithScore, QueryBundle

from engine.common import stage_timing
from engine.common.const import retrieve_type
from engine.gateways.knowledge_base_client import invoke_knowledge_base_client
from engine.retriever.base import BaseRagRetriever
from engine.logutil import logger
from engine.http_utils import build_headers
from engine.rag_utils import append_dialogue_kb

def _build_request_body(question: str, config_info: dict, _retrieve_type: int) -> dict:
    knowledge_info_list = config_info.get('knowledge_info_list', [])
    bases = [{
        "priority": knowledge_info.get('priority', 10),
        "baseList": knowledge_info.get('knowledge_base_name', []),
        "top_k": knowledge_info.get('top_k', 8),
        "score_threshold": knowledge_info.get('score', 0)
    } for knowledge_info in knowledge_info_list]

    append_dialogue_kb(bases, config_info.get("user_request", {}))

    request_condition = {
        "question": question,
        "type": _retrieve_type,
        "bases": bases
    }
    if config_info.get('embedding'):
        request_condition["model"] = config_info.get('embedding')
    return request_condition







class VectorRetriever(BaseRagRetriever, ABC):

    def __init__(self, config_info: Dict):
        super().__init__()
        self.config_info = config_info
        self.header = config_info.get('headers')
        self.header.set_mode('0')

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        body = _build_request_body(query_bundle.query_str, self.config_info, retrieve_type['vector'])
        bases = [name for base in body.get('bases', []) for name in base.get('baseList', [])]
        started = time.perf_counter()
        # 分项耗时：混合检索的 fusion 会串行调用本类与 KeywordRetriever，
        # 只有分项才能让面板分别展示「向量检索 / 关键字检索」。
        with stage_timing.measure(stage_timing.STAGE_VECTOR_RETRIEVAL):
            nodes = invoke_knowledge_base_client(build_headers(self.header), body)
        logger.info('[retriever][vector] bases=%s model=%r nodes=%s elapsed=%.3fs',
                    bases, body.get('model'), len(nodes or []),
                    time.perf_counter() - started)
        return nodes

    def get_description(self) -> str:
        return self.config_info.get('desc_info', '')

    @classmethod
    def from_args(cls, config_dict: Dict) -> "BaseRagRetriever":
        return VectorRetriever(config_dict)
