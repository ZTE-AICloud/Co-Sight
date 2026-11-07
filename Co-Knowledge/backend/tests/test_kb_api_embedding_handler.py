"""``FileEmbeddingHandler`` 的切片表寻址。

`kb_kbase.table_name` 存的是**向量表** ``doc_<id>_vector``，切片表要按
``identifiers.chunk_table_for`` 派生（``doc_<id>_chunk``）。直接拼
``f'{table_name}_chunk'`` 会得到不存在的 ``doc_<id>_vector_chunk``，上传链在
三写第一步就 ``UndefinedTable`` —— 这条用例钉住派生规则。
"""

from knowledge_base.task import handlers


def test_embedding_handler_writes_to_the_derived_chunk_table(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        handlers, '_kbase_row',
        lambda kbase_id: {'id': 7, 'table_name': 'doc_kb1234_vector'})
    monkeypatch.setattr(
        handlers.write_service, 'save_chunks',
        lambda table, chunks: captured.setdefault('chunk_table', table))
    monkeypatch.setattr(handlers, '_update_status', lambda *args, **kwargs: None)

    handlers.FileEmbeddingHandler().handle({
        'fileId': 'f1',
        'kbaseId': 'kb1234',
        'splitResult': {'chunks': [], 'results': []},
    })

    assert captured['chunk_table'] == 'doc_kb1234_chunk'
