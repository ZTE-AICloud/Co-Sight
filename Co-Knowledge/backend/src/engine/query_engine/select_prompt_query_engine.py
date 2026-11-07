from abc import ABC

from engine.primitives.components.query_engine import RetrieverQueryEngine
from engine.primitives.models import QueryBundle, Response as RESPONSE_TYPE

from engine.logutil import logger


class SelectPromptQueryEngine(RetrieverQueryEngine, ABC):
    """
    选择prompt的查询引擎
    根据生成器算子的配置选择各知识库对应的prompt，同时支持选择LLM和top_k

    内部引用，不对外暴露
    """

    # 重写RetrieverQueryEngine的_query方法，让其支持更新生成器算子配置的能力
    def _query(self, query_bundle: QueryBundle) -> RESPONSE_TYPE:
        # 这里不包 callback 事件（CBEventType.QUERY）——
        # 全仓没有 callback 订阅者，事件只产生开销。
        nodes = self.retrieve(query_bundle)
        base_name = nodes[0].base_name if len(nodes) > 0 else ''
        logger.info('Most similar base is [%s]' % base_name)
        self._response_synthesizer.update_llm_and_prompt(base_name)
        return self._response_synthesizer.synthesize(
            query=query_bundle,
            nodes=nodes,
        )
