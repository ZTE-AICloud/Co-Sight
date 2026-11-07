"""``PGClient.execute`` 的失败语义：记录日志并上抛，不得静默吞掉。"""

import logging

import pytest

from ingestion.utility import pg_database


def _client():
    return pg_database.PGClient('h', 'd', 'u', 'p', 5432)


def test_execute_reraises_connect_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError('connect failed')

    monkeypatch.setattr(pg_database.psycopg2, 'connect', boom)

    with pytest.raises(RuntimeError, match='connect failed'):
        _client().execute('select 1')


def test_execute_logs_connect_error(monkeypatch, caplog):
    def boom(**kwargs):
        raise RuntimeError('connect failed')

    monkeypatch.setattr(pg_database.psycopg2, 'connect', boom)

    with caplog.at_level(logging.ERROR, logger=pg_database.__name__):
        with pytest.raises(RuntimeError):
            _client().execute('select 1')

    assert '执行 PG SQL 失败' in caplog.text


def test_execute_closes_cursor_and_connection_on_success(monkeypatch):
    closed = []
    committed = []

    class FakeCursor:
        def execute(self, sql, params):
            self.sql = sql

        def close(self):
            closed.append('cursor')

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            committed.append(True)

        def close(self):
            closed.append('connection')

    monkeypatch.setattr(pg_database.psycopg2, 'connect', lambda **kwargs: FakeConnection())

    _client().execute('select 1')

    assert committed == [True]
    assert closed == ['cursor', 'connection']
