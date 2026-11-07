"""自研编排原语：查询引擎（Transform / Retriever / Router 的对位实现）。

替代 llama-index-core 0.10.31 的：
  * `query_engine/transform_query_engine.py`（`TransformQueryEngine`）：改写后委托；
  * `query_engine/retriever_query_engine.py`（`RetrieverQueryEngine`）：检索 → 后处理 → 合成；
  * `query_engine/router_query_engine.py`（`RouterQueryEngine` + `combine_responses`）：
    选择器挑引擎 → 执行 → 多选时合并。

**对齐**：`RouterQueryEngine._query` 的最后一步会给响应挂
`metadata["selector_result"]`（本仓下游不消费，但照挂以保持一致）；多选合并走
`combine_responses`（`str(response)` 取文本 → `summarizer.get_response`）。

**刻意不做**：callback/instrumentation 事件（全仓零订阅者）、异步 `a*` 变体、
`from_defaults` 的 Settings 回落链。
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from engine.common import stage_timing
from engine.primitives.components.summarizer import TreeSummarize
from engine.primitives.interfaces import (
    RagNodePostprocessor,
    RagQueryEngine,
    RagQueryTransform,
    RagRetriever,
    RagSelector,
    RagSynthesizer,
)
from engine.primitives.models import (
    NodeWithScore,
    QueryBundle,
    QueryEngineTool,
    Response,
    StreamingResponse,
)


class TransformQueryEngine(RagQueryEngine):
    """改写后委托给内层引擎（`MultiTransformQueryEngine` 的基类）。"""

    def __init__(self, query_engine: RagQueryEngine, query_transform: RagQueryTransform,
                 transform_metadata: Optional[dict] = None) -> None:
        self._query_engine = query_engine
        self._query_transform = query_transform
        self._transform_metadata = transform_metadata

    def retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        query_bundle = self._query_transform.run(query_bundle, metadata=self._transform_metadata)
        return self._query_engine.retrieve(query_bundle)

    def synthesize(self, query_bundle: QueryBundle, nodes: List[NodeWithScore],
                   additional_source_nodes: Optional[Sequence[NodeWithScore]] = None) -> Any:
        query_bundle = self._query_transform.run(query_bundle, metadata=self._transform_metadata)
        return self._query_engine.synthesize(
            query_bundle=query_bundle, nodes=nodes,
            additional_source_nodes=additional_source_nodes)

    def _query(self, query_bundle: QueryBundle) -> Response:
        # 只测 transform 本身；内层引擎的时间另由它自己的阶段埋点记录。
        with stage_timing.measure(stage_timing.STAGE_UNDERSTANDING):
            query_bundle = self._query_transform.run(
                query_bundle, metadata=self._transform_metadata)
        return self._query_engine.query(query_bundle)


class RetrieverQueryEngine(RagQueryEngine):
    """检索 → 后处理 → 合成（`SelectPromptQueryEngine` 的基类）。"""

    def __init__(self, retriever: RagRetriever,
                 response_synthesizer: Optional[RagSynthesizer] = None,
                 node_postprocessors: Optional[List[RagNodePostprocessor]] = None) -> None:
        self._retriever = retriever
        self._response_synthesizer = response_synthesizer
        self._node_postprocessors = node_postprocessors or []

    def _apply_node_postprocessors(self, nodes: List[NodeWithScore],
                                   query_bundle: QueryBundle) -> List[NodeWithScore]:
        for node_postprocessor in self._node_postprocessors:
            nodes = node_postprocessor.postprocess_nodes(nodes, query_bundle=query_bundle)
        return nodes

    def retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        # 只测最外层 retriever：fusion 内部会再调用子 retriever，若在每个 retriever
        # 类上埋点会重复计时。同阶段多次执行（Router 多选）由收集器累加。
        with stage_timing.measure(stage_timing.STAGE_RETRIEVAL):
            nodes = self._retriever.retrieve(query_bundle)
        # 本仓注册的 postprocessor 目前全是重排器（LLMReranker/ExternalModelReranker）；
        # 没有配置时不要记录，展示层才能区分「没重排」和「重排 0ms」。
        if self._node_postprocessors:
            with stage_timing.measure(stage_timing.STAGE_RERANK):
                nodes = self._apply_node_postprocessors(
                    nodes, query_bundle=query_bundle)
        return nodes

    def synthesize(self, query_bundle: QueryBundle, nodes: List[NodeWithScore],
                   additional_source_nodes: Optional[Sequence[NodeWithScore]] = None) -> Any:
        return self._response_synthesizer.synthesize(
            query=query_bundle, nodes=nodes, additional_source_nodes=additional_source_nodes)

    def _query(self, query_bundle: QueryBundle) -> Response:
        nodes = self.retrieve(query_bundle)
        return self._response_synthesizer.synthesize(query=query_bundle, nodes=nodes)


def combine_responses(summarizer: TreeSummarize, responses: List[Any],
                      query_bundle: QueryBundle) -> Any:
    """库实现：把多个子引擎的响应合成一个（多选时才会走到）。"""
    response_strs = []
    source_nodes: List[NodeWithScore] = []
    for response in responses:
        if isinstance(response, StreamingResponse):
            response_obj = response.get_response()
        else:
            response_obj = response
        source_nodes.extend(response_obj.source_nodes)
        response_strs.append(str(response_obj))

    summary = summarizer.get_response(query_bundle.query_str, response_strs)

    if isinstance(summary, str):
        return Response(response=summary, source_nodes=source_nodes,
                        query_str=query_bundle.query_str)
    return StreamingResponse(response_gen=summary, source_nodes=source_nodes,
                             query_str=query_bundle.query_str)


class RouterQueryEngine(RagQueryEngine):
    """按选择器把 query 路由到某个子引擎（`ConditionalQueryEngine` 的基类）。"""

    def __init__(self, selector: RagSelector, query_engine_tools: Sequence[QueryEngineTool],
                 llm: Optional[Any] = None, summarizer: Optional[TreeSummarize] = None,
                 verbose: bool = False) -> None:
        self._llm = llm
        self._selector = selector
        self._query_engines = [x.query_engine for x in query_engine_tools]
        self._metadatas = [x.metadata for x in query_engine_tools]
        self._summarizer = summarizer or TreeSummarize(llm=llm)
        self._verbose = verbose

    def _query(self, query_bundle: QueryBundle) -> Response:
        # 路由判断也属于「问题理解」；只测 select，子引擎的检索/重排各自记录。
        with stage_timing.measure(stage_timing.STAGE_UNDERSTANDING):
            result = self._selector.select(self._metadatas, query_bundle)

        if len(result.inds) > 1:
            responses = []
            for engine_ind in result.inds:
                selected_query_engine = self._query_engines[engine_ind]
                responses.append(selected_query_engine.query(query_bundle))
            if len(responses) > 1:
                final_response = combine_responses(self._summarizer, responses, query_bundle)
            else:
                final_response = responses[0]
        else:
            try:
                selected_query_engine = self._query_engines[result.ind]
            except ValueError as e:
                raise ValueError('Failed to select query engine') from e
            final_response = selected_query_engine.query(query_bundle)

        # 与库一致：把选择结果挂到响应 metadata（本仓下游不消费，照挂保持形状一致）
        final_response.metadata = final_response.metadata or {}
        final_response.metadata['selector_result'] = result
        return final_response
