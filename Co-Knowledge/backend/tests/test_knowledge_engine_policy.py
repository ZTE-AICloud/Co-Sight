"""执行策略：行数/字节上限与缺省值。"""

from knowledge_engine import policy as engine_policy


def test_policy_defaults_match_text2sql_contract():
    limits = engine_policy.ExecutionPolicy.from_mapping({})
    assert limits.max_rows == 1000
    assert limits.timeout_ms == 30000
    assert limits.max_bytes == 1024 * 1024


def test_policy_reads_mapping_and_ignores_unknown_keys():
    limits = engine_policy.ExecutionPolicy.from_mapping(
        {'max_rows': 5, 'timeout_ms': 1000, 'max_bytes': 50, 'read_only': False})
    assert (limits.max_rows, limits.timeout_ms, limits.max_bytes) == (5, 1000, 50)


def test_encode_rows_stops_at_row_limit():
    rows, truncated = engine_policy.encode_rows(
        [[index] for index in range(10)],
        engine_policy.ExecutionPolicy(max_rows=3))
    assert rows == [[0], [1], [2]]
    assert truncated is False


def test_encode_rows_stops_at_byte_limit():
    # 第一行约 402 字节，放进 500 字节预算；第二行再加就超了。
    rows, truncated = engine_policy.encode_rows(
        [['x' * 400], ['y' * 400]], engine_policy.ExecutionPolicy(max_bytes=500))
    assert len(rows) == 1
    assert truncated is True


def test_encode_rows_drops_row_that_alone_exceeds_budget():
    rows, truncated = engine_policy.encode_rows(
        [['x' * 5000]], engine_policy.ExecutionPolicy(max_bytes=100))
    assert rows == []
    assert truncated is True


def test_encode_rows_uses_domain_converter():
    rows, _ = engine_policy.encode_rows(
        [('a', 'b')], engine_policy.ExecutionPolicy(),
        convert=lambda raw: [value.upper() for value in raw])
    assert rows == [['A', 'B']]
