"""切片域（``/chunk``）的纯逻辑测试。

这一族最容易写错的是**新旧库分流**（``content_expand`` 存 chunkId 还是真实内容）
—— 一旦反了，列表里的 ``supplement`` 会静默变成一串 uuid（或反过来把 uuid
当内容显示）。真实链路需要真库，这里只钉纯逻辑分流。

> ``_node_content`` 的转义与 ``_update_json_node_value`` 的嵌套改写见
> ``compat/kb_api/store/node_format.py``；格式本身的等价性由
> ``tests/test_kb_api_node_format.py`` 钉住。

跑法::

    python -m pytest tests/test_kb_api_chunk_service.py -q
"""


from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = SERVICE_ROOT / 'src'

from knowledge_base.service import chunk_service as service  # noqa: E402


# ----------------------------------------------------------------------
# _build_chunk_metadata：平铺（没有嵌套副本）
# ----------------------------------------------------------------------


def test_build_chunk_metadata_is_flat():
    """落库的 metadata 只有那 3 个业务键，**没有**任何框架脚手架。"""
    metadata = service._build_chunk_metadata('EXPAND', 'file.md')
    assert metadata == {
        'content_expand': 'EXPAND',
        'source': 'file.md',
        'type': 1,
    }


def test_build_chunk_metadata_key_order_is_stable():
    """键序稳定：``to_search_doc`` 把这份 dict 原样透给前端，顺序变了响应字节就变了。"""
    metadata = service._build_chunk_metadata('E', 'f')
    assert list(metadata) == ['content_expand', 'source', 'type']


# ----------------------------------------------------------------------
# supplement 分流
# ----------------------------------------------------------------------


def test_supplement_uses_chunk_text_for_new_kbase():
    metadata = {'content_expand': 'chunk-1'}
    row = {'id': 'chunk-1', 'text': '真实补充内容'}
    assert service._supplement_of(metadata, row) == '真实补充内容'


def test_supplement_prefers_metadata_when_chunk_text_blank():
    """新库但 chunk 行没 text（或 text 全空白）→ 用 metadata 里的值。"""
    metadata = {'content_expand': 'chunk-1'}
    assert service._supplement_of(metadata, {'id': 'chunk-1', 'text': '   '}) == 'chunk-1'


def test_supplement_empty_without_metadata():
    assert service._supplement_of(None, None) == ''
    assert service._supplement_of({}, None) == ''
    assert service._supplement_of({'content_expand': None}, None) == ''


# ----------------------------------------------------------------------
# extractChunkIdFromMetadata / extracted
# ----------------------------------------------------------------------


def test_chunk_id_of_reads_content_expand():
    assert service._chunk_id_of({'metadata': {'content_expand': 'cid'}}) == 'cid'
    assert service._chunk_id_of({'metadata': {}}) is None
    assert service._chunk_id_of(None) is None
    # 数字也要转成字符串
    assert service._chunk_id_of({'metadata': {'content_expand': 12}}) == '12'


def test_flat_document_keeps_only_projection_fields():
    from retrieval.repository.vector_write_store import flat_document

    metadata = {
        'node_id': 'ignored', 'source': 's', 'content_expand': 'ignored',
        'chunk_index': '', 'chunk_id': 3, 'type': 0,
        'extra': 'x',
    }
    doc = flat_document('n1', 'f1', 'body', metadata)
    assert doc == {
        'node_id': 'n1', 'file_id': 'f1', 'text': 'body',
        'source': 's', 'chunk_index': '', 'chunk_id': 3, 'type': 0,
    }


# ----------------------------------------------------------------------
# DataSetVO / PageDTO 的字段全集（漏字段前端会少键）
# ----------------------------------------------------------------------


def test_dataset_vo_has_all_thirteen_keys():
    vo = service._dataset_vo(1, 'kb', 'file', 'c', 's', 'src')
    assert list(vo) == ['chunkId', 'kbaseId', 'fileId', 'content', 'supplement',
                        'createdBy', 'createdDate', 'lastUpdatedBy', 'lastUpdatedDate',
                        'source', 'score', 'rankScore', 'fullScore']
    assert vo['rankScore'] is None and vo['fullScore'] is None


# ----------------------------------------------------------------------
# 错误码
# ----------------------------------------------------------------------


def test_missing_relation_is_0005_dataset_not_exist(monkeypatch):
    """``selectByIdAndKbaseIdExist`` **自己抛**「数据集不存在」（0005，不是 0001）。"""
    from shared.errors.api import KbApiError
    from knowledge_base.repository import chunk as chunk_store

    monkeypatch.setattr(chunk_store, 'select_relation_by_id', lambda *a: None)
    with pytest.raises(KbApiError) as caught:
        service._relation_or_raise(999, 'kb')
    assert caught.value.key == 'RetCode.dataSet.not.exist'
    assert caught.value.code == '0005'
    assert caught.value.render('zh') == '数据集不存在'


def test_missing_file_is_0005(monkeypatch):
    from shared.errors.api import KbApiError
    from knowledge_base.repository import directory as directory_store

    monkeypatch.setattr(directory_store, 'get_directory', lambda *a, **k: None)
    with pytest.raises(KbApiError) as caught:
        service._file_or_raise('kb', 'file')
    assert caught.value.key == 'RetCode.file.not.exist'


def test_embedding_failure_is_literal_key(monkeypatch):
    """embedding 失败把**常量当消息**。

    所以线上回的是 0005 + 字面量 ``RetCode.embedding.fail``，不是那句中文译文。
    """
    from model import gateway as model_gateway
    from shared.errors.api import KbApiError

    def boom(*_args, **_kwargs):
        raise RuntimeError('gateway down')

    monkeypatch.setattr(model_gateway, 'embed', boom)
    with pytest.raises(KbApiError) as caught:
        service._embedding('text', 'model')
    assert caught.value.code == '0005'
    assert caught.value.render('zh') == 'RetCode.embedding.fail'
    assert caught.value.render('en') == 'RetCode.embedding.fail'   # 不跟语言


# ----------------------------------------------------------------------
# psycopg2 的 ``%`` 转义：字面百分号必须写 ``%%``
#
# 病因：``cursor.execute("... ILIKE '%' || %s || '%'", ['a'])``
# 抛 ``IndexError: list index out of range`` —— psycopg2 把裸 ``%`` 也当占位符语法，
# 它数出的占位符比参数多。浏览器端表现：``/chunk/file/{id}?keyword=x`` 回 0001，
# 关键字搜索整条链挂掉（列表页搜关键词必现）。
# ----------------------------------------------------------------------


class _CapturingCursor:
    """记录 ``execute`` 的 (sql, params)，回答 count/list 两种读法。"""

    def __init__(self, row=None):
        self.calls = []
        self.description = [('id',), ('text',), ('metadata',), ('node_id',)]
        self._row = row or (0,)

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _CapturingConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _capture(monkeypatch, cursor):
    from knowledge_base.repository import chunk as chunk_store

    monkeypatch.setattr(chunk_store, 'connection', lambda: _CapturingConn(cursor))
    # 这里的用例钉的是老库 SQL 形状；_file_join 会先探 _chunk 表是否存在，
    # 不 patch 会真的去连库。
    monkeypatch.setattr(chunk_store, 'table_exists', lambda _name: False)
    return cursor


def _assert_escaped_percent(sql: str, params: list):
    """SQL 里除 ``%%``/``%s`` 外不许有裸 ``%``，且 ``%s`` 数 == 参数数。"""
    assert "'%'" not in sql, f'裸百分号未转义: {sql}'
    stripped = sql.replace('%%', '')
    assert stripped.count('%s') == len(params), \
        f'占位符 {stripped.count("%s")} 个 vs 参数 {len(params)} 个: {sql}'


def test_count_by_file_escapes_literal_percent(monkeypatch):
    from knowledge_base.repository import chunk as chunk_store

    cursor = _capture(monkeypatch, _CapturingCursor(row=(3,)))
    total = chunk_store.count_by_file({'id': 1, 'table_name': 't'}, 'f1', 'Zebra-07')

    sql, params = cursor.calls[0]
    assert total == 3
    assert params == ['f1', 'Zebra-07']
    _assert_escaped_percent(sql, params)


def test_list_by_file_escapes_literal_percent(monkeypatch):
    from knowledge_base.repository import chunk as chunk_store

    cursor = _capture(monkeypatch, _CapturingCursor())
    chunk_store.list_by_file({'id': 1, 'table_name': 't'}, 'f1', 'Zebra-07', 1, 20)

    sql, params = cursor.calls[0]
    _assert_escaped_percent(sql, params)
    assert params == ['f1', 'Zebra-07', 20, 0]


def test_list_by_file_defaults_to_desc_order(monkeypatch):
    """切片管理页的既有口径：``REL.id DESC``（后加的在前）。"""
    from knowledge_base.repository import chunk as chunk_store

    cursor = _capture(monkeypatch, _CapturingCursor())
    chunk_store.list_by_file({'id': 1, 'table_name': 't'}, 'f1', None, 1, 20)

    sql, _ = cursor.calls[0]
    assert 'ORDER BY REL.id DESC' in sql


def test_list_by_file_ascending_for_document_preview(monkeypatch):
    """文档预览按原文顺序拼正文，显式要升序。"""
    from knowledge_base.repository import chunk as chunk_store

    cursor = _capture(monkeypatch, _CapturingCursor())
    chunk_store.list_by_file({'id': 1, 'table_name': 't'}, 'f1', None, 1, 20, True)

    sql, _ = cursor.calls[0]
    assert 'ORDER BY REL.id ASC' in sql


def test_count_by_file_without_keyword_has_no_percent(monkeypatch):
    """无关键字时也不许冒出百分号（``1=1`` 分支）。"""
    from knowledge_base.repository import chunk as chunk_store

    cursor = _capture(monkeypatch, _CapturingCursor(row=(0,)))
    chunk_store.count_by_file({'id': 1, 'table_name': 't'}, None, None)

    sql, params = cursor.calls[0]
    _assert_escaped_percent(sql, params)


def test_count_all_counts_index_rows(monkeypatch):
    """详情页的切片总数与 /chunks 的 total 同口径：数向量索引行，不 join 关系表。"""
    from knowledge_base.repository import chunk as chunk_store

    cursor = _CapturingCursor(row=(42,))
    monkeypatch.setattr(chunk_store, 'connection', lambda: _CapturingConn(cursor))
    monkeypatch.setattr(chunk_store, 'table_exists', lambda _name: True)

    total = chunk_store.count_all({'id': 1, 'table_name': 'doc_t_vector'})

    sql, params = cursor.calls[0]
    assert total == 42
    assert sql.startswith('SELECT count(*) FROM kb_index.doc_t_vector AS idx')
    assert params in (None, ())


def test_count_all_missing_vector_table_is_zero(monkeypatch):
    """新建未处理的库还没有向量表：按 0 计，不是错误。"""
    from knowledge_base.repository import chunk as chunk_store

    cursor = _CapturingCursor()
    monkeypatch.setattr(chunk_store, 'connection', lambda: _CapturingConn(cursor))
    monkeypatch.setattr(chunk_store, 'table_exists', lambda _name: False)

    assert chunk_store.count_all({'id': 1, 'table_name': 'doc_t_vector'}) == 0
    assert cursor.calls == []


def test_count_by_files_groups_by_directory_id(monkeypatch):
    """整页计数用一条 GROUP BY，替代逐个文件的 chunks?size=1 探针。"""
    from knowledge_base.repository import chunk as chunk_store

    cursor = _capture(monkeypatch, _CapturingCursor())
    cursor.fetchall = lambda: [('f1', 3), ('f2', 5)]

    counts = chunk_store.count_by_files({'id': 1, 'table_name': 't'},
                                        ['f1', 'f2', 'f3'])

    sql, params = cursor.calls[0]
    assert counts == {'f1': 3, 'f2': 5}
    assert 'GROUP BY REL.directory_id' in sql
    assert params == (['f1', 'f2', 'f3'],)


def test_count_by_files_empty_skips_query(monkeypatch):
    from knowledge_base.repository import chunk as chunk_store

    cursor = _capture(monkeypatch, _CapturingCursor())

    assert chunk_store.count_by_files({'id': 1, 'table_name': 't'}, []) == {}
    assert cursor.calls == []


def test_no_bare_percent_in_any_sql_like_literal():
    """全仓扫描：``ILIKE/LIKE`` 字面量里出现裸 ``'%'`` 一律视为 bug。

    这类错误的共同症状是**静默 0001**（psycopg2 的 IndexError 被信封吞掉），
    只靠运行时用例很容易漏掉带关键字的 SQL —— 所以在这里做源级兜底。
    """
    import re

    pattern = re.compile(r"LIKE\s+'%'\s*\|\|")
    offenders = []
    for path in sorted((SRC_DIR / 'compat').rglob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if pattern.search(line) and '__pycache__' not in str(path):
                offenders.append(f'{path.relative_to(SRC_DIR)}:{number}: {line.strip()}')
    assert not offenders, '裸百分号 SQL（应为 %%）：\n' + '\n'.join(offenders)
