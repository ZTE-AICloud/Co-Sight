"""Deployment model capabilities read from environment variables.

These values are deployment attributes with a single definition point in
``deploy/.env`` (``GENERATION_MODELS`` / ``REASONING_MODELS`` /
``RERANK_URL``).  They live in the model domain because they describe which
models this deployment can run; workflow validation only consumes them.

Defaults mirror the deployment config in ``deploy/.env``; every value can be overridden
there.
"""

from __future__ import annotations

import os

DEFAULT_MODELS = (
    ('deepseek-chat', 'DeepSeek Chat'),
    ('deepseek-reasoner', 'DeepSeek Reasoner'),
)
DEFAULT_REASONING_MODELS = ('deepseek-reasoner', 'deepseek-r1', 'qwq-32b')
DEFAULT_RERANK_URL = ''
#: Fallback name used when ``RERANK_URL`` is set but ``RERANK_MODEL`` is not.
DEFAULT_RERANK_MODEL = 'bge-reranker-large'

ENV_MODELS = 'RKB_FLOW_LLM_MODELS'
ENV_REASONING_MODELS = 'RKB_FLOW_REASONING_MODELS'
ENV_RERANK_URL = 'RKB_RERANK_URL'
ENV_RERANK_MODEL = 'RERANK_MODEL'
#: 向量模型名（回落端点时用的那个）。``_MODEL_NAME`` 是「不指定名字时请求体里的名字」，
#: 未设置时与 ``EMBEDDING_MODEL`` 同义 —— 与 ``model.resolver._from_env`` 一致。
ENV_EMBEDDING_MODEL = 'EMBEDDING_MODEL'
ENV_EMBEDDING_MODEL_NAME = 'EMBEDDING_MODEL_NAME'
#: 未配 ``EMBEDDING_DIMENSION`` 时回落路径用的维度（与 ``model.resolver`` 一致）。
DEFAULT_EMBEDDING_DIMENSION = 768


def parse_models(raw: str | None) -> tuple:
    """``model=display;model=display`` -> ``((model, display), ...)``.

    A bare ``model`` without ``=`` uses the model name as its display name.
    """
    if not raw:
        return tuple(DEFAULT_MODELS)
    models = []
    for chunk in raw.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        if '=' in chunk:
            value, display = chunk.split('=', 1)
        else:
            value, display = chunk, chunk
        value, display = value.strip(), display.strip()
        if value:
            models.append((value, display or value))
    return tuple(models) if models else tuple(DEFAULT_MODELS)


def parse_reasoning_models(raw: str | None) -> tuple:
    if not raw:
        return tuple(DEFAULT_REASONING_MODELS)
    models = [item.strip() for item in raw.split(',') if item.strip()]
    return tuple(models) if models else tuple(DEFAULT_REASONING_MODELS)


def rerank_url(env: dict | None = None) -> str:
    source = os.environ if env is None else env
    return source.get(ENV_RERANK_URL) or DEFAULT_RERANK_URL


def rerank_model_name(env: dict | None = None) -> str:
    source = os.environ if env is None else env
    return source.get(ENV_RERANK_MODEL) or DEFAULT_RERANK_MODEL
