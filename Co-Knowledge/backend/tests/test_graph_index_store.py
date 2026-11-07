"""图谱向量索引/切片落表（``graph_index_store``）。

## 这个文件为什么存在

导入图数据后必须有向量化/切片落表这步 —— 否则检索端查的
``graph_<uuid>_vector`` 永远不存在，图谱检索静默返回空。这里钉住三件事：

1. 检索端的硬契约：``key_id`` / ``key_type`` / ``labels``；**边行的 key_id 是
   ``"<source>,<target>"``**（``_extract_entity_ids_from_records`` 按逗号拆）；
2. 文本拼法（影响召回，不影响正确性）与过滤（空文本跳过）；
3. 分批向量化：一次 ``embed_many`` 发一批，条数不符要显式报错（不静默截断）。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from graph.repository import graph_index_store as store  # noqa: E402


# ----------------------------------------------------------------------
# 纯函数：文本与键
# ----------------------------------------------------------------------


def test_entity_text_contains_type_and_properties():
    text = store.entity_text({
        'entity_id': 'Person_001', 'entity_type': 'Person',
        'properties': {'name': '张三', 'age': 30},
    })

    assert text.splitlines() == ['entity_type: Person', 'name: 张三', 'age: 30']


def test_edge_text_contains_both_endpoints():
    text = store.edge_text({
        'edge_id': 'WorksAt_001', 'edge_type': 'WorksAt',
        'source_id': 'Person_001', 'target_id': 'Company_001',
        'properties': {'position': '工程师'},
    })

    assert text.splitlines() == [
        'edge_type: WorksAt', 'source_id: Person_001',
        'target_id: Company_001', 'position: 工程师']


def test_edge_key_id_uses_edge_id():
    """边的业务身份是 edge_id，平行边不再相撞。"""
    assert store.edge_key_id(
        {'edge_id': 'Knows_1', 'source_id': 'A', 'target_id': 'B'}) == 'Knows_1'
    assert store.edge_key_id({'source_id': 'A', 'target_id': 'B'}) == ''


def test_chunk_text_prefers_content_expand_then_text():
    assert store.chunk_text({'content_expand': '正文', 'text': 'ignored'}) == '正文'
    assert store.chunk_text({'text': '退路'}) == '退路'
    assert store.chunk_text({}) == ''


def test_labels_only_keeps_strings():
    assert store._labels({'labels': ['核心成员', '', None, 3]}) == ['核心成员', '3']
    assert store._labels({}) == []


# ----------------------------------------------------------------------
# zip 读取
# ----------------------------------------------------------------------


def _zip_with(tmp_path: Path, entries: dict) -> str:
    path = tmp_path / 'graph.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, lines in entries.items():
            archive.writestr(name, '\n'.join(lines))
    return str(path)


def test_read_jsonl_skips_bad_lines(tmp_path):
    zip_path = _zip_with(tmp_path, {'entities.jsonl': [
        json.dumps({'entity_id': 'A'}),
        '{bad json',
        json.dumps(['not', 'a', 'dict']),
        '',
        json.dumps({'entity_id': 'B'}),
    ]})

    rows = store.read_jsonl(zip_path, 'entities.jsonl')

    assert [row['entity_id'] for row in rows] == ['A', 'B']


def test_read_jsonl_missing_entry_is_empty(tmp_path):
    zip_path = _zip_with(tmp_path, {'entities.jsonl': []})

    assert store.read_jsonl(zip_path, 'document_chunk.jsonl') == []


# ----------------------------------------------------------------------
# build_index 编排（DB 写入用桩替换）
# ----------------------------------------------------------------------


def _install_db_stubs(monkeypatch, events):
    monkeypatch.setattr(
        store, 'ensure_vector_table',
        lambda base, dimension=None, **kwargs: events.append(
            ('ensure_vector', base, kwargs)))
    monkeypatch.setattr(store, 'ensure_chunk_table', lambda base: events.append(('ensure_chunk', base)))
    monkeypatch.setattr(store, 'ensure_vector_indexes',
                        lambda base, dimension=None: events.append(('ensure_indexes', base)))

    def fake_upsert(base, key_type, rows, **kwargs):
        rows = list(rows)
        events.append(('upsert', key_type, rows, kwargs))
        return len(rows)

    monkeypatch.setattr(store, 'upsert_vectors', fake_upsert)

    def fake_chunks(base, kbase_id, records):
        events.append(('chunks', kbase_id, [r['id'] for r in records]))
        return len(records)

    monkeypatch.setattr(store, 'replace_chunks', fake_chunks)


def test_build_index_wires_entities_edges_and_chunks(monkeypatch, tmp_path):
    events = []
    _install_db_stubs(monkeypatch, events)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [json.dumps({
            'entity_id': 'Person_001', 'entity_type': 'Person',
            'properties': {'name': '张三'}, 'labels': ['核心']})],
        'edges.jsonl': [json.dumps({
            'edge_id': 'WorksAt_001', 'edge_type': 'WorksAt',
            'source_id': 'Person_001', 'target_id': 'Company_001',
            'properties': {'position': '工程师'}})],
        'document_chunk.jsonl': [json.dumps({
            'id': 'c1', 'source': 'a.md', 'chunk_id': 1,
            'content_expand': '切片正文'})],
    })
    calls = []

    def embed_many(texts, model):
        calls.append((list(texts), model))
        return [[0.1, 0.2] for _ in texts]

    stats = store.build_index('graph_demo', 'kb-1', zip_path, 'm', embed_many)

    assert stats == {'entities': 1, 'edges': 1, 'chunks': 1, 'chunk_rows': 1,
                     'skipped': 0, 'collisions': 0}
    assert any(event[0] == 'ensure_vector' and event[1] == 'graph_demo'
               for event in events)
    assert ('ensure_chunk', 'graph_demo') in events
    assert ('chunks', 'kb-1', ['c1']) in events
    upserts = {e[1]: e[2] for e in events if e[0] == 'upsert'}
    assert upserts['entity'][0][0] == 'Person_001'
    assert upserts['entity'][0][2] == ['核心']
    # 边身份用 edge_id；端点单独落列。
    assert upserts['edge'][0][0] == 'WorksAt_001'
    assert upserts['edge'][0][5] == 'Person_001'
    assert upserts['edge'][0][6] == 'Company_001'
    assert upserts['chunk'][0][0] == 'c1'
    # 三类各一次 embed_many，模型名原样透传
    assert [c[1] for c in calls] == ['m', 'm', 'm']


def test_build_index_skips_blank_text(monkeypatch, tmp_path):
    events = []
    _install_db_stubs(monkeypatch, events)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [json.dumps({'entity_id': 'E1'})],   # 没有 type/properties
        'edges.jsonl': [],
        'document_chunk.jsonl': [],
    })

    stats = store.build_index('graph_demo', 'kb-1', zip_path, None, lambda t, m: [])
    # 没有 entity_type 也没有 properties → 文本为空 → 跳过，**不调网关**
    assert stats['entities'] == 0
    assert stats['skipped'] == 1


def test_build_index_rejects_embedding_count_mismatch(monkeypatch, tmp_path):
    events = []
    _install_db_stubs(monkeypatch, events)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [json.dumps({
            'entity_id': 'E1', 'entity_type': 'Person', 'properties': {'n': 1}})],
    })

    import pytest

    with pytest.raises(store.GraphIndexError):
        store.build_index('graph_demo', 'kb-1', zip_path, None, lambda texts, m: [])


def test_build_index_filters_to_imported_success_sets(monkeypatch, tmp_path):
    """只给导入成功的实体/边建向量，避免 PG 指向不存在的记录。"""
    events = []
    _install_db_stubs(monkeypatch, events)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [
            json.dumps({'entity_id': 'E1', 'entity_type': 'Person',
                        'properties': {'n': 1}}),
            json.dumps({'entity_id': 'E2', 'entity_type': 'Person',
                        'properties': {'n': 2}}),
        ],
        'edges.jsonl': [
            json.dumps({'edge_id': 'R1', 'edge_type': 'Knows',
                        'source_id': 'E1', 'target_id': 'E2'}),
            json.dumps({'edge_id': 'R2', 'edge_type': 'Knows',
                        'source_id': 'E2', 'target_id': 'E1'}),
        ],
    })

    stats = store.build_index(
        'graph_demo', 'kb-1', zip_path, 'm', lambda texts, m: [[0.1] for _ in texts],
        entity_ids={'Person': {'E1'}},
        edge_ids={'Knows': {'R1'}},
    )

    assert stats['entities'] == 1
    assert stats['edges'] == 1
    assert stats['skipped'] == 2
    upserts = {e[1]: e[2] for e in events if e[0] == 'upsert'}
    assert [row[0] for row in upserts['entity']] == ['E1']
    assert [row[0] for row in upserts['edge']] == ['R1']


def test_build_index_merges_colliding_key_ids_instead_of_dropping(monkeypatch, tmp_path):
    """跨 class 同 entity_id / 同端点多条边：合并文本与 labels，不静默丢后一条。"""
    events = []
    _install_db_stubs(monkeypatch, events)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [
            json.dumps({'entity_id': 'E1', 'entity_type': 'Person',
                        'properties': {'name': '张三'}, 'labels': ['核心']}),
            json.dumps({'entity_id': 'E1', 'entity_type': 'Employee',
                        'properties': {'name': '张三'}, 'labels': ['员工']}),
        ],
    })

    stats = store.build_index(
        'graph_demo', 'kb-1', zip_path, 'm', lambda texts, m: [[0.1] for _ in texts])

    assert stats['entities'] == 1
    assert stats['collisions'] == 1
    row = next(e[2] for e in events if e[0] == 'upsert' and e[1] == 'entity')[0]
    assert row[0] == 'E1'
    assert 'entity_type: Person' in row[1]
    assert 'entity_type: Employee' in row[1]
    assert row[2] == ['员工', '核心']


def test_build_index_defaults_labels_to_entity_and_edge_type(monkeypatch, tmp_path):
    """抽取算子不产 labels 时，按类型打标，保证 labels 过滤可用。"""
    events = []
    _install_db_stubs(monkeypatch, events)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [json.dumps({
            'entity_id': 'Person_1', 'entity_type': 'Person',
            'properties': {'name': '张三'}})],
        'edges.jsonl': [json.dumps({
            'edge_id': 'Knows_1', 'edge_type': 'Knows',
            'source_id': 'Person_1', 'target_id': 'Person_2'})],
    })

    store.build_index(
        'graph_demo', 'kb-1', zip_path, 'm',
        lambda texts, m: [[0.1] for _ in texts])

    rows = {e[1]: e[2] for e in events if e[0] == 'upsert'}
    assert rows['entity'][0][2] == ['Person']
    assert rows['edge'][0][2] == ['Knows']


# ----------------------------------------------------------------------
# 批量导入快路径：卸索引 → 多行装载 → 一次建索引
# ----------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConnection:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return _FakeCursor(self.log)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_upsert_vectors_uses_one_multi_row_statement(monkeypatch):
    log = []
    monkeypatch.setattr(store, 'connection', lambda: _FakeConnection(log))

    rows = [
        ('e1', 'text1', ['Entity'], [0.1, 0.2], None, None, None),
        ('e2', 'text2', ['Entity'], [0.3, 0.4], 'r1', 'e1', 'e2'),
    ]
    assert store.upsert_vectors('graph_demo', 'entity', rows,
                                bulk=True, on_conflict=False) == 2

    assert log[0][0] == 'SET LOCAL synchronous_commit = off'
    sql, params = log[-1]
    assert sql.count('(%s, %s, %s, %s, %s::vector, %s, %s, %s)') == 2
    assert 'ON CONFLICT' not in sql
    assert len(params) == 16


def test_upsert_vectors_can_keep_on_conflict(monkeypatch):
    log = []
    monkeypatch.setattr(store, 'connection', lambda: _FakeConnection(log))
    store.upsert_vectors('graph_demo', 'entity',
                         [('e1', 'text1', ['Entity'], [0.1],
                           None, None, None)])
    sql, _ = log[-1]
    assert 'ON CONFLICT (key_type, key_id) DO UPDATE' in sql


def test_build_index_bulk_empty_table_rebuilds_all_indexes(monkeypatch, tmp_path):
    events = []
    _install_db_stubs(monkeypatch, events)
    monkeypatch.setattr(store, '_vector_table_empty', lambda base: True)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [json.dumps({
            'entity_id': 'Person_1', 'entity_type': 'Person',
            'properties': {'name': '张三'}})],
        'edges.jsonl': [json.dumps({
            'edge_id': 'Knows_1', 'edge_type': 'Knows',
            'source_id': 'Person_1', 'target_id': 'Person_2'})],
    })
    progress = []

    store.build_index('graph_demo', 'kb-1', zip_path, 'm',
                      lambda texts, m: [[0.1] for _ in texts],
                      bulk=True, progress_cb=progress.append)

    ensure = next(event for event in events if event[0] == 'ensure_vector')
    assert ensure[2] == {'with_hnsw': False, 'with_secondary_indexes': False}
    assert any(event[0] == 'ensure_indexes' for event in events)
    upserts = [event for event in events if event[0] == 'upsert']
    assert all(event[3]['on_conflict'] is False for event in upserts)
    assert progress[-1] == 100
    assert 95 in progress


def test_build_index_bulk_non_empty_table_keeps_secondary_indexes(monkeypatch, tmp_path):
    events = []
    _install_db_stubs(monkeypatch, events)
    monkeypatch.setattr(store, '_vector_table_empty', lambda base: False)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [json.dumps({
            'entity_id': 'Person_1', 'entity_type': 'Person',
            'properties': {'name': '张三'}})],
    })

    store.build_index('graph_demo', 'kb-1', zip_path, 'm',
                      lambda texts, m: [[0.1] for _ in texts], bulk=True)

    ensure = next(event for event in events if event[0] == 'ensure_vector')
    assert ensure[2] == {'with_hnsw': False, 'with_secondary_indexes': True}
    upserts = [event for event in events if event[0] == 'upsert']
    assert all(event[3]['on_conflict'] is True for event in upserts)
    assert any(event[0] == 'ensure_indexes' for event in events)


def test_ensure_vector_table_can_drop_all_indexes(monkeypatch):
    log = []
    monkeypatch.setattr(store, 'connection', lambda: _FakeConnection(log))
    store.ensure_vector_table('graph_demo', 1024, with_hnsw=False,
                              with_secondary_indexes=False)
    sql = log[-1][0]
    assert 'DROP INDEX IF EXISTS kb_index.graph_demo_vector_type_key_uidx' in sql
    assert 'DROP INDEX IF EXISTS kb_index.graph_demo_vector_entity_hnsw' in sql
    assert 'DROP INDEX IF EXISTS kb_index.graph_demo_vector_edge_hnsw' in sql
    assert 'DROP INDEX IF EXISTS kb_index.graph_demo_vector_chunk_hnsw' in sql
    assert 'CREATE INDEX' not in sql


def test_ensure_vector_indexes_sets_maintenance_work_mem(monkeypatch):
    log = []
    monkeypatch.setattr(store, 'connection', lambda: _FakeConnection(log))
    store.ensure_vector_indexes('graph_demo')
    assert log[0][0].startswith('SET LOCAL maintenance_work_mem')
    hnsw = [sql for sql, _ in log if 'USING hnsw' in sql]
    assert len(hnsw) == 3
    assert any("WHERE key_type = 'entity'" in sql for sql in hnsw)
    assert any("WHERE key_type = 'edge'" in sql for sql in hnsw)
    assert any("WHERE key_type = 'chunk'" in sql for sql in hnsw)
    assert any('CREATE UNIQUE INDEX' in sql for sql, _ in log)


def test_ensure_vector_indexes_falls_back_to_serial_on_shm_error(monkeypatch):
    calls = []

    def fake_create(base, *, parallel, with_hnsw=True):
        calls.append(parallel)
        if parallel:
            raise RuntimeError('could not resize shared memory segment: '
                               'No space left on device')

    monkeypatch.setattr(store, '_create_indexes', fake_create)
    store.ensure_vector_indexes('graph_demo')
    assert calls == [store._PARALLEL_WORKERS, 0]


def test_ensure_vector_indexes_skips_hnsw_above_pgvector_limit(monkeypatch):
    log = []
    monkeypatch.setattr(store, 'connection', lambda: _FakeConnection(log))
    store.ensure_vector_indexes('graph_demo', 2560)
    assert not [sql for sql, _ in log if 'USING hnsw' in sql]
    assert any('CREATE UNIQUE INDEX' in sql for sql, _ in log)


def test_create_indexes_sets_parallel_workers(monkeypatch):
    log = []
    monkeypatch.setattr(store, 'connection', lambda: _FakeConnection(log))
    store._create_indexes('graph_demo', parallel=3)
    assert 'SET LOCAL max_parallel_maintenance_workers = 3' in [sql for sql, _ in log]
    assert 'SET LOCAL statement_timeout = 0' in [sql for sql, _ in log]


def test_entity_context_is_bidirectional_and_capped():
    edges = [
        {'source_id': 'A', 'target_id': 'B', 'edge_type': 'Knows'},
        {'source_id': 'B', 'target_id': 'C', 'edge_type': 'Likes'},
    ]
    context = store._entity_context(edges, limit=1)
    assert context['A'] == 'Knows: B'
    assert context['B'] == 'Knows: A'
    assert context['C'] == 'Likes: B'


def test_build_index_entity_text_includes_neighbor_context(monkeypatch, tmp_path):
    events = []
    _install_db_stubs(monkeypatch, events)
    zip_path = _zip_with(tmp_path, {
        'entities.jsonl': [
            json.dumps({'entity_id': 'Person_1', 'entity_type': 'Person',
                        'properties': {'name': '张三'}}),
            json.dumps({'entity_id': 'Company_1', 'entity_type': 'Company',
                        'properties': {'name': 'Acme'}}),
        ],
        'edges.jsonl': [json.dumps({
            'edge_id': 'WorksAt_1', 'edge_type': 'WorksAt',
            'source_id': 'Person_1', 'target_id': 'Company_1'})],
    })

    store.build_index('graph_demo', 'kb-1', zip_path, 'm',
                      lambda texts, m: [[0.1] for _ in texts])

    rows = {}
    for event in events:
        if event[0] == 'upsert' and event[1] == 'entity':
            for row in event[2]:
                rows[row[0]] = row
    assert 'relations: WorksAt: Company_1' in rows['Person_1'][1]
    assert 'relations: WorksAt: Person_1' in rows['Company_1'][1]
