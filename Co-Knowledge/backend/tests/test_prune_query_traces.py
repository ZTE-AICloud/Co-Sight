"""清理脚本的安全闸与分批 SQL（不连 DB）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Cursor:
    def __init__(self, batches=None, responses=None):
        self.executed = []
        self._batches = list(batches or [])
        self._responses = list(responses or [])
        self._all = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._batches:
            self._all = self._batches.pop(0)
        elif self._responses:
            self._all = self._responses.pop(0)

    def fetchall(self):
        return self._all

    def fetchone(self):
        return self._all[0] if self._all else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


def test_prune_apply_requires_yes_and_nonzero_days(capsys):
    tool = _load('prune_query_traces_guards', 'tools/ops/prune-query-traces.py')
    assert tool.main(['--apply']) == 2
    assert tool.main(['--apply', '--yes', '--older-than-days', '0']) == 2
    assert tool.main(['--apply', '--yes', '--batch-size', '0']) == 2


def test_dry_run_does_not_delete():
    tool = _load('prune_query_traces_dry', 'tools/ops/prune-query-traces.py')
    cursor = _Cursor(responses=[[(3, '2026-01-01', '2026-02-01')]])

    assert tool.dry_run(cursor, 30) == 3
    assert all('DELETE' not in sql.upper() for sql, _ in cursor.executed)


def test_prune_deletes_in_batches_until_short_batch():
    tool = _load('prune_query_traces_apply', 'tools/ops/prune-query-traces.py')
    cursor = _Cursor(batches=[[1, 2], [3]])
    conn = _Conn(cursor)

    total = tool.prune(conn, 30, 2)

    assert total == 3
    assert conn.commits == 2
    delete_sql, params = cursor.executed[0]
    assert 'make_interval(days => %s)' in delete_sql
    assert 'LIMIT %s' in delete_sql
    assert params == (30, 2)


def test_verify_checks_columns_and_indexes():
    tool = _load('prune_query_traces_verify', 'tools/ops/prune-query-traces.py')
    from chat import schema
    cursor = _Cursor(responses=[
        [(name,) for name in ('id', 'created_at', *schema.COLUMN_NAMES)],
        [(name,) for name in schema.INDEX_NAMES],
    ])

    assert tool.verify(cursor) is True
    assert all('information_schema.columns' in sql or 'pg_indexes' in sql
               for sql, _ in cursor.executed)
