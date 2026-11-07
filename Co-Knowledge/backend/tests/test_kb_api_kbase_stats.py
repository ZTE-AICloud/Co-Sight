"""``GET /knowledge-bases/stats`` 的测试。

覆盖三层：

1. store 的聚合 SQL 口径（两分组结果合到同一个分类下、过滤参数只拼一次）；
2. 路由顺序 —— `/knowledge-bases/stats` 必须排在 `/knowledge-bases/{kbase_id}` 之前，
   否则 ``stats`` 会被当成库 id 进详情端点；
3. 服务层补零与分类顺序（请求了但库里没有的分类返回全零）。

不连库：``kbase_store`` 的查询函数用假的替换掉，这一层验的是契约而不是 SQL 执行。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import http_api as kb_router
from knowledge_base.repository import kbase as kbase_store


class _FakeCursor:
    def __init__(self, results):
        self._results = list(results)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.queries.append((sql, params))

    def fetchall(self):
        return self._results.pop(0)


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor


@pytest.fixture()
def client():
    app = FastAPI()
    kb_router.register_rkb_api(app)
    return TestClient(app)


def _stats_url(query: str = '') -> str:
    return f'{kb_router.KBASE_PREFIX}/knowledge-bases/stats{query}'


# ----------------------------------------------------------------------
# store：聚合口径
# ----------------------------------------------------------------------


def test_summarize_kbases_merges_status_and_file_rows_per_category(monkeypatch):
    cursor = _FakeCursor([
        [(1, '0', 3), (1, '103', 1), (10, '5', 2)],
        [(1, 64), (10, 0)],
    ])
    monkeypatch.setattr(kbase_store, 'connection', lambda: _FakeConnection(cursor))

    summary = kbase_store.summarize_kbases([1, 10], org_id='org-1')

    assert summary == {
        1: {'total': 4, 'fileTotal': 64, 'statusCounts': {'0': 3, '103': 1}},
        10: {'total': 2, 'fileTotal': 0, 'statusCounts': {'5': 2}},
    }
    # 两条 SQL 的过滤条件必须一致（org + categories），否则指标卡与列表对不上
    assert cursor.queries[0][1] == ['org-1', [1, 10]]
    assert cursor.queries[1][1] == ['org-1', [1, 10]]
    # 没有逻辑删除：查询里不应有 is_enabled 条件
    assert "is_enabled" not in cursor.queries[1][0]
    assert "d.type = 'file'" in cursor.queries[1][0]


def test_summarize_kbases_without_categories_adds_no_category_filter(monkeypatch):
    cursor = _FakeCursor([[], []])
    monkeypatch.setattr(kbase_store, 'connection', lambda: _FakeConnection(cursor))

    assert kbase_store.summarize_kbases(None) == {}
    assert cursor.queries[0][1] == []
    assert 'category = ANY' not in cursor.queries[0][0]


# ----------------------------------------------------------------------
# 路由 / 服务：顺序、补零、参数解析
# ----------------------------------------------------------------------


def test_stats_route_is_matched_before_kbase_detail(client, monkeypatch):
    """`/knowledge-bases/stats` 不能被 `/{kbase_id}` 抢走。

    排在详情端点后面时，这里会调用 ``select_kbase_by_id('stats')`` 并回业务错误；
    断言聚合函数被调用即可证明命中的是 stats 路由。
    """
    captured = {}

    def fake_summarize(categories, org_id=None):
        captured['categories'] = categories
        captured['org_id'] = org_id
        return {1: {'total': 1, 'fileTotal': 2, 'statusCounts': {'0': 1}}}

    monkeypatch.setattr(kbase_store, 'summarize_kbases', fake_summarize)
    body = client.get(_stats_url('?categories=1')).json()

    assert body['categories'] == [
        {'category': 1, 'total': 1, 'fileTotal': 2, 'statusCounts': {'0': 1}},
    ]
    assert captured == {'categories': [1], 'org_id': ''}


def test_stats_zero_fills_requested_category_missing_from_store(client, monkeypatch):
    monkeypatch.setattr(
        kbase_store, 'summarize_kbases',
        lambda categories, org_id=None: {
            1: {'total': 6, 'fileTotal': 64, 'statusCounts': {'0': 5, '103': 1}},
        },
    )

    body = client.get(_stats_url('?categories=10,1')).json()

    # 顺序跟请求走；10 库里没有数据也要返回全零，前端不必自己兜默认值
    assert body['categories'] == [
        {'category': 10, 'total': 0, 'fileTotal': 0, 'statusCounts': {}},
        {'category': 1, 'total': 6, 'fileTotal': 64, 'statusCounts': {'0': 5, '103': 1}},
    ]


def test_stats_without_categories_returns_all_present_sorted(client, monkeypatch):
    monkeypatch.setattr(
        kbase_store, 'summarize_kbases',
        lambda categories, org_id=None: {
            10: {'total': 3, 'fileTotal': 0, 'statusCounts': {'5': 3}},
            1: {'total': 6, 'fileTotal': 64, 'statusCounts': {'0': 6}},
        },
    )

    body = client.get(_stats_url()).json()

    assert [item['category'] for item in body['categories']] == [1, 10]


def test_stats_passes_org_header_to_store(client, monkeypatch):
    captured = {}

    def fake_summarize(categories, org_id=None):
        captured['org_id'] = org_id
        return {}

    monkeypatch.setattr(kbase_store, 'summarize_kbases', fake_summarize)
    client.get(_stats_url('?categories=1'), headers={'x-org-id': 'org-42'})

    assert captured['org_id'] == 'org-42'


def test_stats_rejects_non_numeric_categories_with_kb_envelope(client):
    body = client.get(_stats_url('?categories=abc')).json()

    # 参数绑定失败 → 400 malformed_request
    assert body['code'] == 'malformed_request'
