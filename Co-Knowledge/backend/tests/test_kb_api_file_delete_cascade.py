"""删文件时的**级联清理顺序**：relation/向量 → chunk 表 → 软删 → 磁盘。

## 这个文件为什么存在

`_purge_files()` 必须按文件名清 chunk 表：漏了会留下 `_chunk` 孤儿行
（merge-verify-kb 删 4 个文件后留了 22 行）。正确顺序是：
在删除文件记录之前取文件名，末尾调 `vectorChunkDao.deleteBySource`。

这条用例用桩把顺序与参数钉住，不连库。
"""
from __future__ import annotations

import pytest


from knowledge_base.service import kbase_write_service       # noqa: E402
from retrieval.service import write as write_service            # noqa: E402


class _Cursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_stubs(monkeypatch, events):
    monkeypatch.setattr(kbase_write_service.directory_store, 'titles_by_ids',
                        lambda kbase_id, ids: events.append(('titles', list(ids))) or ['a.md', 'b.pdf'])
    monkeypatch.setattr(kbase_write_service.directory_store, 'delete_files',
                        lambda cursor, kbase_id, ids: events.append(('soft_delete', list(ids))))
    monkeypatch.setattr(kbase_write_service.directory_store, 'connection',
                        lambda: _Conn())
    monkeypatch.setattr(kbase_write_service.kbase_store, 'select_kbase_by_id',
                        lambda kbase_id: {'table_name': 'data_kb_index_demo'})
    monkeypatch.setattr(kbase_write_service.graph_lifecycle, 'delete_chunks_by_sources',
                        lambda base, sources: events.append(('chunks', base, list(sources))))
    monkeypatch.setattr(kbase_write_service.write_service, 'delete_es_documents_by_query',
                        lambda kbase_id, field, ids: events.append(
                            ('es', kbase_id, field, list(ids))))
    monkeypatch.setattr(kbase_write_service.directory_store, 'delete_properties_by_file_ids',
                        lambda kbase_id, ids: events.append(
                            ('properties', kbase_id, list(ids))))

    class _Relation:
        @staticmethod
        def delete_by_directory_ids(pk_id, ids):
            events.append(('relations', pk_id, list(ids)))

    class _Storage:
        @staticmethod
        def delete_core_file(file_id):
            events.append(('disk', file_id))

    return _Relation, _Storage


def test_purge_files_deletes_chunk_rows_by_source_before_soft_delete(monkeypatch):
    events = []
    relation, storage = _install_stubs(monkeypatch, events)

    kbase_write_service._purge_files('kb-1', 7, ['f1', 'f2'], relation, storage)

    # 顺序：取名字 → relation/向量 → ES → chunk 表 → 属性 → 软删 → 磁盘
    assert [e[0] for e in events] == [
        'titles', 'relations', 'es', 'chunks', 'properties', 'soft_delete', 'disk', 'disk',
    ]
    assert events[0] == ('titles', ['f1', 'f2'])
    assert events[1] == ('relations', 7, ['f1', 'f2'])
    assert events[2] == ('es', 'kb-1', 'file_id', ['f1', 'f2'])
    assert events[3] == ('chunks', 'data_kb_index_demo', ['a.md', 'b.pdf'])
    assert events[4] == ('properties', 'kb-1', ['f1', 'f2'])


def test_embedding_rollback_deletes_relations_and_es(monkeypatch):
    from knowledge_base.task import handlers

    events = []
    monkeypatch.setattr(handlers, '_kbase_row', lambda kbase_id: {'id': 7})
    monkeypatch.setattr(handlers.node_relation_store, 'delete_by_directory_ids',
                        lambda pk_id, ids: events.append(('relations', pk_id, list(ids))))
    monkeypatch.setattr(write_service, 'delete_es_documents_by_query',
                        lambda kbase_id, field, ids: events.append(
                            ('es', kbase_id, field, list(ids))))

    handlers.FileEmbeddingHandler().rollback({'kbaseId': 'kb-1', 'fileId': 'f1'})

    assert events == [
        ('relations', 7, ['f1']),
        ('es', 'kb-1', 'file_id', ['f1']),
    ]


def test_purge_files_skips_when_no_ids(monkeypatch):
    events = []
    relation, storage = _install_stubs(monkeypatch, events)

    kbase_write_service._purge_files('kb-1', 7, [], relation, storage)

    assert events == []


def test_purge_files_tolerates_kbase_without_table_name(monkeypatch):
    """``table_name`` 为空时不能拼出 ``None_chunk`` —— 跳过 chunk 清理即可。"""
    events = []
    relation, storage = _install_stubs(monkeypatch, events)
    monkeypatch.setattr(kbase_write_service.kbase_store, 'select_kbase_by_id',
                        lambda kbase_id: {'table_name': None})

    kbase_write_service._purge_files('kb-1', 7, ['f1'], relation, storage)

    assert [e[0] for e in events] == [
        'titles', 'relations', 'properties', 'soft_delete', 'disk']


def test_purge_files_graph_purges_graph_and_vectors_before_chunk_rows(monkeypatch):
    """图谱库删文件：先按 source 取 chunk id → 删实体/边/向量 → 再删 chunk 行。

    只删 chunk 会漏掉 graph storage 实体/边，已删文件的知识仍可检索。
    """
    events = []
    relation, storage = _install_stubs(monkeypatch, events)
    monkeypatch.setattr(kbase_write_service.kbase_store, 'select_kbase_by_id',
                        lambda kbase_id: {'table_name': 'graph_demo', 'category': 10})
    monkeypatch.setattr(kbase_write_service.graph_lifecycle, 'chunk_ids_for_sources',
                        lambda base, sources: events.append(('chunk_ids', base, list(sources)))
                        or ['c1', 'c2'])
    monkeypatch.setattr(kbase_write_service.graph_lifecycle, 'delete_source_graph_data',
                        lambda base, kbase_id, ids: events.append(
                            ('graph_purge', base, kbase_id, list(ids))))

    kbase_write_service._purge_files('kb-1', 7, ['f1'], relation, storage)

    names = [event[0] for event in events]
    assert names.index('graph_purge') < names.index('chunks')
    purge = events[names.index('graph_purge')]
    assert purge == ('graph_purge', 'graph_demo', 'kb-1', ['c1', 'c2'])


def test_purge_files_document_does_not_touch_graph(monkeypatch):
    events = []
    relation, storage = _install_stubs(monkeypatch, events)
    monkeypatch.setattr(kbase_write_service.graph_lifecycle, 'delete_source_graph_data',
                        lambda *a, **k: pytest.fail('document KB must not purge graph storage'))

    kbase_write_service._purge_files('kb-1', 7, ['f1'], relation, storage)

    assert 'graph_purge' not in [event[0] for event in events]


def test_embedding_rollback_deletes_chunk_rows(monkeypatch):
    """失败重试会生成新 chunk uuid；rollback 必须删掉旧 chunk 行。"""
    from knowledge_base.task import handlers

    events = []
    monkeypatch.setattr(handlers, '_kbase_row',
                        lambda _id: {'id': 7, 'table_name': 'data_kb_index_demo'})
    monkeypatch.setattr(handlers.node_relation_store, 'delete_by_directory_ids',
                        lambda pk_id, ids: events.append(('relations', list(ids))))
    monkeypatch.setattr(handlers.chunk_store, 'delete_chunk_by_id',
                        lambda kbase, chunk_id: events.append(('chunk', chunk_id)))
    monkeypatch.setattr(write_service, 'delete_es_documents_by_query',
                        lambda *a: events.append(('es',)))

    handlers.FileEmbeddingHandler().rollback({
        'kbaseId': 'kb-1', 'fileId': 'f1',
        'splitResult': {'chunks': [{'id': 'c1'}, {'id': 'c2'}]}})

    assert ('chunk', 'c1') in events
    assert ('chunk', 'c2') in events
