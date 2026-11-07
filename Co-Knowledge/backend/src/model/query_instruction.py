"""文档检索的查询侧 instruction（Qwen3-Embedding 等模型的非对称用法）。

Qwen3-Embedding 的 MTEB 分数是在「query 带 instruction、document 不带」的
非对称用法下测的；不带 instruction 会退化成普通句向量。NFCorpus 实测
nDCG@10 30.26% → 35.89%（公开值 36.71%），SciFact 也有小幅收益。

图谱检索在 ``graph_query_service`` 里有自己的 instruction
（``GRAPH_QUERY_INSTRUCTION``，实体召回口径）；文档检索用下面这份。

只对 Qwen3 系默认开启，避免给 BGE 等模型套错指令；部署可用
``EMBEDDING_QUERY_INSTRUCTION`` 显式覆盖（置空 = 关闭）。
"""

from __future__ import annotations

import os

DEFAULT_QWEN3_INSTRUCTION = (
    'Instruct: Given a web search query, retrieve relevant passages that '
    'answer the query\nQuery: '
)


def _configured_instruction() -> str | None:
    value = os.environ.get('EMBEDDING_QUERY_INSTRUCTION')
    if value is None:
        return None
    return value


def instruction_for(model_name: str) -> str:
    """按模型名给查询 instruction；未知模型默认不加。"""
    configured = _configured_instruction()
    if configured is not None:
        return configured
    lowered = (model_name or '').lower()
    if 'qwen3-embedding' in lowered:
        return DEFAULT_QWEN3_INSTRUCTION
    return ''


def apply_query_instruction(text: str, model_name: str) -> str:
    """幂等：已经以 ``Instruct:`` 开头的查询不重复拼。"""
    instruction = instruction_for(model_name)
    if not instruction or (text or '').lstrip().startswith('Instruct:'):
        return text
    return instruction + text
