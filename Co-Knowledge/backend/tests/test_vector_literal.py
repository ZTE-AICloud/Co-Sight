"""pgvector 文本字面量：批量导入的 fast 版本必须与逐值比对版存成同一组 float32。"""
import random
import struct

from shared.chunk_schema.vector import to_vector_literal, to_vector_literal_fast


def _float32(text: str) -> list[float]:
    return [struct.unpack('f', struct.pack('f', float(part)))[0]
            for part in text[1:-1].split(',')]


def test_fast_literal_empty_and_basic():
    assert to_vector_literal_fast([]) == '[]'
    assert to_vector_literal_fast([0.1, -2.5]) == '[0.1,-2.5]'


def test_fast_literal_round_trips_same_float32():
    rng = random.Random(20261030)
    values = [rng.uniform(-1, 1) for _ in range(1024)]
    assert _float32(to_vector_literal_fast(values)) == _float32(to_vector_literal(values))
