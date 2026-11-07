"""``agent_api.store_pg`` 与 ``agent_api.cli`` 的单测（不连 DB）。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timezone

import pytest

from agent import cli, repository_pg as store_pg
from agent.errors import AgentKeyStoreUnavailable

PUBLIC_COLUMNS = [name.strip() for name in store_pg._PUBLIC_COLUMNS.split(',')]


class FakeCursor:
    def __init__(self, rows=None, rowcount=0, error=None):
        self.rows = rows or []
        self.rowcount = rowcount
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


def test_find_by_prefix_returns_row_with_hash(monkeypatch):
    row = ('ragk_abcdefgh', 'demo', 'purpose', ['kb:list'], [], 60, True, None,
           None, 'cli', None, None, 'a' * 64)
    cursor = FakeCursor(rows=[row])
    cursor.description = [(name,) for name in PUBLIC_COLUMNS + ['key_hash']]
    patch_connection(monkeypatch, cursor)

    result = store_pg.find_by_prefix('ragk_abcdefgh')

    assert result['name'] == 'demo'
    assert result['key_hash'] == 'a' * 64
    assert 'WHERE key_prefix = %s' in cursor.executed[0][0]
    assert cursor.executed[0][1] == ('ragk_abcdefgh',)


def test_find_by_prefix_returns_none_when_absent(monkeypatch):
    patch_connection(monkeypatch, FakeCursor(rows=[]))
    assert store_pg.find_by_prefix('ragk_nothing') is None


def test_missing_table_maps_to_503_error(monkeypatch):
    class UndefinedTable(Exception):
        pgcode = '42P01'

    patch_connection(monkeypatch, FakeCursor(error=UndefinedTable('missing')))
    with pytest.raises(AgentKeyStoreUnavailable):
        store_pg.find_by_prefix('ragk_x')


def test_insert_key_passes_arrays_and_expiry(monkeypatch):
    cursor = FakeCursor()
    patch_connection(monkeypatch, cursor)

    store_pg.insert_key(
        name='demo', description='purpose', key_prefix='ragk_x',
        key_hash='h' * 64, scopes=['kb:search'], kb_ids=['kb-1'],
        rate_limit_per_min=5, expires_at=None, created_by='tester')

    sql, params = cursor.executed[0]
    assert 'INSERT INTO public.agent_api_key' in sql
    assert params == ('demo', 'purpose', 'ragk_x', 'h' * 64,
                      ['kb:search'], ['kb-1'], 5, None, 'tester')


def test_set_enabled_and_delete_return_rowcount(monkeypatch):
    cursor = FakeCursor(rowcount=1)
    patch_connection(monkeypatch, cursor)

    assert store_pg.set_enabled('ragk_x', False) == 1
    assert store_pg.delete_key('ragk_x') == 1
    assert 'UPDATE public.agent_api_key' in cursor.executed[0][0]
    assert 'DELETE FROM public.agent_api_key' in cursor.executed[1][0]


def test_touch_last_used_never_raises(monkeypatch):
    class Boom(Exception):
        pass

    patch_connection(monkeypatch, FakeCursor(error=Boom('boom')))
    assert store_pg.touch_last_used('ragk_x') is False


def test_parse_scopes_defaults_and_rejects_unknown():
    assert cli._parse_scopes(None) == ['kb:list', 'kb:search']
    with pytest.raises(SystemExit):
        cli._parse_scopes('kb:list,not:a:scope')


def test_parse_expires_date_only_means_end_of_day_utc():
    parsed = cli._parse_expires('2030-01-02')
    assert parsed.tzinfo == timezone.utc
    assert (parsed.year, parsed.month, parsed.day) == (2030, 1, 2)
    assert (parsed.hour, parsed.minute, parsed.second) == (23, 59, 59)


def test_pepper_is_required(monkeypatch):
    monkeypatch.delenv('RKB_AGENT_KEY_PEPPER', raising=False)
    with pytest.raises(SystemExit):
        cli._pepper()
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'p')
    assert cli._pepper() == 'p'


def test_cmd_create_prints_key_once_and_inserts(monkeypatch, capsys):
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    monkeypatch.setattr(cli.keys, 'generate_key',
                        lambda: ('ragk_abcdefgh_secretsecret', 'ragk_abcdefgh'))
    captured = {}
    monkeypatch.setattr(cli.store_pg, 'insert_key', lambda **kwargs: captured.update(kwargs))

    args = cli.build_parser().parse_args([
        'create', '--name', 'demo', '--scopes', 'kb:list,kb:search',
        '--kb-ids', 'kb-1,kb-2', '--rate-limit', '7'])
    assert cli.cmd_create(args) == 0

    out = capsys.readouterr().out
    assert out.count('ragk_abcdefgh_secretsecret') == 1
    assert captured['name'] == 'demo'
    assert captured['scopes'] == ['kb:list', 'kb:search']
    assert captured['kb_ids'] == ['kb-1', 'kb-2']
    assert captured['rate_limit_per_min'] == 7
    assert captured['key_hash'] == cli.keys.hash_key(
        'ragk_abcdefgh_secretsecret', 'pepper')


def test_cmd_list_and_revoke(monkeypatch, capsys):
    monkeypatch.setattr(cli.store_pg, 'list_keys', lambda: [{
        'key_prefix': 'ragk_x', 'name': 'demo', 'scopes': ['kb:list'],
        'kb_ids': [], 'rate_limit_per_min': 60, 'enabled': True,
        'expires_at': None, 'last_used_at': None,
    }])
    assert cli.cmd_list(None) == 0
    out = capsys.readouterr().out
    assert 'ragk_x' in out and 'yes' in out and '(all)' in out

    monkeypatch.setattr(cli.store_pg, 'set_enabled', lambda prefix, enabled: 1)
    args = cli.build_parser().parse_args(['revoke', '--prefix', 'ragk_x'])
    assert cli.cmd_revoke(args) == 0
    assert 'disabled: ragk_x' in capsys.readouterr().out

    monkeypatch.setattr(cli.store_pg, 'set_enabled', lambda prefix, enabled: 0)
    assert cli.cmd_revoke(args) == 1
