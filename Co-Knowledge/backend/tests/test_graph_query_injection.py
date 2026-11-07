"""图谱检索 SQL 参数化（P0 注入修复）的回归测试。

背景：``_query_chunks_by_ids`` 曾把 chunk_id 用 ``f"'{x}'"`` 直接拼进 SQL；
chunk_id 来自导入 zip 的实体属性，``/graph/import`` 在 ``AUTH_MODE=none``
下无需鉴权，且 psycopg2 无参数执行走 simple query protocol（可堆叠语句）。
本组测试钉住三件事：

1. 所有来自请求/导入数据的值只出现在 **params**，不出现在 SQL 文本；
2. ``base`` 只允许 ``graph_[A-Za-z0-9_]{1,64}``；
3. 非法 base 在触达数据库之前就被拒绝。

跑法::

    python -m pytest tests/test_graph_query_injection.py -q
"""

from __future__ import annotations

import pytest

import graph.service.graph_query_service as service_module
from graph.service.graph_query_service import (
    GraphQueryService,
    _build_retrieve_sql,
    _validate_graph_base,
)

BASE = 'graph_447a9eb5e8fd40b98e7d3f2045880ba5'


class _Captured:
    """记录参数化查询的实参。"""

    def __init__(self, result=(True, [])):
        self.calls = []
        self._result = result

    def __call__(self, sql, params):
        self.calls.append({'sql': sql, 'params': params})
        return self._result


def _service_with_capture(monkeypatch):
    capture = _Captured()
    monkeypatch.setattr(
        service_module._db_pool,
        'pg_select_zip_values_operator_with_params',
        capture,
    )
    service = GraphQueryService.__new__(GraphQueryService)
    return service, capture


# ----------------------------------------------------------------------
# base 白名单
# ----------------------------------------------------------------------


@pytest.mark.parametrize('base', [
    BASE,
    'graph_447a9eb5',
    'graph_0123456789abcdef0123456789abcdef',
    'graph_A_b9',
])
def test_graph_base_accepts_existing_shapes(base):
    assert _validate_graph_base(base) == base


@pytest.mark.parametrize('base', [
    '',
    'graph_',
    'graph_x; DROP TABLE kb_kbase',
    "graph_x' UNION SELECT 1 --",
    'graph_x y',
    'doc_447a9eb5',
    'graph_x/../y',
    None,
])
def test_graph_base_rejects_sql_metacharacters_and_other_prefixes(base):
    with pytest.raises(ValueError):
        _validate_graph_base(base)


# ----------------------------------------------------------------------
# 种子检索 SQL
# ----------------------------------------------------------------------


def test_build_retrieve_sql_binds_embedding_score_labels_and_limit():
    sql, params = _build_retrieve_sql(
        BASE, 'entity', "[0.1,0.2]' ; DROP TABLE kb_kbase --", 7, 0.25, ["a'", 'b'])

    # SQL 文本只有占位符，不包含任何值
    assert "[0.1,0.2]" not in sql
    assert "DROP TABLE" not in sql
    assert "a'" not in sql
    assert 'LIMIT %s' in sql
    assert 'key_type = %s' in sql
    assert 'labels && %s::text[]' in sql

    # 参数顺序：SELECT embedding → key_type → WHERE embedding → 距离上限 →
    # 可选 labels → ORDER BY embedding → LIMIT
    assert params == [
        "[0.1,0.2]' ; DROP TABLE kb_kbase --",
        'entity',
        "[0.1,0.2]' ; DROP TABLE kb_kbase --",
        0.75,
        ["a'", 'b'],
        "[0.1,0.2]' ; DROP TABLE kb_kbase --",
        7,
    ]


def test_build_retrieve_sql_without_labels_has_no_labels_clause():
    sql, params = _build_retrieve_sql(BASE, 'chunk', '[0.1]', 5, 0.0, None)
    assert 'labels' not in sql
    assert params == ['[0.1]', 'chunk', '[0.1]', 1.0, '[0.1]', 5]


def test_build_retrieve_sql_selects_edge_endpoints():
    """边身份改为 edge_id 后，端点必须随行取出，不能再拆 key_id。"""
    sql, _ = _build_retrieve_sql(BASE, 'edge', '[0.1]', 5, 0.0)
    assert 'source_id' in sql
    assert 'target_id' in sql


def test_extract_edge_endpoints_reads_columns_only():
    from graph.service.graph_query_service import GraphQueryService

    records = [{'key_id': 'R1', 'source_id': 'A', 'target_id': 'B'}]
    assert GraphQueryService._extract_entity_ids_from_records(
        None, records, 'edge') == ['A', 'B']
    # key_id 是 edge_id，不能拆成端点
    assert GraphQueryService._extract_entity_ids_from_records(
        None, [{'key_id': 'A,B'}], 'edge') == []


# ----------------------------------------------------------------------
# chunk 详情查询
# ----------------------------------------------------------------------


def test_query_chunks_by_ids_binds_ids_as_any_parameter(monkeypatch):
    service, capture = _service_with_capture(monkeypatch)
    payload = "x') UNION SELECT * FROM kb_kbase --"

    service._query_chunks_by_ids(BASE, ['c1', payload])

    assert len(capture.calls) == 1
    call = capture.calls[0]
    assert 'WHERE id = ANY(%s)' in call['sql']
    assert payload not in call['sql']
    assert call['params'] == (['c1', payload],)


def test_query_chunks_by_ids_rejects_illegal_base_before_db_call(monkeypatch):
    service, capture = _service_with_capture(monkeypatch)

    with pytest.raises(ValueError):
        service._query_chunks_by_ids("graph_x' OR 1=1 --", ['c1'])

    assert capture.calls == []


def test_retrieve_single_base_rejects_illegal_base_without_db_access(monkeypatch):
    service, capture = _service_with_capture(monkeypatch)
    # 任何数据库访问都应视为失败
    monkeypatch.setattr(service, 'check_kb_db_exists',
                        lambda *a, **k: pytest.fail('must not touch database'))

    result = service._retrieve_single_base("graph_x; DROP TABLE kb_kbase", '[0.1]', None, 'en')

    assert result['base'] == "graph_x; DROP TABLE kb_kbase"
    assert result['entities'] == []
    assert result['chunks'] == {}
    assert result.get('error') == 'Graph database does not exist'
    assert capture.calls == []


def test_retrieve_seed_ids_uses_fixed_chunk_top_k(monkeypatch):
    """chunk 种子固定 top_50；实体/边仍按 DTO 的 seed_k。"""
    from graph.models.graph_retrieve_dto import GraphRetrieveDto

    service = GraphQueryService.__new__(GraphQueryService)
    calls = []

    def _query(base, key_type, query_embedding, dto, seed_k=None):
        calls.append((key_type, seed_k))
        return []

    monkeypatch.setattr(service, '_query_vector_index', _query)
    dto = GraphRetrieveDto(query='q', embedding='m', bases=[BASE], seed_k=7)

    service._retrieve_seed_ids(BASE, '[0.1]', dto)

    assert calls == [('entity', None), ('edge', None), ('chunk', 50)]
