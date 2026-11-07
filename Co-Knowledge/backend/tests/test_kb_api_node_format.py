"""``node_format`` / ``node_columns``：切片元数据的**存储形态**与对外响应。

## 这个文件存在的原因

切片元数据经历过两次存储形态调整（去掉 JSON 内的嵌套副本、把 JSON 列展开成
5 个物理列），所以这里就地重建保障：**拿一条真实的存量行**（下面 ``_row()`` 的值来自
``kb_index`` schema 的 dump，只把正文截短），断言它走到
``process_vector_record`` + ``to_search_doc`` 之后**逐键符合对外响应契约**。

跑法::

    python -m pytest tests/test_kb_api_node_format.py -q
"""

from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = SERVICE_ROOT / 'src'

from retrieval.service import node_mapper as node_mapper  # noqa: E402
from shared.chunk_schema import node_columns  # noqa: E402
from shared.chunk_schema import node_format  # noqa: E402

TEXT = '这是一段用于验证任务队列的正文。'
CONTENT_EXPAND = '6e1f361a-fb18-4175-a9f2-cf3b66a9180f'
NODE_ID = 'cbc6b12d-d657-4066-a6d0-0e41ccf44eea'


def _row(**overrides) -> dict:
    """一条真实的存量行（``kb_index.data_kb_index_7ad5f3c5…`` dump）。

    ``metadata_`` 已展开成 5 个物理列，所以这里直接是列。
    """
    row = {
        'id': 1,
        'text': TEXT,
        'node_id': NODE_ID,
        'embedding': None,
        'cosine_similarity': 0.87,
        # ↓ 展开后的 4 列（值取自真实行；chunk_index 已移除）
        'source': 'ft-e2e-1791894012.md',
        'content_expand': CONTENT_EXPAND,
        'chunk_id': 1,
        'type': 0,
    }
    row.update(overrides)
    return row


# ----------------------------------------------------------------------
# node_columns：列 ↔ dict
# ----------------------------------------------------------------------


def test_metadata_from_row_keeps_only_non_null_columns():
    """只收**非 NULL** 的列 —— 与 JSON 时代"键不存在就不出现"对齐。"""
    row = _row()
    row['chunk_index'] = None
    row['type'] = None
    assert node_columns.metadata_from_row(row) == {
        'source': 'ft-e2e-1791894012.md', 'content_expand': CONTENT_EXPAND,
        'chunk_id': 1,
    }


def test_metadata_from_row_key_order_matches_the_old_json():
    """**键序必须与旧 JSON 一致** —— ``to_search_doc`` 把 dict 原样透给前端。"""
    assert list(node_columns.metadata_from_row(_row())) == [
        'source', 'content_expand', 'chunk_id', 'type']


def test_columns_round_trip():
    metadata = node_columns.metadata_from_row(_row())
    cols = node_columns.columns_from_metadata(metadata)
    assert cols == {name: metadata[name] for name in node_columns.EXPANDED_FIELDS}
    assert node_columns.metadata_from_row(cols) == metadata


def test_columns_from_missing_keys_are_none():
    assert node_columns.columns_from_metadata({}) == {
        name: None for name in node_columns.EXPANDED_FIELDS}
    assert node_columns.columns_from_metadata(None) == {
        name: None for name in node_columns.EXPANDED_FIELDS}


def test_metadata_from_row_prefix():
    """联表查询里展开列会撞名（``REL.id AS chunk_id``），SQL 侧加前缀别名。"""
    row = {'meta_source': 'a.md', 'meta_content_expand': 'c', 'chunk_id': 'rel-id'}
    assert node_columns.metadata_from_row(row, prefix='meta_') == {
        'source': 'a.md', 'content_expand': 'c'}


# ----------------------------------------------------------------------
# 对外响应：键集与键序固定
# ----------------------------------------------------------------------


def test_to_search_doc_matches_the_pre_change_response():
    """端到端：``process_vector_record`` + ``to_search_doc`` 的产出**逐键**符合对外响应契约。

    这是对外响应那一层 —— 前端与编排按它解析，所以这一条才是真正要保的。
    期望值来自同一条真实行的样本（见本文件头部说明）。
    """
    doc = node_mapper.to_search_doc(node_mapper.process_vector_record(_row()))

    assert doc == {
        'chunkId': '1',
        'content': TEXT,
        'score': 0.87,
        'sourceDocId': None,          # 新库分支恒为 null（老行为）
        'metadata': {
            'source': 'ft-e2e-1791894012.md',
            'chunk_id': 1, 'type': 0,
        },
    }
    # 内部键必须被剔除
    assert 'content_expand' not in doc['metadata']


def test_row_without_metadata_degrades_to_empty_doc():
    """没有元数据的行 → 空 map（字段全是 null）。"""
    row = _row(**{name: None for name in node_columns.EXPANDED_FIELDS})
    assert node_mapper.process_vector_record(row) == {}


def test_null_metadata_record_degrades_to_empty_doc():
    assert node_mapper.process_vector_record({'metadata_': None, 'text': 'x'}) == {}


def test_node_envelope_keys_and_order():
    """node 信封的键集与键序固定：``text`` 原位、``id`` 追加在末尾。"""
    row = _row()
    node = node_format.node_envelope(node_columns.metadata_from_row(row), row['text'],
                                     row_id=row['id'], node_id=row['node_id'])
    assert list(node) == ['id_', 'embedding', 'metadata', 'excluded_embed_metadata_keys',
                          'excluded_llm_metadata_keys', 'relationships', 'text',
                          'start_char_idx', 'end_char_idx', 'text_template',
                          'metadata_template', 'metadata_seperator', 'class_name', 'id']
    assert node['id_'] == row['node_id']
    assert node['id'] == row['id']
    assert node['end_char_idx'] == len(TEXT)


# ----------------------------------------------------------------------
# 写侧：展开列 + 老键兜底
# ----------------------------------------------------------------------


def test_vector_table_write_uses_expanded_columns():
    """向量表的写侧同样只落展开列。

    ``_vector_params`` 若用了 ``node_columns`` 却没导入，单测可能全绿、
    真上传一次就 ``NameError``；``_chunk_params`` 的用例覆盖不到这里的列序。
    """
    from retrieval.repository import vector_write_store as vector_write_store

    params = vector_write_store._vector_params({
        'node_id': 'n1',
        'text': '正文',
        'embedding': [1.0, 0.5],
        'metadata': {'chunk_index': '', 'source': 'a.md', 'content_expand': 'c',
                     'chunk_id': 1, 'type': 0,
                     '_node_content': '{"x":1}'},
    })
    # 列序：text, node_id, embedding, source, content_expand, chunk_id, type
    # 正文只留 chunk.text，vector.text 普通行为 NULL。
    assert params == (None, 'n1', '[1.0,0.5]', 'a.md', 'c', 1, 0)


def test_vector_write_nulls_missing_metadata():
    from retrieval.repository import vector_write_store as vector_write_store

    params = vector_write_store._vector_params(
        {'node_id': 'n1', 'text': 't', 'embedding': [], 'metadata': None})

    assert params == (None, 'n1', '[]', None, None, None, None)


def test_chunk_table_write_is_flat():
    """chunk 表的写侧同样只落展开列（不写 JSON、不写老键）。"""
    from retrieval.repository import vector_write_store as vector_write_store

    nested = {
        'source': 'a.md', 'content_expand': 'c', 'chunk_index': '', 'chunk_id': 1,
        'type': 0,
        '_node_content': '{"x":1}', '_node_type': 'TextNode',
        'document_id': 'd', 'doc_id': 'd', 'ref_doc_id': 'd',
    }
    params = vector_write_store._chunk_params({'id': 'k1', 'metadata': nested})
    # 文档库列序：id, kbId, source, text, chunk_id, type（图谱契约字段不再落库）
    assert params == ('k1', None, None, None, 1, 0)


def test_vector_table_write_keeps_text_column_null():
    """正文只留 chunk.text：``vector.text`` 普通行必须为 NULL。"""
    from retrieval.repository import vector_write_store as vector_write_store

    row = {'node_id': 'n1', 'text': '正文', 'embedding': [0.1, 0.2],
           'metadata': {'source': 'a.md', 'content_expand': 'chunk-1'}}
    assert vector_write_store._vector_params(row)[0] is None


def test_written_metadata_has_no_legacy_keys():
    """源级兜底：谁再往 metadata 里写 ``_node_content``，这条就红。"""
    import re

    pattern = re.compile(r"metadata\[['\"]_node_content['\"]\]\s*=")
    offenders = []
    for path in sorted((SRC_DIR / 'compat').rglob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if pattern.search(line) and '__pycache__' not in str(path):
                offenders.append(f'{path.relative_to(SRC_DIR)}:{number}: {line.strip()}')
    assert not offenders, '又在往 metadata 里写 _node_content：\n' + '\n'.join(offenders)
