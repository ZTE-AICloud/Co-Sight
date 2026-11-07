"""图谱导出（``POST /graph/export``）的纯函数测试。

钉的是**格式层**那几处 —— 它们不影响 JSON 语义，但文本比对会露出来，
而「差不多」的实现（比如直接用 ``json.dumps(indent=2)``）会静默产出另一个形状，
消费方拿去做文本比对或 diff 时才发现。

跑法::

    python -m pytest tests/test_kb_api_graph_export.py -q
"""

import json
import zipfile
from io import BytesIO

import pytest

from graph.service import graph_export_service as svc  # noqa: E402


# ----------------------------------------------------------------------
# 缩进输出格式（与 Python 的 json.dumps 形状不同）
# ----------------------------------------------------------------------


def test_pretty_object_uses_spaced_colon():
    """键值之间是 ``" : "``（Python 默认 ``": "``）。"""
    assert svc._pretty({'a': 1}) == b'{\n  "a" : 1\n}'


def test_pretty_has_no_trailing_newline():
    """输出写完就结束，不补 newline；``json.dumps`` 也没有，但别自己加。"""
    assert not svc._pretty({'a': 1}).endswith(b'\n')


def test_pretty_array_hugs_brackets():
    """数组是 ``[ 1, 2 ]`` —— 括号贴着元素、元素间 ``", "``。

    Python 的 ``indent=2`` 会把每个元素单独换行，那是另一个形状。
    """
    assert svc._pretty([1, 2]) == b'[ 1, 2 ]'


def test_pretty_empty_containers():
    assert svc._pretty({}) == b'{ }'
    assert svc._pretty([]) == b'[ ]'


def test_pretty_nested_array_of_objects_matches_source_shape():
    """schema.json 的形状：数组里的对象多行，数组括号留在同一行。"""
    value = {'entities': [{'type': 'Person', 'properties': [{'name': 'n'}]}]}
    expected = (
        '{\n'
        '  "entities" : [ {\n'
        '    "type" : "Person",\n'
        '    "properties" : [ {\n'
        '      "name" : "n"\n'
        '    } ]\n'
        '  } ]\n'
        '}'
    )
    assert svc._pretty(value).decode() == expected


def test_pretty_keeps_non_ascii_raw():
    """``ensure_ascii=False`` —— 输出中文原文，不是 ``\\uXXXX``。"""
    assert b'\xe4\xba\xba\xe7\x89\xa9' in svc._pretty({'desc': '人物'})


def test_pretty_booleans_and_numbers_are_json_literals():
    assert svc._pretty({'ok': True, 'n': 30}) == b'{\n  "ok" : true,\n  "n" : 30\n}'


# ----------------------------------------------------------------------
# jsonl：紧凑分隔符 + 每条一行 + 末尾换行
# ----------------------------------------------------------------------


def test_jsonl_is_compact():
    """JSONL 用不带 pretty printer 的 writer：``{"a":1}`` 而不是 ``{"a": 1}``。"""
    assert svc._jsonl([{'a': 1, 'b': 'x'}]) == b'{"a":1,"b":"x"}\n'


def test_jsonl_one_line_each_and_trailing_newline():
    assert svc._jsonl([{'a': 1}, {'b': 2}]) == b'{"a":1}\n{"b":2}\n'


def test_jsonl_empty_is_empty_bytes():
    assert svc._jsonl([]) == b''


# ----------------------------------------------------------------------
# 实体/边行：键序与属性过滤
# ----------------------------------------------------------------------


def test_entity_line_key_order_and_drops_labels_from_properties():
    """``#labels`` 只作为**行级** ``labels``，不进 ``properties``。"""
    row = {'entity_id': 'Person_001', 'name': '张三', 'age': 30,
           '#labels': ['核心成员'], '@rid': '#26:0'}
    line = svc._entity_line('Person', row, ['name', 'age'])
    assert list(line) == ['entity_type', 'entity_id', 'properties', 'labels']
    assert line['properties'] == {'name': '张三', 'age': 30}
    assert line['labels'] == ['核心成员']


def test_entity_line_omits_labels_when_absent():
    line = svc._entity_line('Person', {'entity_id': 'x', 'name': 'n'}, ['name'])
    assert 'labels' not in line


def test_edge_line_key_order():
    row = {'edge_id': 'WorksAt_001', 'target_id': 'Company_001',
           'source_id': 'Person_001', 'position': '工程师'}
    line = svc._edge_line('WorksAt', row, ['position'])
    assert list(line) == ['edge_id', 'target_id', 'source_id', 'edge_type', 'properties']
    assert line['properties'] == {'position': '工程师'}


def test_properties_empty_when_schema_declares_nothing():
    """schema 没声明属性 → ``{}``（不是把整行塞进去）。"""
    assert svc._filter_properties({'name': 'x'}, [], frozenset()) == {}


def test_properties_drop_system_and_null_values():
    """丢弃三类：系统字段（``@``/``out``/``in``）、值为 null 的、以及不在 schema 里的。

    注意 ``age`` 虽在 schema 里但值为 null → 也丢（只保留非 null 值）。
    """
    row = {'name': 'x', 'age': None, '@class': 'V', 'out': '#1:0', 'undeclared': 1}
    assert svc._filter_properties(row, ['name', 'age'], frozenset()) == {'name': 'x'}


# ----------------------------------------------------------------------
# zip 打包
# ----------------------------------------------------------------------


def test_zip_entries_in_source_order_and_skips_missing():
    """条目序固定；``entities.jsonl`` 缺席时不补空文件（那正是导出失败的来源）。"""
    content = svc._zip({'desc.json': b'{}', 'edges.jsonl': b''})
    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert archive.namelist() == ['desc.json', 'edges.jsonl']


def test_zip_roundtrip_content():
    content = svc._zip({'desc.json': '中文'.encode()})
    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert archive.read('desc.json') == '中文'.encode()


# ----------------------------------------------------------------------
# 导出夹具
# ----------------------------------------------------------------------


def test_desc_json_keys_and_id_shape():
    """``id`` 是 ``graph_<uuid>``（带前缀），不是裸 uuid。"""
    kbase = {'name': 'kb', 'kbase_id': 'a' * 32, 'embedding_model': 'm',
             'description': 'd'}
    payload = json.loads(svc._desc_json(kbase))
    assert payload == {'name': 'kb', 'id': 'graph_' + 'a' * 32,
                       'embedding': 'm', 'desc': 'd'}


def test_blank_kb_id_is_literal_validation_error():
    """``@NotBlank(message="知识库ID不能为空")`` 是**内联中文**，恒中文、码 0004。"""
    from shared.errors.api import KbLiteralValidationError

    with pytest.raises(KbLiteralValidationError) as caught:
        svc.export_graph({'kbId': '  '})
    assert caught.value.code == '0004'
    assert caught.value.render('en') == '知识库ID不能为空'


# ----------------------------------------------------------------------
# document_chunk.jsonl：物理列映射
# ----------------------------------------------------------------------


def test_chunk_line_maps_physical_columns():
    line = svc._chunk_line({
        'id': 'c1', 'source': 'a.md', 'label': 'L', 'spilt_type': 'system',
        'table_id': 't1', 'content_expand': '正文', 'table_name': 't',
        'chunk_id': 3, 'chunk_index': '0',
        'text': '正文', 'chunk_order': 1,
    })

    assert line['id'] == 'c1'
    assert line['type'] == 'system'
    assert line['content_expand'] == '正文'
    assert line['chunk_id'] == 3
    assert line['text'] == '正文'
    assert line['chunk_index'] == '0'


def test_chunk_line_key_order_starts_with_base_keys():
    line = svc._chunk_line({'id': 'c1'})
    assert list(line)[:len(svc.CHUNK_BASE_KEYS)] == list(svc.CHUNK_BASE_KEYS)


def test_chunk_rows_uses_physical_columns_and_rejects_illegal_table(monkeypatch):
    from infrastructure.db import kb as db

    class _Cursor:
        description = [('id',), ('text',)]
        sql = ''

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            return [True]

        def fetchall(self):
            return [('c1', '正文')]

    class _Conn:
        def __init__(self):
            self.cursor_obj = _Cursor()

        def cursor(self):
            return self.cursor_obj

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    conn = _Conn()
    monkeypatch.setattr(db, 'connection', lambda: conn)

    rows = svc._chunk_rows('kb_index.graph_demo_chunk')

    assert rows == [{'id': 'c1', 'text': '正文'}]
    assert 'metadata' not in conn.cursor_obj.sql
    assert 'content_expand' in conn.cursor_obj.sql

    with pytest.raises(ValueError):
        svc._chunk_rows('kb_index.graph_demo; DROP TABLE x')


def test_export_document_chunk_surfaces_unexpected_error(monkeypatch):
    monkeypatch.setattr(svc, '_chunk_rows', lambda table: (_ for _ in ()).throw(
        RuntimeError('bad schema')))

    with pytest.raises(Exception) as caught:
        svc._export_document_chunk('a' * 32)

    assert getattr(caught.value, 'key', None) == 'graph.export.failed'
