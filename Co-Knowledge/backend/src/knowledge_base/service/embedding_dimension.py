"""embedding 维度解析（建库/建图谱索引时用）。

### 为什么不能再用无维度 ``vector``

pgvector 的 HNSW/IVFFlat 构建代码要求列有固定维度，否则直接报
``column does not have dimensions``。无维度列等于**永远无法建 ANN 索引**，
每次检索只能全表扫描。

### 维度来源的唯一顺序

1. ``model_registry`` 里该 embedding 模型的 ``dimension``（**权威**）；
2. 环境变量 ``EMBEDDING_DIMENSION``（模型注册表不可用时的回落）；
3. ``DEFAULT_VECTOR_DIMENSION``（1024，与 deploy/.env 默认一致）。

模型名可能为空（历史库）；空值时同样走 2/3。解析失败**不阻断建库** ——
建库比「维度精确」更重要，后续写入时还会做一次维度校验。
"""

from __future__ import annotations

import os

from infrastructure.logging.logutil import log

DEFAULT_VECTOR_DIMENSION = 1024


def resolve_embedding_dimension(model_name: str | None,
                                default: int | None = None) -> int:
    """返回该 embedding 模型应使用的向量维度。"""
    if model_name:
        try:
            from model import resolver as model_resolver

            resolved = model_resolver.resolve('embedding', model_name)
            dimension = getattr(resolved, 'dimension', None)
            if dimension:
                return int(dimension)
        except Exception:                                          # noqa: BLE001
            log.warning('resolve embedding dimension failed for %r, falling back',
                        model_name, exc_info=True)

    raw = default if default is not None else os.environ.get('EMBEDDING_DIMENSION')
    try:
        dimension = int(raw) if raw not in (None, '') else DEFAULT_VECTOR_DIMENSION
    except (TypeError, ValueError):
        dimension = DEFAULT_VECTOR_DIMENSION
    return dimension if dimension > 0 else DEFAULT_VECTOR_DIMENSION


def ensure_known_embedding_model(
        model_name: str | None,
        *,
        error_key: str = 'kbase.embedding.model.invalid') -> None:
    """建库/建图**之前**校验模型名：必须会被写路径原样使用（可带维度地解析）。

    空值 = 跟随部署默认，不校验。

    为什么要在入库前拦住：解析不到的名字不会让写入失败，而是**静默换成** ``.env``
    的默认模型 —— 库里留下了 ``kb_kbase.embedding_model = <请求的名字>``，向量却是
    另一个模型算出来的。实际部署里出现过这种账实不符，直到用户点「发送」才炸成 502。

    「读不到注册表 / 本部署一个可写的模型都没配」= 无法判定，放行（与校验链的
    其它安全阀一致）。

    :param error_key: 文案键。图谱抽取的既有接口用 ``graph.extract.embedding.model.invalid``
        保持契约不变，其余建库入口用默认键。
    :raises KbApiError: 0004（参数不合法，与建库的其它入参校验同一档）。
    """
    if not isinstance(model_name, str) or not model_name.strip():
        return
    from model import resolver as model_resolver
    from shared.errors.api import KbApiError

    name = model_name.strip()
    try:
        known = model_resolver.is_writable_embedding_model(name)
    except Exception:                                              # noqa: BLE001
        log.warning('embedding model check failed for %r, skip', name, exc_info=True)
        return
    if known is False:
        raise KbApiError(error_key, name, code='0004')
