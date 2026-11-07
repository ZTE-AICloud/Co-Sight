"""图谱详情里的全量实体/关系数（``stats``）。

基本信息页要显示「图谱实际有多少实体/关系」，而不是当前查询结果的长度
（那个会被类型筛选、关键词和 ``limit`` 截断）。这里钉住三件事：

1. ``graph_pg.count_entities_and_edges`` 数的是物理行，表不存在时返回 ``None``；
2. 只有图谱库（``category=10``）才去数，文档库不碰图存储；
3. 计数失败不能把详情接口带崩 —— ``stats`` 退化为 ``None``，页面回落。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_graph_stats.py -q
"""

from __future__ import annotations

import pytest

from graph.repository import graph_pg
from graph.service import lifecycle
from knowledge_base.service import kbase_v2_service


class _FakeCursor:
    def __init__(self, result=(5, 2)):
        self.sql = ''
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self.result


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


def test_count_uses_physical_rows_of_both_graph_tables(monkeypatch):
    cursor = _FakeCursor(result=(7, 3))
    monkeypatch.setattr(graph_pg, 'is_database_exists', lambda client: True)
    monkeypatch.setattr(graph_pg, '_connect', lambda: _FakeConn(cursor))

    stats = graph_pg.count_entities_and_edges('graph_demo')

    assert stats == {'entityCount': 7, 'edgeCount': 3}
    assert 'kb_index.graph_demo_vertex' in cursor.sql
    assert 'kb_index.graph_demo_edge' in cursor.sql


def test_count_returns_none_when_graph_tables_do_not_exist(monkeypatch):
    monkeypatch.setattr(graph_pg, 'is_database_exists', lambda client: False)
    opened = []
    monkeypatch.setattr(graph_pg, '_connect', lambda: opened.append(True))

    assert graph_pg.count_entities_and_edges('graph_missing') is None
    assert opened == []


def test_lifecycle_prefixes_plain_kbase_ids(monkeypatch):
    seen = []
    monkeypatch.setattr(graph_pg, 'count_entities_and_edges',
                        lambda dbname: seen.append(dbname) or {'entityCount': 1,
                                                               'edgeCount': 1})

    lifecycle.count_graph_entities_and_edges('demo')
    lifecycle.count_graph_entities_and_edges('graph_demo')

    # 已带前缀的 id 不能被拼成 graph_graph_demo
    assert seen == ['graph_demo', 'graph_demo']


def _patch_detail(monkeypatch, *, category):
    monkeypatch.setattr(kbase_v2_service.kbase_service, 'get_kbase_detail',
                        lambda kb_id: {'id': kb_id, 'schemaObj': {}})
    monkeypatch.setattr(kbase_v2_service.kbase_service, 'get_kbase_row',
                        lambda kb_id: {'category': category})
    monkeypatch.setattr(kbase_v2_service, '_search_file_by_kb_id', lambda kb_id: [])


def test_graph_detail_carries_full_counts(monkeypatch):
    _patch_detail(monkeypatch, category=10)
    calls = []
    monkeypatch.setattr(
        kbase_v2_service.graph_lifecycle, 'count_graph_entities_and_edges',
        lambda kb_id: calls.append(kb_id) or {'entityCount': 42, 'edgeCount': 17})

    detail = kbase_v2_service.get_kbase_detail('kb-1')

    assert detail['stats'] == {'entityCount': 42, 'edgeCount': 17}
    assert calls == ['kb-1']


def test_document_detail_does_not_touch_graph_storage(monkeypatch):
    _patch_detail(monkeypatch, category=1)
    monkeypatch.setattr(
        kbase_v2_service.graph_lifecycle, 'count_graph_entities_and_edges',
        lambda kb_id: pytest.fail('document KB must not count graph rows'))

    detail = kbase_v2_service.get_kbase_detail('kb-1')

    assert detail['stats'] is None


def test_count_failure_does_not_break_detail(monkeypatch):
    _patch_detail(monkeypatch, category=10)

    def boom(kb_id):
        raise RuntimeError('storage down')

    monkeypatch.setattr(kbase_v2_service.graph_lifecycle,
                        'count_graph_entities_and_edges', boom)

    detail = kbase_v2_service.get_kbase_detail('kb-1')

    assert detail['stats'] is None
    assert detail['data']['id'] == 'kb-1'
