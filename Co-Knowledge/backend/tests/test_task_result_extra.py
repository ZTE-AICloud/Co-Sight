"""任务结果摘要（``task_center.task.extra``）的写入形状。

三条链路各自负责产出计数，但落库路径只有两种：

* ``status_owner='engine'``（文件导入）：runner 用 ``TaskContext.set_result``
  收集，引擎在成功落停时合并进 ``extra``；
* ``status_owner='runner'``（图谱抽图/导入）：领域 store 在写终态时合并。

本组测试钉住 SQL 形状、合并语义与摘要字段，不连数据库。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

from infrastructure.tasks import TaskContext, TaskRecord, pg_queue
from knowledge_base.task import executor
from knowledge_base.task.chain import FileHandlerChain


class _Cursor:
    def __init__(self):
        self.sql = ''
        self.params = None
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def close(self):
        pass


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def _capture(monkeypatch, module):
    cursor = _Cursor()

    @contextmanager
    def _connection():
        yield _Conn(cursor)

    monkeypatch.setattr(module, 'connection', _connection)
    return cursor


# ----------------------------------------------------------------------
# 引擎侧
# ----------------------------------------------------------------------


def test_task_context_set_result_merges_existing_extra():
    record = TaskRecord(task_id='t1', kind='file_import', extra={'inherited': True})
    ctx = TaskContext(record=record, lane='file_import')

    ctx.set_result(chunkCount=3, vectorCount=3)

    assert record.extra == {'inherited': True, 'chunkCount': 3, 'vectorCount': 3}


def test_pg_queue_complete_merges_extra_json(monkeypatch):
    cursor = _capture(monkeypatch, pg_queue)

    assert pg_queue.complete('t1', 'worker-1', extra={'chunkCount': 2})

    assert "status = 'COMPLETED'" in cursor.sql
    assert "extra = COALESCE(extra, '{}'::jsonb) || %s::jsonb" in cursor.sql
    assert cursor.params[0] == 100
    assert json.loads(cursor.params[1]) == {'chunkCount': 2}
    assert cursor.params[2:] == ['t1', 'worker-1']


def test_pg_queue_complete_without_extra_keeps_existing_value(monkeypatch):
    cursor = _capture(monkeypatch, pg_queue)

    assert pg_queue.complete('t1', 'worker-1')

    assert 'extra =' not in cursor.sql
    assert cursor.params == [100, 't1', 'worker-1']


# ----------------------------------------------------------------------
# 文件导入
# ----------------------------------------------------------------------


def test_handler_chain_returns_stage_timings():
    class Handler:
        def __init__(self, stage):
            self.stage = stage

        def handle(self, file_handle):
            file_handle.setdefault('seen', []).append(self.stage)

        def rollback(self, file_handle):
            pass

    chain = FileHandlerChain()
    chain.add_handler(Handler('parse'))
    chain.add_handler(Handler('split'))
    chain.add_handler(Handler('embed'))
    handle = {}

    timings = chain.execute(handle)

    assert handle['seen'] == ['parse', 'split', 'embed']
    assert set(timings) == {'parse', 'split', 'embed'}
    assert all(isinstance(value, int) and value >= 0 for value in timings.values())


def test_process_file_returns_result_summary(monkeypatch):
    from knowledge_base.repository import directory as directory_store

    class Chain:
        def add_handler(self, handler):
            return self

        def execute(self, file_handle):
            file_handle['splitResult'] = {
                'chunks': [{'id': 'c1'}, {'id': 'c2'}],
                'results': [{'nodeId': 'n1'}, {'nodeId': 'n2'}, {'nodeId': 'n3'}],
            }
            return {'parse': 1, 'split': 2, 'embed': 3}

    monkeypatch.setattr(executor, 'FileHandlerChain', Chain)
    monkeypatch.setattr(directory_store, 'update_file_status',
                        lambda cursor, file_id, status, reason: None)
    monkeypatch.setattr(executor.storage, 'cleanup_task_files', lambda handle: None)

    @contextmanager
    def _connection():
        yield _Conn(_Cursor())

    monkeypatch.setattr(directory_store, 'connection', _connection)

    summary = executor.process_file({
        'fileId': 'f1',
        'kbaseId': 'kb1',
        'fileName': 'report.md',
        'fileSize': 2048,
        'format': 'md',
        'modelName': 'Qwen3-Embedding-0.6B',
        'operatorSplitDTO': {'operatorId': -1},
    })

    assert summary == {
        'fileName': 'report.md',
        'fileSize': 2048,
        'format': 'md',
        'embeddingModel': 'Qwen3-Embedding-0.6B',
        'splitOperatorId': -1,
        'chunkCount': 2,
        'vectorCount': 3,
        'indexDocCount': 3,
        'stageTimingsMs': {'parse': 1, 'split': 2, 'embed': 3},
    }


def test_run_file_task_sets_result_on_context(monkeypatch):
    calls = []
    monkeypatch.setattr(executor, 'process_file',
                        lambda handle: {'chunkCount': 2, 'vectorCount': 2})
    monkeypatch.setattr(executor.kbase_store, 'set_kbase_status_modified',
                        lambda kbase_id: calls.append(kbase_id))
    record = SimpleNamespace(payload={'fileHandle': {'kbaseId': 'kb1'}})
    ctx = SimpleNamespace(results={})

    def set_result(**fields):
        ctx.results.update(fields)

    ctx.set_result = set_result

    executor.run_file_task(record, ctx)

    assert ctx.results == {'chunkCount': 2, 'vectorCount': 2}
    assert calls == ['kb1']


# ----------------------------------------------------------------------
# 图谱导入 / 抽图
# ----------------------------------------------------------------------


def _counters(total=5, success=5, failed=0):
    return SimpleNamespace(total=total, success=success, failed=failed,
                           failed_records=[])


def test_graph_import_progress_includes_vector_stats(monkeypatch):
    from graph.repository import graph_import_store as store

    cursor = _capture(monkeypatch, store)

    store.update_progress(
        't1', 100, _counters(), _counters(success=4, failed=1),
        index_stats={'entities': 5, 'edges': 4, 'chunks': 2,
                     'chunk_rows': 2, 'skipped': 0, 'collisions': 1},
        index_error='index boom')

    extra = json.loads(cursor.params[1])
    assert extra['entity_success'] == 5
    assert extra['edge_failed'] == 1
    assert extra['vector_entities'] == 5
    assert extra['vector_edges'] == 4
    assert extra['vector_chunks'] == 2
    assert extra['vector_collisions'] == 1
    assert extra['index_error'] == 'index boom'


def test_extract_status_update_merges_extra(monkeypatch):
    from graph.repository import graph_extract_store as store

    cursor = _capture(monkeypatch, store)

    store.update_task_status('t1', store.STATUS_SUCCESS, 100,
                             extra={'entity_total': 5, 'schemaId': 'General_Schema'})

    assert "extra = COALESCE(extra, '{}'::jsonb) || %s::jsonb" in cursor.sql
    assert json.loads(cursor.params[3]) == {
        'entity_total': 5, 'schemaId': 'General_Schema'}


def test_extract_result_extra_combines_input_and_import_counts():
    from graph.service import graph_extract_v2_service as service

    extra = service._result_extra(
        {'operatorId': -6, 'kwargs': {'llm': 'deepseek-v4-flash'}},
        'General_Schema', 2, 'import-1',
        {
            'entity_total': 5, 'entity_success': 5, 'entity_failed': 0,
            'edge_total': 5, 'edge_success': 5, 'edge_failed': 0,
            'vector_entities': 5, 'vector_edges': 5, 'vector_chunks': 0,
            'failed_records': None,
        })

    assert extra == {
        'fileCount': 2,
        'operatorId': -6,
        'schemaId': 'General_Schema',
        'llm': 'deepseek-v4-flash',
        'importTaskId': 'import-1',
        'entity_total': 5,
        'entity_success': 5,
        'entity_failed': 0,
        'edge_total': 5,
        'edge_success': 5,
        'edge_failed': 0,
        'vector_entities': 5,
        'vector_edges': 5,
        'vector_chunks': 0,
    }


def test_extract_result_extra_counts_failed_records():
    from graph.service import graph_extract_v2_service as service

    extra = service._result_extra(
        {'operatorId': -6}, 'General_Schema', None, 'import-1',
        {'failed_records': [{'id': 'e1'}, {'id': 'e2'}]})

    assert extra['failedRecordCount'] == 2
    assert 'fileCount' not in extra
