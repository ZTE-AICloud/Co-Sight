"""自研编排原语层 —— 替代 llama-index-core 在编排层的四类供给。

| 原库供给 | 本包对位 |
|---|---|
| `Node`/`TextNode`、`NodeWithScore`、`QueryBundle`、`Response`/`StreamingResponse`、`ToolMetadata`、`SelectorResult` | `models.py` |
| `BaseRetriever`/`BaseQueryEngine`/`BaseNodePostprocessor`/`BaseSynthesizer`/`BaseQueryTransform`/`BaseSelector` | `interfaces.py` |
| `PromptTemplate`/`SelectorPromptTemplate`/`ChatMessage`/`messages_to_prompt` | `templating.py` |
| 默认 prompt 文本（与上游一致，MIT 归属见文件头） | `prompts.py` |
| LLM 调用链（predict/stream 分派、token 提取） | `llm.py`（P2） |
| 组件实现（Router/Selector/融合/重排/合成/截断） | `components/`（P3） |

**边界（有意不做的）**：callback_manager / instrumentation 事件（全仓零订阅者）、
异步 `_a*` 变体、`PromptMixin`/`ChainableMixin`、`PromptHelper` 的 chunk 切分能力
（只实现 `truncate` 用到的一条路径）。

**许可**：默认 prompt 文本与若干保持一致的行为来自 llama-index-core 0.10.31
（MIT License, Copyright (c) Jerry Liu）。各文件为本仓独立重写实现。完整许可文本见仓库根目录
`THIRD-PARTY-NOTICES.md`。
"""
from engine.primitives.models import (  # noqa: F401
    DEFAULT_METADATA_SEPERATOR,
    DEFAULT_METADATA_TEMPLATE,
    DEFAULT_TEXT_TEMPLATE,
    MetadataMode,
    MultiSelection,
    Node,
    NodeWithScore,
    QueryBundle,
    QueryEngineTool,
    RagNodeWithScore,
    Response,
    SelectorResult,
    SingleSelection,
    StreamingResponse,
    TextNode,
    ToolMetadata,
)
from engine.primitives.interfaces import (  # noqa: F401
    RagNodePostprocessor,
    RagQueryEngine,
    RagQueryTransform,
    RagRetriever,
    RagSelector,
    RagSynthesizer,
)
from engine.primitives.templating import (  # noqa: F401
    BasePromptTemplate,
    ChatMessage,
    MessageRole,
    PromptTemplate,
    PromptType,
    SelectorPromptTemplate,
    get_template_vars,
    messages_to_prompt,
    prompt_to_messages,
)
