"""``DatabaseOperator`` 参数化查询的回归测试。

``pg_select_zip_values_operator_with_params`` 让图谱检索走 psycopg2 的
extended protocol（不可堆叠语句）。本组测试钉住：

1. 有 params 时 ``cursor.execute(sql, params)``；
2. ``params=None`` 时保持 simple query 语义；
3. 连接失败时返回 ``(False, msg)``，不能被 ``finally`` 里的
   ``UnboundLocalError`` 掩盖。

跑法::

    python -m pytest tests/test_database_pool_operator_params.py -q
"""

from __future__ import annotations

from infrastructure.db.pool import DatabaseOperator


class _FakeCursor:
    description = [('x',)]

    def __init__(self):
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return [(1,)]

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def _operator(conn=None, error=None):
    operator = DatabaseOperator.__new__(DatabaseOperator)

    def _connect():
        if error is not None:
            raise error
        return conn

    operator.get_db_conn = _connect
    return operator


def test_with_params_executes_extended_protocol():
    conn = _FakeConn()
    operator = _operator(conn)

    status, rows = operator.pg_select_zip_values_operator_with_params(
        'SELECT %s', ('value',))

    assert status is True
    assert rows == [{'x': 1}]
    assert conn.cursor_obj.executed == [('SELECT %s', ('value',))]
    assert conn.cursor_obj.closed is True
    assert conn.closed is True


def test_none_params_keeps_simple_execute():
    conn = _FakeConn()
    operator = _operator(conn)

    status, rows = operator.pg_select_zip_values_operator_with_params('SELECT 1', None)

    assert status is True
    assert rows == [{'x': 1}]
    assert conn.cursor_obj.executed == [('SELECT 1', None)]


def test_connect_failure_returns_error_without_unbound_local():
    operator = _operator(error=RuntimeError('no database'))

    status, message = operator.pg_select_zip_values_operator_with_params(
        'SELECT %s', ('value',))

    assert status is False
    assert 'no database' in message
