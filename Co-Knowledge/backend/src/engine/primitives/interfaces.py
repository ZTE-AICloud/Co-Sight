"""自研编排原语：组件抽象基类。

替代 llama-index-core 0.10.31 的 `BaseRetriever` / `BaseQueryEngine` /
`BaseNodePostprocessor` / `BaseSynthesizer` / `BaseQueryTransform` / `BaseSelector`。

**钩子名保持与库一致**（`_retrieve` / `_postprocess_nodes` / `_query` / `synthesize` /
`_run` / `_select`），公共入口（`retrieve` / `query` / `postprocess_nodes` / `run` /
`select`）也同名同形 —— 这样 vendored 算子类只需换 import 与基类，业务代码零改动。

**刻意不做的事**：库的 `callback_manager` / instrumentation 事件（全仓零订阅者）、
`PromptMixin` / `ChainableMixin` / `from_defaults` 链路、异步 `_a*` 变体
（本仓全部走同步路径）。以后要加观测，这里是唯一的挂点。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence

from engine.primitives.models import (
    NodeWithScore,
    QueryBundle,
    Response,
    SelectorResult,
    ToolMetadata,
)


class RagRetriever(ABC):
    """检索器基类（替代 `BaseRetriever`）。"""

    def retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        return self._retrieve(query_bundle)

    @abstractmethod
    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """call knowledge base"""

    def get_description(self) -> Optional[str]:
        """候选描述。**保持恒 None**：条件路由的 choices 文案依赖它回落到库默认
        DEFAULT_DESCRIPTION（见 `primitives/prompts.py`）。"""
        return None


class RagQueryEngine(ABC):
    """查询引擎基类（替代 `BaseQueryEngine` 的 `query`/`retrieve`/`synthesize`）。

    ⚠️ `retrieve` / `synthesize` **不是抽象方法**：库的实现是"抛 NotImplementedError"
    的具名消息（路由器就是这种引擎 —— 只支持 `query`）。错误文案保持不变。
    """

    def query(self, str_or_query_bundle: Any, **kwargs: Any) -> Response:
        query_bundle = (str_or_query_bundle if isinstance(str_or_query_bundle, QueryBundle)
                        else QueryBundle(query_str=str_or_query_bundle))
        return self._query(query_bundle)

    def retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        raise NotImplementedError(
            'This query engine does not support retrieve, use query directly')

    def synthesize(
            self,
            query_bundle: QueryBundle,
            nodes: List[NodeWithScore],
            additional_source_nodes: Optional[Sequence[NodeWithScore]] = None,
    ) -> Response:
        raise NotImplementedError(
            'This query engine does not support synthesize, use query directly')

    @abstractmethod
    def _query(self, query_bundle: QueryBundle) -> Response:
        ...


class RagNodePostprocessor(ABC):
    """后处理器基类（替代 `BaseNodePostprocessor`）。"""

    def postprocess_nodes(
            self,
            nodes: List[NodeWithScore],
            query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        return self._postprocess_nodes(nodes, query_bundle)

    @abstractmethod
    def _postprocess_nodes(
            self,
            nodes: List[NodeWithScore],
            query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        ...


class RagSynthesizer(ABC):
    """合成器基类（替代 `BaseSynthesizer` 中本仓用到的部分）。

    子类（components 里的 `SimpleSummarize` 对位实现）负责 `get_response` /
    `_prepare_response_output`；这里只保证 `_llm` / `_streaming` / `_text_qa_template`
    三个字段的存在性与库一致。
    """

    def __init__(self, llm: Optional[Any] = None, streaming: bool = False) -> None:
        self._llm = llm
        self._streaming = streaming
        self._text_qa_template = None

    @abstractmethod
    def synthesize(
            self,
            query: Any,
            nodes: List[NodeWithScore],
            additional_source_nodes: Optional[Sequence[NodeWithScore]] = None,
            **response_kwargs: Any,
    ) -> Any:
        ...


class RagQueryTransform(ABC):
    """查询改写基类（替代 `BaseQueryTransform`）。"""

    def __init__(self, config_dict: Optional[Dict[str, Any]] = None) -> None:
        self.config_info: Dict[str, Any] = dict(config_dict or {})

    def run(self, query_bundle: QueryBundle, metadata: Optional[Dict[str, Any]] = None) -> QueryBundle:
        return self._run(query_bundle, metadata)

    @abstractmethod
    def _run(self, query_bundle: QueryBundle, metadata: Optional[Dict[str, Any]]) -> QueryBundle:
        ...


class RagSelector(ABC):
    """选择器基类（替代 `LLMSingleSelector`）。"""

    def select(self, choices: Sequence[ToolMetadata], query: QueryBundle) -> SelectorResult:
        return self._select(choices, query)

    @abstractmethod
    def _select(self, choices: Sequence[ToolMetadata], query: QueryBundle) -> SelectorResult:
        ...
