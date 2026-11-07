"""检索器包：`RagNodeWithScore` 从这里转出（历史导入路径，勿删）。

`RagNodeWithScore` 本体已随 P4 迁到自研原语层（`primitives/models.py`），但
**大量 vendored 代码与测试仍按 `from engine.retriever import
RagNodeWithScore` 导入** —— 这是被冻结的 ABI，本模块只做转出。
"""
from engine.primitives.models import (  # noqa: F401
    BaseNode,
    NodeWithScore,
    RagNodeWithScore,
)
