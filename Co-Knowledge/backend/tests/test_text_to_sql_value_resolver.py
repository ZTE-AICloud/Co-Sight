"""查询时值解析：字面量提取与回库改写（不回连真实数据库）。"""

from __future__ import annotations

import psycopg2
import pytest

from text_to_sql import value_resolver
from text_to_sql.value_resolver import ValueResolutionError, extract_text_filters

DSN = {'host': 'db', 'port': 5432, 'database': 'demo', 'username': 'reader',
       'password': 'pwd'}

SNAPSHOT = {
    'datasource': {'name': 'Demo 数据源', 'database': 'demo'},
    'tables': [
        {
            'id': 't1', 'schema': 'public', 'name': 'orders',
            'columns': [
                {'id': 'c1', 'name': 'order_id', 'dataType': 'bigint'},
                {'id': 'c2', 'name': 'status', 'dataType': 'smallint'},
                {'id': 'c3', 'name': 'channel', 'dataType': 'character varying'},
                {'id': 'c4', 'name': 'city_id', 'dataType': 'bigint'},
            ],
        },
        {
            'id': 't2', 'schema': 'public', 'name': 'region_info',
            'columns': [
                {'id': 'c5', 'name': 'city_id', 'dataType': 'bigint'},
                {'id': 'c6', 'name': 'city_name', 'dataType': 'character varying'},
            ],
        },
    ],
}


class FakeCursor:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.rows = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if isinstance(self.responses, Exception):
            raise self.responses
        self.rows = self.responses.pop(0) if self.responses else []

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, responses):
        self.fake_cursor = FakeCursor(responses)
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


def _install(monkeypatch, responses):
    conn = FakeConnection(responses)
    monkeypatch.setattr(value_resolver, '_open_connection',
                        lambda connection, timeout_ms: conn)
    return conn


# ----------------------------------------------------------------------
# 提取
# ----------------------------------------------------------------------
def test_extract_resolves_alias_and_full_qualified_text_columns():
    sql = ('SELECT * FROM public.orders o JOIN public.region_info ri '
           "ON o.city_id = ri.city_id WHERE ri.city_name = '西安'")

    filters = extract_text_filters(sql, SNAPSHOT)

    assert [(item.schema, item.table, item.column, item.value, item.mode)
            for item in filters] == [
        ('public', 'region_info', 'city_name', '西安', 'eq')]


def test_extract_handles_in_lists_and_skips_other_operators():
    sql = ("SELECT * FROM public.orders o "
           "WHERE o.channel IN ('线上', '线下') AND o.channel <> '未知' "
           "AND o.channel LIKE '线%' AND o.status = '2'")

    filters = extract_text_filters(sql, SNAPSHOT)

    assert [(item.column, item.value, item.mode) for item in filters] == [
        ('channel', '线上', 'in'), ('channel', '线下', 'in')]


def test_extract_handles_cte_and_unqualified_unique_column():
    cte = ("WITH x AS (SELECT city_id FROM public.region_info "
           "WHERE city_name = '西安') SELECT * FROM x")
    filters = extract_text_filters(cte, SNAPSHOT)
    assert [(item.table, item.column) for item in filters] == [('region_info', 'city_name')]

    unique = "SELECT * FROM public.region_info WHERE city_name = '西安'"
    assert extract_text_filters(unique, SNAPSHOT)[0].column == 'city_name'


def test_extract_skips_ambiguous_unqualified_and_commented_literals():
    snapshot = {
        'tables': [
            {'id': 'a', 'schema': 'public', 'name': 'orders',
             'columns': [
                 {'id': 'c1', 'name': 'name', 'dataType': 'text'},
                 {'id': 'c3', 'name': 'user_id', 'dataType': 'bigint'},
             ]},
            {'id': 'b', 'schema': 'public', 'name': 'users',
             'columns': [
                 {'id': 'c2', 'name': 'name', 'dataType': 'text'},
                 {'id': 'c4', 'name': 'user_id', 'dataType': 'bigint'},
             ]},
        ],
    }
    single = "SELECT * FROM public.orders WHERE name = 'x'"
    assert [item.column for item in extract_text_filters(single, snapshot)] == ['name']

    joined = ("SELECT * FROM public.orders o JOIN public.users u "
              "ON o.user_id = u.user_id WHERE name = 'x'")
    assert extract_text_filters(joined, snapshot) == []

    commented = ("SELECT * FROM public.region_info "
                 "-- WHERE city_name = '西安'")
    assert extract_text_filters(commented, SNAPSHOT) == []


# ----------------------------------------------------------------------
# 回库改写
# ----------------------------------------------------------------------
def test_resolve_rewrites_unique_partial_match(monkeypatch):
    conn = _install(monkeypatch, [[], [], [('西安市',)]])
    sql = "SELECT * FROM public.region_info WHERE city_name = '西安'"

    rewritten, evidence = value_resolver.resolve_and_rewrite(DSN, sql, SNAPSHOT)

    assert "city_name = '西安市'" in rewritten
    assert evidence == [{
        'schema': 'public', 'table': 'region_info', 'column': 'city_name',
        'from': '西安', 'value': '西安市', 'match': 'resolved'}]
    assert conn.closed is True


def test_resolve_raises_ambiguous_with_candidates(monkeypatch):
    _install(monkeypatch, [[], [], [('西安市',), ('西安区',)]])
    sql = "SELECT * FROM public.region_info WHERE city_name = '西安'"

    with pytest.raises(ValueResolutionError) as error:
        value_resolver.resolve_and_rewrite(DSN, sql, SNAPSHOT)

    assert error.value.code == 'VALUE_AMBIGUOUS'
    assert error.value.candidates == ['西安市', '西安区']


def test_resolve_raises_when_value_missing(monkeypatch):
    _install(monkeypatch, [[], [], [], []])
    sql = "SELECT * FROM public.region_info WHERE city_name = '不存在'"

    with pytest.raises(ValueResolutionError) as error:
        value_resolver.resolve_and_rewrite(DSN, sql, SNAPSHOT)

    assert error.value.code == 'VALUE_NOT_FOUND'
    assert '不存在' in error.value.message
    assert 'Demo 数据源 demo' in error.value.message


def test_resolve_keeps_original_sql_on_lookup_error(monkeypatch):
    _install(monkeypatch, psycopg2.Error())
    sql = "SELECT * FROM public.region_info WHERE city_name = '西安'"

    rewritten, evidence = value_resolver.resolve_and_rewrite(DSN, sql, SNAPSHOT)

    assert rewritten == sql
    assert evidence[0]['match'] == 'skipped'


def test_resolve_skips_text_without_filters(monkeypatch):
    monkeypatch.setattr(value_resolver, '_open_connection',
                        lambda connection, timeout_ms: pytest.fail('不应连接数据库'))
    sql = 'SELECT COUNT(*) FROM public.orders WHERE status = 2'

    rewritten, evidence = value_resolver.resolve_and_rewrite(DSN, sql, SNAPSHOT)

    assert rewritten == sql
    assert evidence == []
