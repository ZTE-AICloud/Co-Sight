"""A 批回归：根目录哨兵、文件来源、GraphProcess 进度 SQL。"""
from __future__ import annotations

from ingestion.client import graph_process
from knowledge_base.service import directory_service


class _FakeCursor:
    def __init__(self):
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _FakeConn:
    def __init__(self):
        self.cursor_obj = _FakeCursor()

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_query_or_create_directory_uses_null_parent(monkeypatch):
    conn = _FakeConn()
    captured = {}

    monkeypatch.setattr(directory_service.directory_store, 'connection', lambda: conn)
    monkeypatch.setattr(directory_service.directory_store, 'get_parent_path',
                        lambda _cursor, parent_id: '0')
    monkeypatch.setattr(directory_service.directory_store, 'find_folder_by_title',
                        lambda _cursor, kb, parent_id, title: captured.update(
                            find_parent=parent_id) or None)

    def _insert(_cursor, kbase_id, parent_id, parent_path, title, dir_type, status,
                **kwargs):
        captured.update(insert_parent=parent_id, title=title, kwargs=kwargs)
        return 'dir-new'

    monkeypatch.setattr(directory_service.directory_store, 'insert_directory', _insert)

    assert directory_service.query_or_create_directory('kb-1', 'Default') == 'dir-new'
    assert captured['find_parent'] is None
    assert captured['insert_parent'] is None


def test_graph_process_emits_valid_update_sql(monkeypatch):
    executed = []

    class _Client:
        def execute(self, sql, params):
            executed.append((sql, params))

    class _PgManager:
        def get_pg_client(self):
            return _Client()

    monkeypatch.setattr(graph_process, 'pg_manager', _PgManager())
    graph_process.GraphProcess().update_kbase_process('kb-1', '30', '处理中', 'running')

    assert len(executed) == 1
    sql, params = executed[0]
    assert 'SET process = %s, process_obj = %s WHERE kbase_id = %s' in sql
    assert ', WHERE' not in sql
    assert params[0] == '30'
    assert params[2] == 'kb-1'
