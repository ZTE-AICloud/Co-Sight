"""API Key 调用计数：DDL、按日累加、7 天窗口与管理接口（不连 DB）。

背景：密钥管理页的「总调用量 / 最近 7 天请求数」两张卡片的数据来自本计数；
鉴权路径若只更新 ``last_used_at``、不做计数，两张卡片只能显示「—」。这里钉住四件事：

1. 计数表 DDL 在 ``agent.schema`` 的单一来源里，且删 Key 级联清空；
2. 每次鉴权通过只累加一次，401/429 不计；
3. 聚合口径是 Asia/Shanghai 自然日、含今天共 7 天；
4. 管理接口 ``GET /agent-keys/stats`` 的形状与 503 映射。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import admin_rest, auth, key_ops, keys, schema
from agent import repository_pg as store_pg
from agent.errors import AgentApiError, AgentKeyStoreUnavailable
from shared.prefixes import AGENT_ADMIN_PREFIX

SHANGHAI = ZoneInfo('Asia/Shanghai')


class FakeCursor:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.executed = []
        self.description = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self.error is not None:
            raise self.error

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def patch_connection(monkeypatch, cursor):
    @contextmanager
    def _fake():
        yield FakeConnection(cursor)

    monkeypatch.setattr(store_pg, '_connection', _fake)


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

def test_usage_ddl_is_daily_counter_with_cascading_fk():
    ddl = '\n'.join(schema.USAGE_SCHEMA_STATEMENTS)

    assert 'CREATE TABLE IF NOT EXISTS public.agent_api_key_usage' in ddl
    assert 'usage_date' in ddl
    assert 'request_count bigint' in ddl
    assert 'PRIMARY KEY (key_prefix, usage_date)' in ddl
    assert 'ON DELETE CASCADE' in ddl
    assert 'idx_agent_api_key_usage_usage_date' in ddl
    assert 'agent_api_key_usage_set_updated_at' in ddl


def test_usage_statements_are_part_of_the_single_schema_source():
    assert set(schema.USAGE_SCHEMA_STATEMENTS) <= set(schema.SCHEMA_STATEMENTS)


# ---------------------------------------------------------------------------
# 累加与聚合
# ---------------------------------------------------------------------------

def test_record_usage_upserts_one_call_per_day(monkeypatch):
    cursor = FakeCursor()
    patch_connection(monkeypatch, cursor)

    assert store_pg.record_usage('ragk_x', date(2026, 10, 27)) is True

    sql, params = cursor.executed[0]
    assert 'INSERT INTO public.agent_api_key_usage' in sql
    assert 'ON CONFLICT (key_prefix, usage_date)' in sql
    assert 'request_count = agent_api_key_usage.request_count + 1' in sql
    assert params == ('ragk_x', date(2026, 10, 27))


def test_record_usage_never_raises(monkeypatch):
    class Boom(Exception):
        pass

    patch_connection(monkeypatch, FakeCursor(error=Boom('boom')))
    assert store_pg.record_usage('ragk_x', date(2026, 10, 27)) is False


def test_usage_summary_filters_window_on_the_database(monkeypatch):
    cursor = FakeCursor(rows=[(42, 7)])
    cursor.description = [('total_calls',), ('calls_7d',)]
    patch_connection(monkeypatch, cursor)

    summary = store_pg.usage_summary(date(2026, 10, 21))

    assert summary == {'total_calls': 42, 'calls_7d': 7}
    sql, params = cursor.executed[0]
    assert 'FROM public.agent_api_key_usage' in sql
    assert 'FILTER (WHERE usage_date >= %s)' in sql
    assert params == (date(2026, 10, 21),)


def test_usage_summary_missing_table_maps_to_store_unavailable(monkeypatch):
    class UndefinedTable(Exception):
        pgcode = '42P01'

    patch_connection(monkeypatch, FakeCursor(error=UndefinedTable('missing')))
    with pytest.raises(AgentKeyStoreUnavailable):
        store_pg.usage_summary(date(2026, 10, 21))


def test_key_summary_counts_all_keys_not_just_one_page(monkeypatch):
    """概览计数从全量聚合：列表端点 pageSize 上限 100，不能靠第一页数。"""
    def fake_list():
        return [
            {'key_prefix': 'a', 'name': 'a', 'kb_ids': ['kb1', 'kb2'],
             'rate_limit_per_min': 10, 'enabled': True},
            {'key_prefix': 'b', 'name': 'b', 'kb_ids': [],
             'rate_limit_per_min': 0, 'enabled': False},
            {'key_prefix': 'c', 'name': 'c', 'kb_ids': ['kb2'],
             'rate_limit_per_min': 0, 'enabled': True},
        ]

    monkeypatch.setattr(store_pg, 'list_keys', fake_list)

    assert key_ops.key_summary() == {
        'total': 3,
        'enabled': 2,
        'rateLimited': 1,
        'kbScoped': 2,
        'allKbs': True,
        'kbCount': 2,
    }


def test_usage_stats_window_is_seven_calendar_days_including_today(monkeypatch):
    captured = {}

    def fake_summary(since):
        captured['since'] = since
        return {'total_calls': 12345, 'calls_7d': 678}

    monkeypatch.setattr(store_pg, 'usage_summary', fake_summary)

    data = key_ops.usage_stats(today=date(2026, 10, 27))

    assert captured['since'] == date(2026, 10, 21)
    assert data == {
        'totalCalls': 12345,
        'requests7d': 678,
        'windowStart': '2026-10-21',
        'windowEnd': '2026-10-27',
    }


# ---------------------------------------------------------------------------
# 鉴权路径计数
# ---------------------------------------------------------------------------

def _row(full_key, pepper, **overrides):
    row = {
        'key_prefix': keys.key_prefix(full_key),
        'name': 'demo',
        'key_hash': keys.hash_key(full_key, pepper),
        'scopes': ['kb:list'],
        'kb_ids': [],
        'rate_limit_per_min': 60,
        'enabled': True,
        'expires_at': None,
    }
    row.update(overrides)
    return row


def test_authenticate_counts_each_successful_request_only(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    auth.reset_rate_limiter()
    full, _ = keys.generate_key()
    monkeypatch.setattr(auth.store_pg, 'find_by_prefix',
                        lambda prefix: _row(full, 'pepper', rate_limit_per_min=1))
    monkeypatch.setattr(auth.store_pg, 'touch_last_used', lambda prefix: True)
    recorded = []
    monkeypatch.setattr(auth.store_pg, 'record_usage',
                        lambda prefix, day: recorded.append((prefix, day)))

    auth.authenticate('Bearer ' + full, now=100.0)
    assert len(recorded) == 1
    prefix, day = recorded[0]
    assert prefix == keys.key_prefix(full)
    assert day == datetime.now(SHANGHAI).date()

    # 429：鉴权失败在计数之前抛出，不计数。
    with pytest.raises(AgentApiError) as exc:
        auth.authenticate('Bearer ' + full, now=101.0)
    assert exc.value.http_status == 429
    assert len(recorded) == 1

    # 401：坏 Key 也不计数。
    with pytest.raises(AgentApiError):
        auth.authenticate('Bearer not-a-key', now=102.0)
    assert len(recorded) == 1
    auth.reset_rate_limiter()


# ---------------------------------------------------------------------------
# 管理接口
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_ADMIN_ENABLED', 'true')
    monkeypatch.setenv('AUTH_MODE', 'none')
    app = FastAPI()
    app.include_router(admin_rest.build_admin_router())
    with TestClient(app) as test_client:
        yield test_client


def test_stats_endpoint_returns_totals_and_window(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'usage_summary',
                        lambda since: {'total_calls': 12345, 'calls_7d': 678})
    monkeypatch.setattr(store_pg, 'list_keys', lambda: [
        {'key_prefix': 'a', 'name': 'a', 'kb_ids': ['kb1'],
         'rate_limit_per_min': 0, 'enabled': True},
    ])

    response = client.get(AGENT_ADMIN_PREFIX + '/stats')

    assert response.status_code == 200
    data = response.json()
    assert data['totalCalls'] == 12345
    assert data['requests7d'] == 678
    assert data['keySummary'] == {
        'total': 1,
        'enabled': 1,
        'rateLimited': 0,
        'kbScoped': 1,
        'allKbs': False,
        'kbCount': 1,
    }
    today = datetime.now(SHANGHAI).date()
    assert data['windowEnd'] == today.isoformat()
    assert data['windowStart'] == (today - timedelta(days=6)).isoformat()


def test_stats_endpoint_maps_missing_table_to_503(client, monkeypatch):
    def boom(since):
        raise AgentKeyStoreUnavailable()

    monkeypatch.setattr(store_pg, 'usage_summary', boom)

    response = client.get(AGENT_ADMIN_PREFIX + '/stats')

    assert response.status_code == 503
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'service_unavailable'


def test_stats_endpoint_respects_kill_switch(client, monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_ADMIN_ENABLED', 'false')

    response = client.get(AGENT_ADMIN_PREFIX + '/stats')

    assert response.status_code == 403
    assert response.json()['code'] == 'permission_denied'
