"""`chat.repository_pg` 的 SQL/清洗/降级口径（不连真实 PG）。"""
from __future__ import annotations

import math
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from chat import repository_pg, schema
from chat.trace_errors import QueryTraceStoreUnavailable


class _FakeCursor:
    def __init__(self):
        self.executed = []
        self.description = None
        self._one = None
        self._all = []
        self._on_execute = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._on_execute is not None:
            self._on_execute(sql, params)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


@contextmanager
def _conn_ctx(conn):
    yield conn


@pytest.fixture(autouse=True)
def _reset_schema():
    repository_pg._reset_schema_for_tests()
    yield
    repository_pg._reset_schema_for_tests()


def _payload(**overrides):
    values = {
        'trace_id': 't' * 70,
        'conversation_id': 'd\x00' + 'x' * 200,
        'workflow_id': 'w' * 200,
        'org_id': 'o' * 200,
        'is_stream': True,
        'status': 'ok',
        'error_code': 'e' * 200,
        'http_status': 200,
        'error_status': None,
        'question_len': 3,
        'answer_len': 8,
        'understanding_ms': 12.34,
        'retrieval_ms': 0,
        'rerank_ms': None,
        'generate_ms': math.nan,
        'first_token_ms': -1,
        'total_ms': 100.0,
        'hit_count': 5,
        'source_count': 3,
        'kb_count': 1,
        'top_score': math.inf,
    }
    values.update(overrides)
    return values


def test_row_values_are_sanitized_and_truncated():
    values = repository_pg._row_values(_payload())
    mapping = dict(zip(schema.COLUMN_NAMES, values))

    assert mapping['trace_id'] == 't' * 64
    assert mapping['conversation_id'].startswith('d') and '\x00' not in mapping['conversation_id']
    assert len(mapping['conversation_id']) == 128
    assert len(mapping['workflow_id']) == 128
    assert len(mapping['org_id']) == 128
    assert len(mapping['error_code']) == 128
    assert mapping['retrieval_ms'] == 0.0
    assert mapping['generate_ms'] is None
    assert mapping['first_token_ms'] is None
    assert mapping['top_score'] is None


def test_row_values_force_unknown_status_to_error():
    values = repository_pg._row_values(_payload(status='weird'))
    mapping = dict(zip(schema.COLUMN_NAMES, values))
    assert mapping['status'] == schema.STATUS_ERROR


def test_ensure_table_skips_ddl_when_table_exists():
    cursor = _FakeCursor()
    cursor._one = ('t_query_trace',)

    assert repository_pg.ensure_table(_FakeConn(cursor)) is True
    assert len(cursor.executed) == 1
    assert 'to_regclass' in cursor.executed[0][0]
    assert not any('CREATE TABLE' in sql for sql, _ in cursor.executed)


def test_ensure_table_creates_schema_when_missing_and_commits_ddl():
    cursor = _FakeCursor()
    cursor._one = (None,)
    conn = _FakeConn(cursor)

    assert repository_pg.ensure_table(conn) is True
    executed = [sql for sql, _ in cursor.executed]
    assert any('CREATE TABLE IF NOT EXISTS' in sql for sql in executed)
    assert sum('CREATE INDEX IF NOT EXISTS' in sql for sql in executed) == len(
        schema.CREATE_INDEX_STATEMENTS)
    # DDL 必须在 INSERT 之前提交，否则 INSERT 失败会连表一起回滚
    assert conn.commits == 1


def test_ensure_table_failure_cools_down():
    cursor = _FakeCursor()

    def boom(sql, params=None):
        raise RuntimeError('no privilege')

    cursor._on_execute = boom
    with pytest.raises(RuntimeError):
        repository_pg.ensure_table(_FakeConn(cursor))

    # 冷却期内不再尝试 DDL
    second = _FakeCursor()
    assert repository_pg.ensure_table(_FakeConn(second)) is False
    assert second.executed == []


def test_persist_query_trace_parameters_and_failure_swallow(monkeypatch):
    cursor = _FakeCursor()
    monkeypatch.setattr(repository_pg, 'ensure_table', lambda conn: True)
    monkeypatch.setattr(
        'infrastructure.db.kb.connection',
        lambda: _conn_ctx(_FakeConn(cursor)))

    assert repository_pg.persist_query_trace(_payload()) is True
    insert_sql, insert_params = cursor.executed[-1]
    assert insert_sql.startswith(f'INSERT INTO {schema.TABLE}')
    assert len(insert_params) == len(schema.COLUMN_NAMES)
    assert any('statement_timeout' in sql for sql, _ in cursor.executed)
    assert any('lock_timeout' in sql for sql, _ in cursor.executed)

    def boom():
        raise RuntimeError('db down')

    monkeypatch.setattr('infrastructure.db.kb.connection', boom)
    assert repository_pg.persist_query_trace(_payload()) is False


def _trace_row(row_id=1):
    values = {
        'id': row_id,
        'trace_id': 'trace-1',
        'conversation_id': 'dlg-1',
        'workflow_id': 'wf-1',
        'org_id': 'org-1',
        'is_stream': True,
        'status': 'ok',
        'error_code': '',
        'http_status': 200,
        'error_status': None,
        'question_len': 3,
        'answer_len': 8,
        'understanding_ms': 12.3,
        'retrieval_ms': 20.0,
        'rerank_ms': 30.0,
        'generate_ms': 40.0,
        'first_token_ms': 50.0,
        'total_ms': 60.0,
        'hit_count': 5,
        'source_count': 3,
        'kb_count': 1,
        'top_score': 6.0,
        'created_at': datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc),
    }
    return tuple(values[name] for name in ('id', *schema.COLUMN_NAMES, 'created_at'))


def _trace_description():
    return [(name,) for name in ('id', *schema.COLUMN_NAMES, 'created_at')]


def test_list_traces_filters_and_maps_rows(monkeypatch):
    cursor = _FakeCursor()
    cursor._one = (2,)
    cursor._all = [_trace_row(2), _trace_row(1)]
    cursor.description = _trace_description()
    monkeypatch.setattr(repository_pg, '_open_reader', lambda: _conn_ctx(_FakeConn(cursor)))

    items, total = repository_pg.list_query_traces(
        {'workflow_id': 'wf-1', 'status': 'ok', 'from_dt': None, 'to_dt': None},
        page_no=2, page_size=10)

    assert total == 2
    assert [item['id'] for item in items] == [2, 1]
    count_sql, count_params = next(
        (sql, params) for sql, params in cursor.executed
        if sql.startswith('SELECT count(*)'))
    assert 'workflow_id = %s' in count_sql and 'status = %s' in count_sql
    assert count_params == ['wf-1', 'ok']
    data_sql, data_params = next(
        (sql, params) for sql, params in cursor.executed
        if 'ORDER BY created_at DESC' in sql)
    assert 'LIMIT %s OFFSET %s' in data_sql
    assert data_params[-2:] == [10, 10]
    assert any('SET LOCAL TIME ZONE' in sql for sql, _ in cursor.executed)
    assert any('REPEATABLE READ' in sql for sql, _ in cursor.executed)


def test_get_trace_and_store_error(monkeypatch):
    cursor = _FakeCursor()
    cursor._all = [_trace_row(7)]
    cursor.description = _trace_description()
    monkeypatch.setattr(repository_pg, '_open_reader', lambda: _conn_ctx(_FakeConn(cursor)))
    assert repository_pg.get_query_trace(7)['id'] == 7

    def boom():
        raise RuntimeError('db down')

    monkeypatch.setattr(repository_pg, '_open_reader', boom)
    with pytest.raises(QueryTraceStoreUnavailable):
        repository_pg.get_query_trace(7)


def _summary_row(**overrides):
    values = {
        'count': 10, 'ok_count': 8, 'error_count': 1,
        'client_disconnect_count': 1, 'ok_hit_count': 6,
        'avg_hit_count': 3.5, 'avg_source_count': 2.25,
    }
    for key, _alias in repository_pg._STAGE_COLUMNS:
        values[f'{key}_count'] = 8
        values[f'{key}_p50'] = 1.0
        values[f'{key}_p95'] = 2.0
        values[f'{key}_p99'] = 3.0
    values.update(overrides)
    return values


def test_stats_query_uses_timezone_bucket_and_returns_rows(monkeypatch):
    cursor = _FakeCursor()
    summary = _summary_row()
    cursor._one = tuple(summary[name] for name in summary)
    cursor.description = [(name,) for name in summary]

    def switch_description(sql, params=None):
        if 'date_trunc' in sql:
            cursor.description = [('bucket',), *[(name,) for name in summary]]
        else:
            cursor.description = [(name,) for name in summary]

    cursor._on_execute = switch_description
    series_row = dict(summary, bucket=datetime(2026, 10, 25, tzinfo=timezone.utc))
    cursor._all = [tuple(series_row[name] for name in ('bucket', *summary))]
    monkeypatch.setattr(repository_pg, '_open_reader', lambda: _conn_ctx(_FakeConn(cursor)))

    result = repository_pg.query_trace_stats({'workflow_id': 'wf-1'}, 'day')

    assert result['summary']['count'] == 10
    assert result['series'][0]['bucket'] == datetime(2026, 10, 25, tzinfo=timezone.utc)
    series_sql, series_params = cursor.executed[-1]
    assert 'date_trunc(%s, created_at AT TIME ZONE %s)' in series_sql
    assert series_params[:3] == ['day', repository_pg.TIMEZONE, repository_pg.TIMEZONE]
    assert series_params[3] == 'wf-1'


def test_stats_rejects_unknown_bucket():
    with pytest.raises(ValueError):
        repository_pg.query_trace_stats({}, 'week')
