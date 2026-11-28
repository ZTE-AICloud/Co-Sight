"""知识文本的向量化。

端点与模型名都由模型注册表解析（``model.gateway.embed_many``），不在本域写死；
整批一次 HTTP 请求，维度由版本行声明、写入前校验。
"""

from __future__ import annotations


class IndexingError(RuntimeError):
    """批量向量化失败。"""


def embed_texts(texts: list[str], model: str) -> list[list[float]]:
    from model.gateway import embed_many

    try:
        embeddings = embed_many(texts, model)
    except Exception as error:                                     # noqa: BLE001
        raise IndexingError(str(error)) from error
    if len(embeddings) != len(texts):
        raise IndexingError('embedding 返回数量与输入不一致')
    return embeddings
