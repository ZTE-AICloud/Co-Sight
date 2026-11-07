"""自研编排原语：组件实现（替代库内置组件）。

| 原库组件 | 本包对位 | 本仓谁在用 |
|---|---|---|
| `LLMSingleSelector`（+ 两个私有函数） | `selector.SingleSelector` / `_build_choices_text` / `_structured_output_to_selector_result` | `pre_retriever/query_selector/*` |
| `SelectionOutputParser` | `selector.SelectionOutputParser` | 同上（经 `from_defaults` 装配） |
| `LLMRerank` + 两个默认函数 | `rerank.LLMRerank` / `default_format_node_batch_fn` / `default_parse_choice_select_answer_fn` | `post_retriever/llm_reranker.py` |
| `QueryFusionRetriever` + `FUSION_MODES` | `fusion.QueryFusionRetriever` / `FUSION_MODES` | `retriever/fusion_retriever.py` |
| `TransformQueryEngine` / `RetrieverQueryEngine` / `RouterQueryEngine` | `query_engine.*`（含 `combine_responses`） | `query_engine/*` |
| `SimpleSummarize` / `TreeSummarize` / `"Empty Response"` | `summarizer.*` | `response_synthesizer/*`、路由器多选合并 |
| `PromptHelper.truncate` + `TokenTextSplitter` | `token_split.*`（词表随包 vendor） | 合成路径的截断 |

许可：默认 prompt 文本、`FORMAT_STR`、`"Empty Response"` 哨兵与若干保持一致的
算法/格式来自 llama-index-core 0.10.31（MIT License, Copyright (c) Jerry Liu）；
各文件为本仓独立重写实现。完整许可文本见仓库根目录 `THIRD-PARTY-NOTICES.md`。
"""
from engine.primitives.components.fusion import (  # noqa: F401
    FUSION_MODES,
    QUERY_GEN_PROMPT,
    QueryFusionRetriever,
)
from engine.primitives.components.query_engine import (  # noqa: F401
    RetrieverQueryEngine,
    RouterQueryEngine,
    TransformQueryEngine,
    combine_responses,
)
from engine.primitives.components.rerank import (  # noqa: F401
    LLMRerank,
    default_format_node_batch_fn,
    default_parse_choice_select_answer_fn,
)
from engine.primitives.components.selector import (  # noqa: F401
    Answer,
    SelectionOutputParser,
    SingleSelector,
    StructuredOutput,
    _build_choices_text,
    _structured_output_to_selector_result,
)
from engine.primitives.components.summarizer import (  # noqa: F401
    SimpleSummarize,
    TreeSummarize,
    empty_response_generator,
)
from engine.primitives.components.token_split import (  # noqa: F401
    PromptHelper,
    TokenizerTextSplitter,
    get_tokenizer,
)
