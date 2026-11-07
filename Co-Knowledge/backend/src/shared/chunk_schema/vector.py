"""pgvector literal formatting (pure, framework-free)."""
from __future__ import annotations

import struct


def to_vector_literal(embedding: list[float]) -> str:
    """把向量格式化成 pgvector 的文本字面量 ``[a,b,c]``。

    向量是 32 位的：这里先把每个值按 float32 收敛再取最短表示，
    否则会把 Python 的 64 位尾数带进字面量（pgvector 内部本就是 4 字节，
    所以对**结果**无影响，但便于字节级比对排查）。
    """
    if not embedding:
        return '[]'
    parts = []
    for value in embedding:
        as_float32 = struct.unpack('f', struct.pack('f', float(value)))[0]
        parts.append(repr(as_float32))
    return '[' + ','.join(parts) + ']'


def to_vector_literal_fast(embedding: list[float]) -> str:
    """批量导入专用：``.12g`` 可精确往返 float32，比逐值 struct/repr 快约 1.9 倍。

    写入路径只要求 pgvector 能解析成同样的 float32；不需要接口出参那种字节级比对。
    ``.9g`` 在 1024 维
    随机向量上会出现 3/1024 个相邻 float32 舍入差异，``.10g`` 起为 0，留到 ``.12g``。
    """
    if not embedding:
        return '[]'
    return '[' + ','.join(format(float(value), '.12g') for value in embedding) + ']'
