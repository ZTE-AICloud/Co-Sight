"""图谱导入引擎的纯逻辑测试。

引擎整体**已在容器里跑通完整往返**（导出 zip → 导进一次性 PostgreSQL 图谱库 →
任务 COMPLETED、实体 4/4、边 2/2 → 查回数据 → 清理）。这里钉的是不连库的那几块 ——
尤其是**计数不变量**与**端点校验**，它们在真实数据上很难构造。

跑法::

    python -m pytest tests/test_kb_api_graph_import_engine.py -q
"""

import zipfile

import pytest

from graph.service import graph_import_engine as engine  # noqa: E402


# ----------------------------------------------------------------------
# 名称归一
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw, expected', [
    ('abc', 'graph_abc'),
    ('graph_abc', 'graph_abc'),                # 已带前缀，**不重复加**
])
def test_to_graph_db_name(raw, expected):
    """``graph_`` 前缀不重复加 —— 否则会拼成 ``graph_graph_<id>``。"""
    assert engine.to_graph_db_name(raw) == expected


def test_to_graph_db_name_blank_raises():
    for bad in (None, '', '   '):
        with pytest.raises(ValueError):
            engine.to_graph_db_name(bad)


@pytest.mark.parametrize('raw, expected', [
    ('abc', 'abc'),
    ('graph_abc', 'abc'),
    (None, None),
])
def test_to_kbase_id(raw, expected):
    assert engine.to_kbase_id(raw) == expected


# ----------------------------------------------------------------------
# JSONL 读取
# ----------------------------------------------------------------------


def _zip_with(tmp_path, entries: dict):
    path = tmp_path / 'probe.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return str(path)


def test_for_each_json_line_counts_bad_json_and_continues(tmp_path):
    """坏行计入 failed 而**不中断**（后面那行照样处理）。"""
    path = _zip_with(tmp_path, {'entities.jsonl': '{bad\n{"a":1}\n'})
    counters = engine.Counters()
    seen = []
    engine._for_each_json_line(path, 'entities.jsonl',
                               lambda line_no, parsed, _c: seen.append(parsed), counters)
    assert seen == [{'a': 1}]
    assert (counters.total, counters.failed) == (1, 1)
    assert counters.failed_records[0]['error'] == 'Invalid JSON format'


def test_for_each_json_line_missing_entry_is_empty_not_error(tmp_path):
    """条目不存在等价于 0 条 —— 抽取可能只产出实体。"""
    path = _zip_with(tmp_path, {'entities.jsonl': '{"a":1}\n'})
    counters = engine.Counters()
    engine._for_each_json_line(path, 'edges.jsonl', lambda *_: None, counters)
    assert (counters.total, counters.failed) == (0, 0)


def test_for_each_json_line_skips_blank_lines(tmp_path):
    path = _zip_with(tmp_path, {'entities.jsonl': '\n  \n{"a":1}\n\n'})
    counters = engine.Counters()
    seen = []
    engine._for_each_json_line(path, 'entities.jsonl',
                               lambda _n, parsed, _c: seen.append(parsed), counters)
    assert seen == [{'a': 1}]
    assert counters.total == 0


def test_entry_name_is_exact_not_ends_with(tmp_path):
    """条目名是**精确匹配** —— 与 ``/graph/import`` 那个按 endsWith 找 desc.json
    的宽松规则不同，别混。"""
    path = _zip_with(tmp_path, {'my_entities.jsonl': '{"a":1}\n'})
    counters = engine.Counters()
    seen = []
    engine._for_each_json_line(path, 'entities.jsonl',
                               lambda _n, parsed, _c: seen.append(parsed), counters)
    assert seen == []


def test_failure_record_id_falls_back_to_kind_and_line():
    assert engine._failure(None, 7, 'entity', 'x')['id'] == 'entity_line_7'
    assert engine._failure('Person_1', 7, 'entity', 'x')['id'] == 'Person_1'


def test_counters_start_at_zero():
    counters = engine.Counters()
    assert (counters.total, counters.success, counters.failed) == (0, 0, 0)
    assert counters.failed_records == []


def test_build_pg_index_forwards_imported_success_sets(monkeypatch):
    """索引只覆盖导入成功集合。"""
    from graph.repository import graph_index_store
    from knowledge_base.service import kbase_service as kbase_store

    captured = {}
    monkeypatch.setattr(kbase_store, 'get_kbase_row',
                        lambda _id: {'table_name': 'graph_demo',
                                     'embedding_model': 'm'})
    monkeypatch.setattr(graph_index_store, 'build_index',
                        lambda **kwargs: captured.update(kwargs) or {'ok': True})

    result = engine.build_pg_index(
        'graph_kb-1', 'z.zip',
        {'Person': {'E1'}}, {'Knows': {'R1'}})

    assert result == {'ok': True}
    assert captured['entity_ids'] == {'Person': {'E1'}}
    assert captured['edge_ids'] == {'Knows': {'R1'}}
    assert captured['base'] == 'graph_demo'


def test_import_edges_accepts_any_matching_definition(tmp_path, monkeypatch):
    """同一 edge_type 可有多条定义，匹配其中任意一条即合法。

    schema 里 ``Contain`` 可以同时声明 Product→Function、Business→Task、
    Function→OperationStep；用 ``{edge_type: def}`` 取字典**只剩最后一条**，
    会把另外两类的合法边全判成「endpoint not present as declared type」——
    真实测试包导入出现 11/30 条边被跳过（状态 104）就是这条引起的。
    """
    import json
    from types import SimpleNamespace

    written = []
    monkeypatch.setattr(engine.graph_pg, 'upsert_edges_bulk',
                        lambda _db, rows: written.extend(
                            (row[0], row[1]) for row in rows))

    schema = {'edges': [
        {'edge_type': 'Contain', 'source_entity': 'Product', 'target_entity': 'Function'},
        {'edge_type': 'Contain', 'source_entity': 'Business', 'target_entity': 'Task'},
        {'edge_type': 'Contain', 'source_entity': 'Function',
         'target_entity': 'OperationStep'},
    ]}
    records = [
        {'edge_id': 'Contain_1', 'edge_type': 'Contain',
         'source_id': 'Product_1', 'target_id': 'Function_1'},
        {'edge_id': 'Contain_2', 'edge_type': 'Contain',
         'source_id': 'Business_1', 'target_id': 'Task_1'},
        {'edge_id': 'Contain_3', 'edge_type': 'Contain',
         'source_id': 'Function_1', 'target_id': 'OperationStep_1'},
        # 不在任何一条定义里：Product → Task
        {'edge_id': 'Contain_4', 'edge_type': 'Contain',
         'source_id': 'Product_1', 'target_id': 'Task_1'},
    ]
    path = _zip_with(tmp_path, {'edges.jsonl': '\n'.join(json.dumps(r) for r in records)})
    imported = {
        'Product': {'Product_1'},
        'Function': {'Function_1'},
        'Business': {'Business_1'},
        'Task': {'Task_1'},
        'OperationStep': {'OperationStep_1'},
    }
    counters = engine.Counters()

    result = engine.import_edges(SimpleNamespace(dbname='graph_demo'), path,
                                 schema, imported, counters)

    assert counters.total == 4
    assert counters.success == 3
    assert counters.failed == 1
    assert counters.failed_records[0]['id'] == 'Contain_4'
    assert result['Contain'] == {'Contain_1', 'Contain_2', 'Contain_3'}
    assert [edge_id for _type, edge_id in written] == ['Contain_1', 'Contain_2', 'Contain_3']


def test_import_entities_bulk_counts_and_falls_back(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    schema = {'entities': [{'entity_type': 'Person'}]}
    path = _zip_with(tmp_path, {'entities.jsonl': '\n'.join(json.dumps({
        'entity_type': 'Person', 'entity_id': f'P{i}',
        'properties': {'name': f'n{i}'}}) for i in range(3))})
    client = SimpleNamespace(dbname='graph_demo')
    imported = []

    def bulk(_db, rows):
        imported.extend(row[1] for row in rows)
        raise RuntimeError('bulk failed')

    monkeypatch.setattr(engine.graph_pg, 'upsert_entities_bulk', bulk)
    per_row = []
    monkeypatch.setattr(engine.graph_pg, 'upsert_entity',
                        lambda _db, etype, eid, props, labels: per_row.append(eid))
    counters = engine.Counters()

    result = engine.import_entities(client, path, schema, counters)

    assert counters.total == 3
    assert counters.success == 3
    assert counters.failed == 0
    assert per_row == ['P0', 'P1', 'P2']
    assert result == {'Person': {'P0', 'P1', 'P2'}}


def test_import_edges_bulk_falls_back_to_per_row(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    schema = {'edges': [{'edge_type': 'Knows', 'source_entity': 'Person',
                         'target_entity': 'Person'}]}
    path = _zip_with(tmp_path, {'edges.jsonl': json.dumps({
        'edge_id': 'R1', 'edge_type': 'Knows',
        'source_id': 'P1', 'target_id': 'P2'})})
    monkeypatch.setattr(engine.graph_pg, 'upsert_edges_bulk',
                        lambda _db, rows: (_ for _ in ()).throw(RuntimeError('bulk')))
    per_row = []
    monkeypatch.setattr(engine.graph_pg, 'upsert_edge',
                        lambda _db, etype, eid, *_rest: per_row.append(eid))
    counters = engine.Counters()

    result = engine.import_edges(SimpleNamespace(dbname='graph_demo'), path, schema,
                                 {'Person': {'P1', 'P2'}}, counters)

    assert counters.total == 1
    assert counters.success == 1
    assert per_row == ['R1']
    assert result == {'Knows': {'R1'}}
