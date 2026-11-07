"""自研编排原语：合成器（`SimpleSummarize` / `TreeSummarize` 的对位实现）。

替代 llama-index-core 0.10.31 的 `response_synthesizers/simple_summarize.py`
（`SimpleSummarize`）+ `response_synthesizers/tree_summarize.py`（`TreeSummarize`，
仅路由器多选合并用到）+ `response_synthesizers/base.py` 的两段：
`_get_metadata_for_response` 与 `_prepare_response_output`（含 `"Empty Response"` 哨兵）。

**语义**：
  * `get_response()`：`partial_format(query_str=...)` → `"\\n".join(text_chunks)` 压成**一块**
    → `PromptHelper.truncate(...)`（**返回值是 list**，直接作为 `context_str` 传给
    `predict/stream` —— 于是模板里落成 list 的 repr，这是既定行为）
    → 非流式走 `predict`、流式走 `stream` → **空串替换为 `"Empty Response"`**；
  * `_prepare_response_output()`：`str` → `Response`；生成器 → `StreamingResponse`；
    两者都带 `source_nodes` 与 `metadata={node_id: node.metadata}`；
  * `"Empty Response"` 的另一来源 `empty_response_generator()`（基类流式兜底）也一并对位 ——
    `app._streamer` 靠这个字面量识别哨兵帧。
"""
from __future__ import annotations

from typing import Any, Generator, List, Optional, Sequence, Union

from engine.primitives.components.token_split import PromptHelper
from engine.primitives.interfaces import RagSynthesizer
from engine.primitives.models import (
    MetadataMode,
    NodeWithScore,
    QueryBundle,
    Response,
    StreamingResponse,
)
from engine.primitives.prompts import DEFAULT_SUMMARY_PROMPT_TMPL, DEFAULT_TEXT_QA_PROMPT_TMPL
from engine.primitives.templating import PromptTemplate, PromptType, SelectorPromptTemplate

RESPONSE_TEXT_TYPE = Union[str, Generator[str, None, None]]


def empty_response_generator() -> Generator[str, None, None]:
    """库的基类兜底：无 token 时产出哨兵（`app._streamer` 按字面量分支）。"""
    yield 'Empty Response'


class _SynthesizerBase(RagSynthesizer):
    """合成器公共部分（对位库的 `BaseSynthesizer` 中最常用的一段）。"""

    def __init__(self, llm: Optional[Any] = None, streaming: bool = False,
                 prompt_helper: Optional[PromptHelper] = None) -> None:
        super().__init__(llm=llm, streaming=streaming)
        self._prompt_helper = prompt_helper or (
            PromptHelper.from_llm_metadata(llm.metadata) if llm is not None else None)

    # ---- 响应装配（库 `BaseSynthesizer` 的两个方法） ----------------------
    @staticmethod
    def _get_metadata_for_response(nodes: List[Any]) -> Optional[dict]:
        return {node.node_id: node.metadata for node in nodes}

    def _prepare_response_output(
            self,
            response_str: Optional[RESPONSE_TEXT_TYPE],
            source_nodes: List[NodeWithScore],
    ) -> Any:
        response_metadata = self._get_metadata_for_response(
            [node_with_score.node for node_with_score in source_nodes])

        if isinstance(response_str, str):
            return Response(response_str, source_nodes=source_nodes, metadata=response_metadata)
        if isinstance(response_str, Generator):
            return StreamingResponse(response_str, source_nodes=source_nodes,
                                     metadata=response_metadata)
        raise ValueError(
            f'Response must be a string or a generator. Found {type(response_str)}')

    # ---- 通用合成入口（库 `BaseSynthesizer.synthesize`） -------------------
    def synthesize(self, query: Any, nodes: List[NodeWithScore],
                   additional_source_nodes: Optional[Sequence[NodeWithScore]] = None,
                   **response_kwargs: Any) -> Any:
        """库实现：零节点走哨兵；否则取各节点 LLM 模式文本 → `get_response` → 装配响应。

        ⚠️ 本仓的 `RagSimpleSummarizer` **覆盖**了本方法：它多了引用/图片标记、
        零检索兜底（`generate_answer`/`generate_answer_stream`）与会话历史保存。
        这里的实现只服务"基类行为对齐"与单测。
        """
        if len(nodes) == 0:
            if self._streaming:
                return StreamingResponse(response_gen=empty_response_generator())
            return Response('Empty Response')

        if isinstance(query, str):
            query = QueryBundle(query_str=query)

        response_str = self.get_response(
            query_str=query.query_str,
            text_chunks=[n.node.get_content(metadata_mode=MetadataMode.LLM) for n in nodes],
            **response_kwargs,
        )

        additional_source_nodes = additional_source_nodes or []
        source_nodes = list(nodes) + list(additional_source_nodes)
        return self._prepare_response_output(response_str, source_nodes)


class SimpleSummarize(_SynthesizerBase):
    """`SimpleSummarize` 的对位实现（本仓 `RagSimpleSummarizer` 的基类）。"""

    def __init__(self, llm: Optional[Any] = None, streaming: bool = False,
                 prompt_helper: Optional[PromptHelper] = None,
                 text_qa_template: Optional[Any] = None) -> None:
        super().__init__(llm=llm, streaming=streaming, prompt_helper=prompt_helper)
        # 库默认是 DEFAULT_TEXT_QA_PROMPT_SEL（带 chat 条件分支）；本仓生产路径由
        # `RagSimpleSummarizer._select_prompt()` 恒量覆写，条件分支不可达，故只保留默认模板。
        self._text_qa_template = text_qa_template or SelectorPromptTemplate(
            default_template=PromptTemplate(DEFAULT_TEXT_QA_PROMPT_TMPL,
                                            prompt_type=PromptType.QUESTION_ANSWER))

    def get_response(
            self,
            query_str: str,
            text_chunks: Sequence[str],
            **response_kwargs: Any,
    ) -> RESPONSE_TEXT_TYPE:
        text_qa_template = self._text_qa_template.partial_format(query_str=query_str)
        single_text_chunk = '\n'.join(text_chunks)
        truncated_chunks = self._prompt_helper.truncate(
            prompt=text_qa_template,
            text_chunks=[single_text_chunk],
        )

        response: RESPONSE_TEXT_TYPE
        if not self._streaming:
            response = self._llm.predict(
                text_qa_template,
                context_str=truncated_chunks,
                **response_kwargs,
            )
        else:
            response = self._llm.stream(
                text_qa_template,
                context_str=truncated_chunks,
                **response_kwargs,
            )

        if isinstance(response, str):
            response = response or 'Empty Response'
        return response

    # `synthesize` 由子类（RagSimpleSummarizer）实现 —— 基类保持抽象


class TreeSummarize(_SynthesizerBase):
    """`TreeSummarize` 的对位实现（路由器多选合并时使用；同步递归路径）。"""

    def __init__(self, llm: Optional[Any] = None, streaming: bool = False,
                 prompt_helper: Optional[PromptHelper] = None,
                 summary_template: Optional[Any] = None) -> None:
        super().__init__(llm=llm, streaming=streaming, prompt_helper=prompt_helper)
        self._summary_template = summary_template or SelectorPromptTemplate(
            default_template=PromptTemplate(DEFAULT_SUMMARY_PROMPT_TMPL,
                                            prompt_type=PromptType.SUMMARY))

    def get_response(
            self,
            query_str: str,
            text_chunks: Sequence[str],
            **response_kwargs: Any,
    ) -> RESPONSE_TEXT_TYPE:
        summary_template = self._summary_template.partial_format(query_str=query_str)
        text_chunks = self._prompt_helper.repack(summary_template, text_chunks=list(text_chunks))

        if len(text_chunks) == 1:
            if self._streaming:
                return self._llm.stream(summary_template, context_str=text_chunks[0],
                                        **response_kwargs)
            return self._llm.predict(summary_template, context_str=text_chunks[0],
                                     **response_kwargs)

        # 同步递归：逐块总结，再把总结当作新的 chunk 继续（与库同构）
        summaries = [
            self._llm.predict(summary_template, context_str=chunk, **response_kwargs)
            for chunk in text_chunks
        ]
        return self.get_response(query_str, summaries, **response_kwargs)

    # `synthesize` 继承基类（库的 TreeSummarize 同样不覆盖它）
