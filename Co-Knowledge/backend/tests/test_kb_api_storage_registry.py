"""``kb_storage_registry`` 生命周期表（P2）。

写入是尽力而为：注册表失败不能阻断建库/删库，所以这里只钉 SQL 形状与状态推进。
"""

from __future__ import annotations

from contextlib import contextmanager

from infrastructure.storage import registry as store


class _Cursor:
    def __init__(self):
        self.sql = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)

    def close(self):
        pass


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


def _capture(monkeypatch):
    cursor = _Cursor()

    @contextmanager
    def _connection():
        yield _Conn(cursor)

    monkeypatch.setattr(store, 'connection', _connection)
    monkeypatch.setattr(store, 'ensure_table', lambda: None)
    return cursor


def test_lifecycle_states_are_written(monkeypatch):
    cursor = _capture(monkeypatch)

    store.begin_create('kb-1', 'demo', 1, 'data_kb_index_kb1', 'm', 1024)
    store.mark_ready('kb-1')
    store.mark_failed('kb-1', 'boom')
    store.begin_delete('kb-1')
    store.remove('kb-1')

    assert 'INSERT INTO public.kb_storage_registry' in cursor.sql[0]
    assert cursor.params[0][-1] == store.STATE_CREATING
    assert "state = %s" in cursor.sql[1] and cursor.params[1][0] == store.STATE_READY
    assert cursor.params[2][0] == store.STATE_FAILED and cursor.params[2][1] == 'boom'
    assert cursor.params[3][0] == store.STATE_DELETING
    assert cursor.sql[4].startswith('DELETE FROM public.kb_storage_registry')


def test_reconcile_inserts_missing_and_marks_broken(monkeypatch):
    class _ScriptedCursor(_Cursor):
        def __init__(self):
            super().__init__()
            self._results = [
                [('kb-1', 'demo', 1, 'data_kb_index_kb1', 'm')],
                [],
                [(True,)],
            ]

        def fetchall(self):
            return self._results.pop(0)

        def fetchone(self):
            return self._results.pop(0)[0]

    cursor = _ScriptedCursor()

    @contextmanager
    def _connection():
        yield _Conn(cursor)

    monkeypatch.setattr(store, 'connection', _connection)

    stats = store.reconcile()

    assert stats == {'inserted': 1, 'failed': 0, 'removed': 0, 'checked': 1}
    insert_at = next(
        index for index, sql in enumerate(cursor.sql)
        if sql.startswith('INSERT INTO public.kb_storage_registry'))
    assert cursor.params[insert_at] == (
        'kb-1', 'demo', 1, 'data_kb_index_kb1',
        'data_kb_index_kb1_chunk', None, 'm', 'ready', None)
