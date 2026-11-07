"""Agent Key 管理面的存储层与前缀校验单测（不连 DB）。"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from agent import keys, repository_pg as store_pg
from agent.errors import AgentKeyStoreUnavailable

PUBLIC_COLUMNS = [name.strip() for name in store_pg._PUBLIC_COLUMNS.split(',')]


class FakeCursor:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.executed = []
        self.description = [(name,) for name in PUBLIC_COLUMNS]

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


def _row(**overrides):
    values = {
        'key_prefix': 'ragk_1a2b3c4d',
        'name': 'demo',
        'description': 'demo description',
        'scopes': ['kb:list'],
        'kb_ids': [],
        'rate_limit_per_min': 60,
        'enabled': True,
        'expires_at': None,
        'last_used_at': None,
        'created_at': None,
        'updated_at': None,
        'created_by': 'admin',
    }
    values.update(overrides)
    return tuple(values[name] for name in PUBLIC_COLUMNS)


def test_get_key_selects_public_columns_only(monkeypatch):
    cursor = FakeCursor(rows=[_row()])
    patch_connection(monkeypatch, cursor)

    row = store_pg.get_key('ragk_1a2b3c4d')

    assert row['name'] == 'demo'
    sql, params = cursor.executed[0]
    assert 'key_hash' not in sql
    assert 'WHERE key_prefix = %s' in sql
    assert params == ('ragk_1a2b3c4d',)


def test_update_key_builds_whitelisted_sql_and_returns_row(monkeypatch):
    cursor = FakeCursor(rows=[_row(name='renamed', enabled=False)])
    patch_connection(monkeypatch, cursor)

    row = store_pg.update_key(
        'ragk_1a2b3c4d', name='renamed', scopes=['kb:list'], enabled=False)

    assert row['name'] == 'renamed'
    sql, params = cursor.executed[0]
    assert 'UPDATE public.agent_api_key SET' in sql
    assert 'name = %s' in sql
    assert 'scopes = %s' in sql
    assert 'enabled = %s' in sql
    assert 'key_hash' not in sql
    assert params == ('renamed', ['kb:list'], False, 'ragk_1a2b3c4d')


def test_update_key_can_clear_expiry(monkeypatch):
    cursor = FakeCursor(rows=[_row(expires_at=None)])
    patch_connection(monkeypatch, cursor)

    store_pg.update_key('ragk_1a2b3c4d', expires_at=None)

    sql, params = cursor.executed[0]
    assert 'expires_at = %s' in sql
    assert params == (None, 'ragk_1a2b3c4d')


def test_update_key_empty_changes_is_rejected():
    with pytest.raises(ValueError):
        store_pg.update_key('ragk_1a2b3c4d')


def test_update_key_returns_none_when_absent(monkeypatch):
    cursor = FakeCursor(rows=[])
    patch_connection(monkeypatch, cursor)
    assert store_pg.update_key('ragk_1a2b3c4d', name='x') is None


def test_ping_maps_missing_table_to_store_unavailable(monkeypatch):
    class MissingTable(Exception):
        pgcode = '42P01'

    cursor = FakeCursor(error=MissingTable('missing'))
    patch_connection(monkeypatch, cursor)

    with pytest.raises(AgentKeyStoreUnavailable):
        store_pg.ping()


def test_is_key_prefix_accepts_hex_prefix():
    assert keys.is_key_prefix('ragk_1a2b3c4d')
    assert not keys.is_key_prefix('ragk_BJ_S2dCf')
    assert not keys.is_key_prefix('ragk_short')
    assert not keys.is_key_prefix('not-a-key')
    assert not keys.is_key_prefix('')
