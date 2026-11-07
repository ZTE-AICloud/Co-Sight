"""自研编排原语：LLM 重排（`LLMRerank` 的对位实现）。

替代 llama-index-core 0.10.31 的 `postprocessor/llm_rerank.py`（`LLMRerank`）+
`indices/utils.py` 的两个默认函数（`default_format_node_batch_fn` /
`default_parse_choice_select_answer_fn`）。

**语义**：
  * batch 文本：`"Document {n}:\\n" + get_content(MetadataMode.LLM)`，`"\\n\\n"` 连接；
  * 解析：按行 `","` 切；`"{num}: {rel}"` 两侧各一次 split(":")；`> num_choices` 的行丢弃；
    相关性取冒号后**第一个整数**（正则 `\\d+`）；坏行默认跳过（`raise_error=False`）；
  * 默认 prompt 是 `DEFAULT_CHOICE_SELECT_PROMPT_TMPL`（画布 kwargs 里没有 prompt 键，
    恒用默认 —— 见 `llm_reranker.py:18-20`）。

**构造期严格性**：库侧 `top_n` 是 pydantic `int` 字段 —— `None`/缺失在构造期就报错
（指纹 `probes.rerank_top_n_*` 记录了这一行为，语义是"画布漏配必须显式失败，
不许静默变成 `[:None]` 返回全部节点"）。这里用显式校验保留该语义，但**不复制
pydantic 的报错文本**（那属于实现细节；指纹探测只对比"是否拒绝"）。
"""
from __future__ import annotations

import re
from typing import Any, Callable, List, Optional, Tuple

from engine.primitives.interfaces import RagNodePostprocessor
from engine.primitives.models import MetadataMode, NodeWithScore, QueryBundle
from engine.primitives.prompts import DEFAULT_CHOICE_SELECT_PROMPT_TMPL
from engine.primitives.templating import PromptTemplate, PromptType


def default_format_node_batch_fn(summary_nodes: List[Any]) -> str:
    """库实现：逐个 `"Document {i+1}:\\n" + LLM 模式的 get_content`，`"\\n\\n"` 连接。"""
    fmt_node_txts = []
    for idx in range(len(summary_nodes)):
        number = idx + 1
        fmt_node_txts.append(
            f'Document {number}:\n'
            f'{summary_nodes[idx].get_content(metadata_mode=MetadataMode.LLM)}'
        )
    return '\n\n'.join(fmt_node_txts)


def default_parse_choice_select_answer_fn(
        answer: str, num_choices: int, raise_error: bool = False,
) -> Tuple[List[int], List[float]]:
    """库实现：解析 `Doc: 1, Relevance: 9` 形式的作答（坏行默认跳过）。"""
    answer_lines = answer.split('\n')
    answer_nums: List[int] = []
    answer_relevances: List[float] = []
    for answer_line in answer_lines:
        line_tokens = answer_line.split(',')
        if len(line_tokens) != 2:
            if not raise_error:
                continue
            raise ValueError(
                f'Invalid answer line: {answer_line}. '
                'Answer line must be of the form: '
                'answer_num: <int>, answer_relevance: <float>'
            )
        answer_num = int(line_tokens[0].split(':')[1].strip())
        if answer_num > num_choices:
            continue
        answer_nums.append(answer_num)
        # extract just the first digits after the colon.
        _answer_relevance = re.findall(r'\d+', line_tokens[1].split(':')[1].strip())[0]
        answer_relevances.append(float(_answer_relevance))
    return answer_nums, answer_relevances


class LLMRerank(RagNodePostprocessor):
    """`LLMRerank` 的对位实现（字段名与库一致，供 vendored 子类复用）。"""

    def __init__(
            self,
            llm: Optional[Any] = None,
            choice_select_prompt: Optional[PromptTemplate] = None,
            choice_batch_size: int = 10,
            format_node_batch_fn: Optional[Callable] = None,
            parse_choice_select_answer_fn: Optional[Callable] = None,
            top_n: int = 10,
    ) -> None:
        if top_n is None:
            # 库的 pydantic 字段在此拒绝 None；这里是同一语义的显式版本（报错文本不同）
            raise ValueError('top_n 不能为 None：画布算子漏配 top_n（原库由 pydantic 在构造期拒绝）')
        self.top_n = int(top_n)
        self.llm = llm
        self.choice_select_prompt = choice_select_prompt or PromptTemplate(
            DEFAULT_CHOICE_SELECT_PROMPT_TMPL, prompt_type=PromptType.CHOICE_SELECT)
        self.choice_batch_size = choice_batch_size
        self._format_node_batch_fn = format_node_batch_fn or default_format_node_batch_fn
        self._parse_choice_select_answer_fn = (
            parse_choice_select_answer_fn or default_parse_choice_select_answer_fn)

    def _postprocess_nodes(
            self,
            nodes: List[NodeWithScore],
            query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        """与库实现一致（注意：库此处的返回值**不带** base_name，本仓子类自行补）。"""
        if query_bundle is None:
            raise ValueError('Query bundle must be provided.')
        if len(nodes) == 0:
            return []

        initial_results: List[NodeWithScore] = []
        for idx in range(0, len(nodes), self.choice_batch_size):
            nodes_batch = [node.node for node in nodes[idx: idx + self.choice_batch_size]]

            query_str = query_bundle.query_str
            fmt_batch_str = self._format_node_batch_fn(nodes_batch)
            raw_response = self.llm.predict(
                self.choice_select_prompt,
                context_str=fmt_batch_str,
                query_str=query_str,
            )

            raw_choices, relevances = self._parse_choice_select_answer_fn(
                raw_response, len(nodes_batch))
            choice_idxs = [int(choice) - 1 for choice in raw_choices]
            choice_nodes = [nodes_batch[idx] for idx in choice_idxs]
            relevances = relevances or [1.0 for _ in choice_nodes]
            initial_results.extend(
                [NodeWithScore(node=node, score=relevance)
                 for node, relevance in zip(choice_nodes, relevances)]
            )

        return sorted(initial_results, key=lambda x: x.score or 0.0, reverse=True)[: self.top_n]
