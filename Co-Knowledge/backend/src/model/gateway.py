"""model-gateway 的 embedding 调用（检索入参向量化）。

* 模型解析：``model`` 先在**模型注册表**里找（模型管理页可注册自建端点），
  命中且带 ``dimension`` 就用那条的端点/模型名/维度；否则整体回落到 ``.env``
  配置的默认模型（``EMBEDDING_MODEL`` / ``EMBEDDING_DIMENSION``）。
* 请求：``POST {url}{path}``，体 ``{"input": ["<question>"], "model": <model_code>}``，
  ``Authorization: Bearer <api-key>`` 仅在 key 非空时带上。
* 维度校验：不匹配直接抛错（**不截断不补零**）。

**刻意不走 ``LlmProxyClient``**：embedding 直连 ``MODEL_GATEWAY_URL``，
HTTP 行为保持稳定，不要随手改动请求形状。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from infrastructure.http import egress
from infrastructure.logging.logutil import log

DEFAULT_MODEL = 'BAAI/bge-base-zh-v1.5'
DEFAULT_DIMENSION = 768
TIMEOUT_SECONDS = 60


class EmbeddingError(Exception):
    """embedding 失败（网关不可用 / 响应畸形 / 维度不符）—— 由上层收敛成 bo=[]。"""


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


@dataclass(frozen=True)
class EmbeddingTarget:
    """一次向量化要用的全部参数（**含端点**，不只是模型名与维度）。

    端点也可能来自模型注册表（模型管理页可注册自建端点），
    所以解析结果不能再只是 ``(model_code, dimension)`` 两元组。
    """

    #: 发给端点的 ``model`` 字段
    api_model: str
    #: 期望维度（**校验基准**：不匹配显式报错，契约禁止静默截断/补零）
    dimension: int
    url: str
    api_key: str = ''
    #: 注册名（排障用：报错信息里给这个，而不是发给端点那个）
    model_name: str = ''
    #: ``registry`` / ``env`` —— 症状是「注册了模型却没生效」时先看这个
    origin: str = 'env'


def _env_default_model() -> tuple[str, int]:
    """回落目标：``.env`` 的默认模型与维度。"""
    return (_env('EMBEDDING_MODEL', DEFAULT_MODEL),
            int(_env('EMBEDDING_DIMENSION', str(DEFAULT_DIMENSION))))


def resolve_model(requested_model: str | None) -> EmbeddingTarget:
    """解析向量化目标：**注册表优先，回落 ``.env`` 默认模型**。

    先问 ``model_resolver``（它读注册表，读不到会自己回落到 ``.env`` 的端点）。
    命中的行必须带维度 —— 维度是建表与写入的基准，缺了它就等于「静默用错维度」，
    宁可退回默认模型。`kb_embedding` 表已不存在，不再有第二层按表查。
    """
    from model import resolver as model_resolver

    endpoint = model_resolver.resolve('embedding', requested_model)
    if endpoint.origin == 'registry' and endpoint.dimension:
        return EmbeddingTarget(
            api_model=endpoint.api_model, dimension=int(endpoint.dimension),
            url=endpoint.url, api_key=endpoint.api_key,
            model_name=endpoint.model_name, origin='registry')

    model_code, dimension = _env_default_model()
    # 回落时的端点取 .env（model_resolver 的 env 分支）；模型名与维度按 .env 解析
    fallback = model_resolver.resolve('embedding', model_code)
    return EmbeddingTarget(
        api_model=model_code, dimension=dimension,
        url=fallback.url, api_key=fallback.api_key,
        model_name=(requested_model or '').strip() or model_code,
        origin='env' if fallback.origin == 'env' else fallback.origin)


def embed(question: str, requested_model: str | None) -> list[float]:
    """单条向量化（``doEmbedding(String)``）。失败一律抛 :class:`EmbeddingError`。

    ⚠️ 这个函数**不加查询 instruction**：``chunk_service`` 也用它做切片入库。
    检索查询请用 :func:`embed_query`。
    """
    return embed_many([question], requested_model)[0]


def embed_query(question: str, requested_model: str | None) -> list[float]:
    """检索查询向量化：按模型拼查询 instruction（documents 侧不拼）。"""
    from model.query_instruction import apply_query_instruction

    target = resolve_model(requested_model)
    text = apply_query_instruction(question, target.model_name or target.api_model)
    return embed(text, requested_model)


def embed_many(texts: list[str], requested_model: str | None) -> list[list[float]]:
    """**整批**向量化（``doEmbedding(List<String>, model)``）—— **一次 HTTP 请求**。

    ⚠️ 这里必须整批发，别在调用方逐条循环：网关的 embedding 接口接受数组，
    逐条发是 N 倍请求量 —— 跑一个文件就是几十上百次 HTTP，把远端网关的每次抖动
    都放大成一次任务失败风险（``FileEmbeddingHandler`` 一失败就回滚整条链）。
    批量发同时也快得多。

    ⚠️ 排查提示:网关对**本栈没有的模型名**直接回 404（实测 ``bge-base-zh-v1.5``
    在远端确定性 404、``Qwen3-Embedding-0.6B`` 200）—— 文件任务报 404 时先核对
    ``kb_kbase.embedding_model`` 那一列，别急着当网关抖动。

    返回值与入参**同序**（按响应里的 ``index`` 排；网关不给 ``index`` 就按响应顺序）。
    """
    items = list(texts or [])
    if not items:
        return []
    target = resolve_model(requested_model)
    expected_dimension = target.dimension

    url = target.url
    headers = {'Content-Type': 'application/json'}
    if target.api_key:
        headers['Authorization'] = f'Bearer {target.api_key}'

    try:
        response = egress.post(
            url, json={'input': items, 'model': target.api_model},
            headers=headers, timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        log.exception('embedding gateway call failed')
        raise EmbeddingError(f'embedding gateway unavailable: {error}') from error

    data = payload.get('data') or []
    if len(data) != len(items):
        # 条数对不上就是坏的：宁可报错也别把向量错位写进库
        raise EmbeddingError(
            f'embedding gateway returned {len(data)} vectors for {len(items)} inputs')

    ordered = sorted(data, key=lambda item: item.get('index', 0)) \
        if all('index' in item for item in data) else data

    vectors: list[list[float]] = []
    for item in ordered:
        embedding = item.get('embedding')
        if not embedding:
            raise EmbeddingError('embedding gateway returned empty data')
        if len(embedding) != expected_dimension:
            raise EmbeddingError(
                f'embedding dimension mismatch: expected {expected_dimension}, '
                f'got {len(embedding)}')
        vectors.append(embedding)
    return vectors
