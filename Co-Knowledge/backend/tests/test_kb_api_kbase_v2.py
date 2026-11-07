"""``/kbase/graph`` 四个端点的测试。

不连库：只测**纯逻辑**那几块 —— 表名推导、画布库名的 token 提取、窄 VO 的字段全集、
以及 v2 与 v1 的四处实质差别。真实的建/删往返需要真库，不在单测里。

跑法::

    python -m pytest tests/test_kb_api_kbase_v2.py -q
"""


import pytest

from knowledge_base.service import kbase_v2_service as v2
from workflow.bindings import identity_token  # noqa: E402

UUID = 'a' * 32


# ----------------------------------------------------------------------
# 表名：category 决定前缀（v1 硬编码文档库，没有这个分支）
# ----------------------------------------------------------------------


def test_table_name_for_graph_category():
    assert v2._table_name(v2.CATEGORY_KNOWLEDGE_GRAPH, UUID) == f'graph_{UUID}'


def test_table_name_for_document_category():
    assert v2._table_name(v2.CATEGORY_DOCUMENT, UUID) == f'doc_{UUID}_vector'


# ----------------------------------------------------------------------
# 建库动态表：图谱库不建裸 graph_<id>
# ----------------------------------------------------------------------


def _record_create_tables(monkeypatch):
    """把三处建表动作换成记录器（``ddl`` 在函数内 import，patch 模块属性即可）。"""
    calls = []
    from infrastructure.db import ddl

    monkeypatch.setattr(ddl, 'create_vector_table',
                        lambda name, dim=None: calls.append(('vector', name, dim)))
    monkeypatch.setattr(ddl, 'create_chunk_table',
                        lambda name: calls.append(('chunk', name)))
    monkeypatch.setattr(ddl, 'create_graph_chunk_table',
                        lambda name: calls.append(('graph_chunk', name)))
    monkeypatch.setattr(v2.graph_lifecycle, 'ensure_database',
                        lambda name: calls.append(('graph_db', name)))
    return calls


def test_create_tables_for_graph_skips_legacy_bare_vector_table(monkeypatch):
    """图谱库只建 ``_chunk`` 与图库本体；裸 ``graph_<id>`` 从未被读写，不再创建。"""
    calls = _record_create_tables(monkeypatch)

    v2._create_tables(f'graph_{UUID}', 1024, category=v2.CATEGORY_KNOWLEDGE_GRAPH)

    assert ('graph_chunk', f'graph_{UUID}_chunk') in calls
    assert ('graph_db', f'graph_{UUID}') in calls
    assert [call for call in calls if call[0] == 'vector'] == []


def test_create_tables_for_document_keeps_vector_table(monkeypatch):
    calls = _record_create_tables(monkeypatch)

    v2._create_tables(f'doc_{UUID}_vector', 1024, category=v2.CATEGORY_DOCUMENT)

    assert ('vector', f'doc_{UUID}_vector', 1024) in calls
    assert ('chunk', f'doc_{UUID}_chunk') in calls


def test_v2_file_count_limit_is_shared_by_both_categories():
    """v2 的 ``fileCountLimit`` **只有 50 这一个值**（``fileLimit.graph_kbase``）。

    注解挂在单个字段上、代码里没有按 category 分流 —— 而 v1 那条路是 5000。
    别「按图谱库才 50」去实现。
    """
    assert v2.V2_FILE_COUNT_LIMIT == 50


# ----------------------------------------------------------------------
# 画布库名的 token 提取（删库前置检查用）
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw, expected', [
    (f'doc_{UUID}', UUID),
    (f'graph_{UUID}', UUID),
    (f'doc_{UUID}_vector', UUID),
    (f'doc_{UUID}|#|dev', UUID),
    (f'doc_{UUID}|#|publish', UUID),
    (f'graph_{UUID}|#|dev', UUID),
    ('123', '123'),                      # 旧形态：自增主键
    (f'  doc_{UUID}  ', UUID),  # 前后空白要 trim
])
def test_identity_token_strips_scope_and_prefixes(raw, expected):
    assert identity_token(raw) == expected


@pytest.mark.parametrize('raw', [None, '', '   ', 'doc_', 'graph_'])
def test_identity_token_returns_none_when_nothing_left(raw):
    """去掉前后缀后为空 → None（调用方据此跳过）。"""
    assert identity_token(raw) is None


# ----------------------------------------------------------------------
# 窄 VO：只有五个字段有值，但**26 个键都要在**
# ----------------------------------------------------------------------


def test_narrow_vo_has_every_field_but_only_five_set():
    vo = v2._narrow_vo(UUID, 7, 'probe', None, 'document')
    assert len(vo) == 26
    non_null = {key for key, value in vo.items() if value is not None}
    assert non_null == {'id', 'pkId', 'name', 'headIcon', 'type'} or \
        non_null == {'id', 'pkId', 'name', 'type'}   # headIcon 为 None 时不算


def test_narrow_vo_keeps_head_icon_when_given():
    vo = v2._narrow_vo(UUID, 7, 'probe', 'icon.png', 'document')
    assert vo['headIcon'] == 'icon.png'


# ----------------------------------------------------------------------
# DTO 字段表：category 是 Integer、kbaseId 是 String
# ----------------------------------------------------------------------


def test_category_coerces_numeric_string():
    """``"1"`` 能强转成 1（否则额外建库用例的行为会分叉）。"""
    from infrastructure.http import binding
    assert binding.bind({'category': '1'}, v2.KBASE_REQ_FIELDS) == {'category': 1}


def test_category_boolean_rejected():
    from infrastructure.http import binding
    with pytest.raises(ValueError):
        binding.bind({'category': True}, v2.KBASE_REQ_FIELDS)


def test_unknown_fields_dropped():
    from infrastructure.http import binding
    assert binding.bind({'nope': 1, 'name': 'x'}, v2.KBASE_REQ_FIELDS) == {'name': 'x'}


# ----------------------------------------------------------------------
# 删图谱库：顺序与失败语义
# ----------------------------------------------------------------------


def test_delete_graph_soft_deletes_last(monkeypatch):
    """清理全部完成后才软删 KB；任一步失败都保持可重试。"""
    events = []
    monkeypatch.setattr(v2, '_check_bound_by_workflow', lambda *a, **k: None)
    monkeypatch.setattr(v2, 'delete_directories_of_kbase', lambda *a, **k: None)
    monkeypatch.setattr(v2.index_service, 'delete_index', lambda _id: events.append('es'))
    monkeypatch.setattr(v2.graph_lifecycle.graph_delete_store, 'delete_import_tasks',
                        lambda _id: events.append('import_tasks'))
    monkeypatch.setattr(v2.graph_lifecycle.graph_delete_store, 'delete_extract_tasks',
                        lambda _id: events.append('extract_tasks'))
    monkeypatch.setattr(v2.graph_lifecycle, 'delete_graph_database', lambda _id: events.append('graph'))
    monkeypatch.setattr(v2.graph_lifecycle.graph_delete_store, 'drop_table_if_exists',
                        lambda name: events.append('drop:' + name.split('.')[-1][-7:]))
    monkeypatch.setattr(v2.kbase_store, 'delete_kbase_row',
                        lambda _id: events.append('soft_delete'))

    v2._delete_graph({'kbase_id': UUID}, 7, 'user-1')

    assert events[-1] == 'soft_delete'
    assert events.index('es') < events.index('graph') < events.index('soft_delete')


def test_delete_graph_db_drops_graph_before_registry(monkeypatch):
    events = []
    monkeypatch.setattr(v2.graph_lifecycle.graph_pg, 'new_client', lambda _name: object())
    monkeypatch.setattr(v2.graph_lifecycle.graph_pg, 'drop_database',
                        lambda client, name, **kw: events.append('drop'))
    monkeypatch.setattr(v2.graph_lifecycle.graph_delete_store, 'delete_knowledge_graph_info',
                        lambda name: events.append('registry'))

    v2.graph_lifecycle.delete_graph_database(UUID)

    assert events == ['drop', 'registry']


def test_delete_graph_db_failure_keeps_registry_and_raises(monkeypatch):
    events = []
    monkeypatch.setattr(v2.graph_lifecycle.graph_pg, 'new_client', lambda _name: object())

    def _drop(client, name, **kw):
        raise RuntimeError('graph down')

    monkeypatch.setattr(v2.graph_lifecycle.graph_pg, 'drop_database', _drop)
    monkeypatch.setattr(v2.graph_lifecycle.graph_delete_store, 'delete_knowledge_graph_info',
                        lambda name: events.append('registry'))

    with pytest.raises(RuntimeError, match='graph down'):
        v2.graph_lifecycle.delete_graph_database(UUID)

    assert events == []


def test_reuse_rejects_cross_category(monkeypatch):
    """文档库不能复用到图谱库。"""
    from shared.errors.api import KbApiError

    monkeypatch.setattr(v2.kbase_store, 'count_files', lambda _id: 0)
    with pytest.raises(KbApiError):
        v2._reuse_or_raise(
            {'kbase_id': 'a' * 32, 'category': 10, 'table_name': 'graph_' + 'a' * 32},
            'same-name', 1)


def test_reuse_rejects_mismatched_table_prefix(monkeypatch):
    from shared.errors.api import KbApiError

    monkeypatch.setattr(v2.kbase_store, 'count_files', lambda _id: 0)
    with pytest.raises(KbApiError):
        v2._reuse_or_raise(
            {'kbase_id': 'a' * 32, 'category': 1,
             'table_name': 'graph_' + 'a' * 32},
            'same-name', 1)
