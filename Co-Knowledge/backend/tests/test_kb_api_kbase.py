"""kb_api 知识库只读端点的测试。

不连库：``kbase_store`` 的查询函数用假的替换掉，这一层要验的是**VO 组装与契约保真**
（字段全集、null 与空串的区别、哪些字段该是 null），以及路由顺序。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_kbase.py -q
"""

from datetime import datetime

import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import http_api as kb_router  # noqa: E402
from shared.errors.api import KbValidationError  # noqa: E402
from knowledge_base.service import kbase_service  # noqa: E402
from knowledge_base.repository import kbase as kbase_store  # noqa: E402
from model import resolver as model_resolver  # noqa: E402

# KbaseVO 的字段全集。
# 响应包含所有字段（null 不省略），
# 前端与编排层都按「字段存在」解析。
KBASE_VO_FIELDS = [
    'id', 'pkId', 'name', 'headIcon', 'type', 'description', 'props', 'esIndexName',
    'embeddingModel', 'currentFileCount', 'fileCountLimit', 'createdBy', 'createdDate',
    'lastUpdatedBy', 'lastUpdatedDate', 'fullName', 'fullNameEn', 'tableName', 'action',
    'operatorId', 'failReason', 'status', 'schemaName', 'schemaObj', 'process',
    'processDetailInfo',
    # Knowledge Studio 领域扩展（不属于上面的字段集）：详情页的「N 个切片」直接用这个值，
    # 不再单独发 chunks?size=1 去拿分页信封的 total。图谱库不带该字段。
    'chunkCount',
]

ROW = {
    'id': 1,
    'kbase_id': '447a9eb509e44d399790dbfd97f25360',
    'type': 'document',
    'name': 'demo-kb',
    'description': 'first slice',
    'head_icon': None,
    'es_index_name': 'doc_447a9eb509e44d399790dbfd97f25360',
    'file_count_limit': 5000,
    'org_id': None,
    'embedding_model': 'bge-base-zh-v1.5',
    'table_name': 'doc_447a9eb509e44d399790dbfd97f25360_vector',
    'category': 1,
    'operator_id': None,
    'schema_id': None,
    'schema_obj': None,
    'fail_reason_obj': None,
    'process_obj': None,
    'status': '0',
    'process': None,
    'created_by': 'admin',
    'created_at': datetime(2026, 10, 5, 4, 49, 42),
    'updated_by': 'admin',
    'updated_at': datetime(2026, 10, 5, 4, 49, 42),
    'tenant_id': None,
}


@pytest.fixture()
def fake_store(monkeypatch):
    """把 store 换成内存假实现。"""
    state = {'rows': [dict(ROW)], 'file_count': 1}

    monkeypatch.setattr(kbase_store, 'select_all_kbases', lambda org_id=None: [dict(r) for r in state['rows']])
    monkeypatch.setattr(kbase_store, 'select_kbase_by_id', lambda kb_id: next(
        (dict(r) for r in state['rows'] if r['kbase_id'] == kb_id), None))
    monkeypatch.setattr(kbase_store, 'count_files', lambda kb_id: state['file_count'])
    # 详情里的 chunkCount 走 repository.chunk.count_all：单测里别真连库。
    monkeypatch.setattr(kbase_service.chunk_store, 'count_all', lambda row: 42)
    return state


@pytest.fixture()
def client():
    app = FastAPI()
    kb_router.register_rkb_api(app)
    return TestClient(app)


# ----------------------------------------------------------------------
# 字段全集与各字段取值
# ----------------------------------------------------------------------


def test_vo_has_every_field_in_java_declaration_order(fake_store):
    vo = kbase_service.get_kbase_detail(ROW['kbase_id'])

    assert list(vo.keys()) == KBASE_VO_FIELDS


def test_list_authority_kbases_deliberately_omits_table_name(fake_store):
    """``GET /kbase`` **不设** ``tableName``。

    这条看着像 bug，其实是必须保留的行为：编排层的
    ``invoke_list_vector_knowledge_bases()`` 读 ``tableName`` 来当 base 用，拿不到就抛
    ``knowledgebase-not-imported``。填上真实表名 ``data_doc_<id>`` 并不能修好它
    —— 检索端还会再拼一次 ``data_`` 前缀，变成 ``data_data_...`` 查不到表
    （历史遗留的坑）。所以这里保持 null，并在此锁住。
    """
    vo = kbase_service.list_authority_kbases()[0]

    assert vo['tableName'] is None
    assert vo['embeddingModel'] is None       # builder 也没设
    assert vo['currentFileCount'] is None
    assert vo['description'] is None
    assert vo['action'] == 'm'                # 本部署走「有管理权限」分支（实测）
    assert vo['name'] == 'demo-kb'            # 六个被显式设置的字段之一


def test_detail_sets_table_name_and_props(fake_store):
    vo = kbase_service.get_kbase_detail(ROW['kbase_id'])

    assert vo['tableName'] == 'doc_447a9eb509e44d399790dbfd97f25360_vector'
    assert vo['currentFileCount'] == 1
    assert vo['chunkCount'] == 42
    # PropsDTO 的字段初始值，不是从库里读的
    assert vo['props'] == {
        'embeddingModel': 'bge-base-zh-v1.5',
        'splitMethod': 'comprehensiveSplitter',
        'regex': '\\n\\n',
    }


def test_detail_omits_chunk_count_for_graph_kbase(fake_store):
    """图谱库没有「切片」概念：不返回 chunkCount（避免把实体数误当切片数）。"""
    fake_store['rows'][0]['category'] = 10

    vo = kbase_service.get_kbase_detail(ROW['kbase_id'])

    assert 'chunkCount' not in vo


def test_detail_schema_name_stays_null_but_search_sets_empty_string(fake_store):
    """同一个 VO 字段在两条装配路径上取值不同 —— 这是真实行为，别统一。

    ``GET /kbase/{id}`` 走 ``KbaseVO.from()``，不碰 ``schemaName`` ⇒ null；
    ``/kbase/search`` 走 ``KbaseServiceV2``，把它显式设成 ``""``。
    """
    detail = kbase_service.get_kbase_detail(ROW['kbase_id'])
    assert detail['schemaName'] is None
    assert detail['failReason'] == ''          # from() 会格式化，null map → ""


def test_dates_use_jackson_default_format(fake_store):
    vo = kbase_service.get_kbase_detail(ROW['kbase_id'])

    assert vo['createdDate'] == '2026-10-05 04:49:42'


def test_list_is_sorted_case_insensitively_like_java_collator(monkeypatch):
    """``GET /kbase`` 的顺序必须与 ``Collator`` 主强度一致（忽略大小写）。

    期望顺序是 ``demo-kb, graph-e2e-kb, KB_20261011_143412, manual-test-kb``
    —— 用码位序排会得到 ``KB_...`` 在最前（``'K'``(75) < ``'d'``(100)）。
    """
    names = ['KB_20261011_143412', 'manual-test-kb', 'demo-kb', 'graph-e2e-kb']
    rows = []
    for i, name in enumerate(names):
        row = dict(ROW, name=name, kbase_id=f'id-{i}')
        rows.append(row)
    monkeypatch.setattr(kbase_store, 'select_all_kbases', lambda org_id=None: rows)

    assert [vo['name'] for vo in kbase_service.list_authority_kbases()] == [
        'demo-kb', 'graph-e2e-kb', 'KB_20261011_143412', 'manual-test-kb',
    ]


# ----------------------------------------------------------------------
# 两套「取本地化文案」必须保持差异
# ----------------------------------------------------------------------


def test_localized_text_returns_empty_string_for_missing_key():
    """``KbaseVO.formatLocalizedMessage``：键缺失 → 空串。"""
    assert kbase_service._localized_text({'en_US': 'x'}) == ''


def test_localized_string_value_reproduces_java_null_string():
    """``KbaseServiceV2.formatFailReason`` 用 ``String.valueOf`` ⇒ 键缺失产出 ``"null"``。

    这是有意保持的行为（看着像 bug），分页列表里会原样出现。
    别「修」成空串 —— 它会改变对外响应。
    """
    assert kbase_service._localized_string_value({'en_US': 'x'}) == 'null'
    assert kbase_service._localized_string_value(None) == ''


# ----------------------------------------------------------------------
# 其它只读端点
# ----------------------------------------------------------------------


@pytest.mark.parametrize('value, expected', [
    ('AIS', True), ('ais', True), ('V7', True), ('v7', True),
    ('', False), (None, False), ('OTHER', False),
])
def test_is_ais_environment(value, expected):
    assert kbase_service.is_ais_environment(value) is expected


def test_embedding_models_preserve_registry_order(fake_store, monkeypatch):
    monkeypatch.setattr(model_resolver, 'embedding_models',
                        lambda: ['bge-large-zh-v1.5', 'bge-base-zh-v1.5'])

    assert kbase_service.list_embedding_models() == ['bge-large-zh-v1.5', 'bge-base-zh-v1.5']


def test_missing_kbase_non_numeric_raises_not_exist(fake_store):
    """库不存在 + id **不是纯数字** → ``kbase.not.exist``。"""
    from shared.errors.api import KbApiError

    with pytest.raises(KbApiError) as excinfo:
        kbase_service.get_kbase_detail('no-such-id')

    assert excinfo.value.key == 'kbase.not.exist'
    assert excinfo.value.code == '0005'


@pytest.mark.parametrize('kbase_id', ['0' * 32, '123', '-7'])
def test_missing_kbase_numeric_raises_permission_denied(fake_store, kbase_id):
    """库不存在 + id **是纯数字** → ``PermissionDenied``。

    权限切面在库查不到后会拿 id 当**算子** id 再查一次（``checkUserPermission``），
    只有 id 形如 ``-?\\d+`` 才走那条分支；走不通最后抛的就是这句。
    实测 32 个 0 踩的正是这条。
    """
    from shared.errors.api import KbApiError

    with pytest.raises(KbApiError) as excinfo:
        kbase_service.get_kbase_detail(kbase_id)

    assert excinfo.value.key == 'permission.denied'
    assert excinfo.value.code == '0005'


def test_judge_empty_rejects_kbase_with_files(fake_store):
    from shared.errors.api import KbApiError

    with pytest.raises(KbApiError) as excinfo:
        kbase_service.is_kbase_empty(ROW['kbase_id'])

    assert excinfo.value.render('en') == (
        'Cannot delete knowledge base: knowledge base includes other knowledge.')


# ----------------------------------------------------------------------
# HTTP 层
# ----------------------------------------------------------------------


def test_kbase_ais_is_not_swallowed_by_the_detail_route(fake_store):
    """``/system/info`` 必须命中系统域，而不是被知识库详情路由吃掉。

    FastAPI 按注册顺序匹配，所以系统域端点必须在动态路由之前注册 —— 一旦有人调整
    顺序，前端读到的 ``{ais: ...}`` 会变成「知识库不存在」的业务错误。
    """
    app = FastAPI()
    kb_router.register_rkb_api(app)
    client = TestClient(app)

    response = client.get(f'{kb_router.KBASE_PREFIX}/system/info')
    body = response.json()

    assert response.status_code == 200
    assert 'ais' in body


def test_embedding_all_is_wrapped_in_envelope(fake_store, monkeypatch, client):
    monkeypatch.setattr(model_resolver, 'embedding_models', lambda: ['m1'])

    response = client.get(f'{kb_router.KBASE_PREFIX}/system/embedding-models')

    assert response.status_code == 200
    assert response.json() == ['m1']


def test_environment_returns_deployed_by_key(fake_store, client):
    response = client.get(f'{kb_router.KBASE_PREFIX}/system/info')
    body = response.json()

    assert response.status_code == 200
    assert 'deployedBy' in body


def test_missing_kbase_over_http_is_business_error_not_500(fake_store, client):
    response = client.get(f'{kb_router.KBASE_PREFIX}/knowledge-bases/no-such-id')

    assert response.status_code == 404
    body = response.json()
    assert body['code'] == 'knowledge_base_not_found'
    # id 不是纯数字 → 走「直接报不存在」那条；纯数字才走 PermissionDenied（见上一个用例）。
    assert body['detail'] == 'Knowledge base not exist'


# ----------------------------------------------------------------------
# 画布「知识库下拉」（原生实现，直接读库）
# ----------------------------------------------------------------------


def _option_rows(**overrides):
    base = dict(ROW, status='0', category=1,
                table_name='doc_447a9eb509e44d399790dbfd97f25360_vector')
    base.update(overrides)
    return [base]


def test_canvas_options_table_name_is_the_retrieval_base_name(monkeypatch):
    """文档库的 ``tableName`` 必须是 ``doc_<uuid>``，**不是** ``kb_kbase.table_name``。

    前端把它存进算子的 ``knowledge_info_list[].knowledge_base_name``，运行时按
    ``kb_kbase.table_name`` 解析物理表。``dbTableName`` 才是物理表名
    （文档库为 ``doc_<uuid>_vector``），两种名字不能混用。
    """
    from knowledge_base import kbase_options

    monkeypatch.setattr(kbase_store, 'select_all_kbases', lambda org_id=None: _option_rows())
    option = kbase_options.KbaseTableOptionProvider().list_options()['dev'][0]

    assert option['tableName'] == 'doc_' + ROW['kbase_id']
    assert option['dbTableName'] == 'doc_' + ROW['kbase_id'] + '_vector'


def test_graph_kbase_option_uses_the_materialized_table_name(monkeypatch):
    """图谱库（``category=10``）直接给物化表名 ``graph_<uuid>`` —— 它走另一条检索路。"""
    from knowledge_base import kbase_options

    monkeypatch.setattr(kbase_store, 'select_all_kbases',
                        lambda org_id=None: _option_rows(category=10, table_name='graph_0f28f086'))
    option = kbase_options.KbaseTableOptionProvider().list_options()['dev'][0]

    assert option['tableName'] == 'graph_0f28f086'


@pytest.mark.parametrize('status, expected_group', [
    ('7', 'running'), ('8', 'running'),
    ('0', 'dev'), ('5', 'dev'), ('6', 'dev'), (None, 'dev'),
])
def test_canvas_options_grouping(status, expected_group, monkeypatch):
    """``running`` = 已发布 7 / 发布后又改 8，其余（含发布中 6）一律 ``dev``。"""
    from knowledge_base import kbase_options

    monkeypatch.setattr(kbase_store, 'select_all_kbases',
                        lambda org_id=None: _option_rows(status=status))
    grouped = kbase_options.KbaseTableOptionProvider().list_options()

    assert len(grouped[expected_group]) == 1
    assert set(grouped) == {'running', 'dev'}      # 两个键恒在


def test_canvas_options_skip_kbase_without_table_name(monkeypatch):
    """没有 ``tableName`` 的库不返回 —— 宁可少一项，也不给一个「选了检索不到」的选项。"""
    from knowledge_base import kbase_options

    monkeypatch.setattr(kbase_store, 'select_all_kbases',
                        lambda org_id=None: _option_rows(table_name=None))
    grouped = kbase_options.KbaseTableOptionProvider().list_options()

    assert grouped == {'running': [], 'dev': []}


def test_canvas_options_embedding_filter(monkeypatch):
    """前端「按向量模型分组」的抽屉会带 embedding 参数来取库。"""
    from knowledge_base import kbase_options

    monkeypatch.setattr(kbase_store, 'select_all_kbases', lambda org_id=None: _option_rows())
    provider = kbase_options.KbaseTableOptionProvider()

    assert len(provider.list_options('bge-base-zh-v1.5')['dev']) == 1
    assert provider.list_options('other-model')['dev'] == []
    assert len(provider.list_options('')['dev']) == 1        # 空串 = 不过滤


def test_canvas_options_expose_all_eight_fields(monkeypatch):
    from knowledge_base import kbase_options

    monkeypatch.setattr(kbase_store, 'select_all_kbases', lambda org_id=None: _option_rows())
    option = kbase_options.KbaseTableOptionProvider().list_options()['dev'][0]

    assert set(option) == {'kbasePkId', 'name', 'tableName', 'dbTableName',
                           'type', 'assetId', 'status', 'embeddingModel'}
    assert option['assetId'] == ROW['kbase_id']    # 无资产中心，用自身 uuid 顶替
    assert option['kbasePkId'] == ROW['id']


def test_flow_api_defaults_to_the_native_provider():
    """编排层装配**原生** provider（直接读 kb_kbase）。"""
    from workflow import service as flow_service

    assert type(flow_service._default_kbase_provider()).__name__ == 'KbaseTableOptionProvider'


def test_search_kbases_uses_created_at_desc_by_default(fake_store, monkeypatch, client):
    """``GET /knowledge-bases`` 默认排序是 created_at DESC。"""
    captured = {}

    def fake_search(keyword, categories, embedding_model, org_id, limit, offset,
                    order_list=None):
        captured.update(keyword=keyword, categories=categories, limit=limit, offset=offset,
                        order_list=order_list)
        return [dict(ROW)]

    monkeypatch.setattr(kbase_store, 'count_search_kbases', lambda *a: 1)
    monkeypatch.setattr(kbase_store, 'search_kbases', fake_search)
    monkeypatch.setattr(kbase_store, 'count_files_by_kbase_ids', lambda ids: {ROW['kbase_id']: 1})

    body = client.get(f'{kb_router.KBASE_PREFIX}/knowledge-bases',
                      params={'page': 3, 'size': 5}).json()

    assert body['total'] == 1
    assert body['page'] == 3
    assert body['items'][0]['schemaName'] == ''
    assert captured['limit'] == 5
    assert captured['offset'] == 10          # (currentPage - 1) * pageSize
    assert captured['order_list'] == []      # 没传 orderList → 空清单 → 走默认排序


# ----------------------------------------------------------------------
# 建库 DTO 的两条 @Size 与 props 的 NPE
#
# 1001 字的描述必须回 0004，不能直接建库成功 —— 否则会多建一个本不该存在的库。
# ----------------------------------------------------------------------


def test_create_rejects_over_long_description():
    """``@Size(max=1000)`` 是闭区间：1000 合法、1001 → 0004。"""
    from knowledge_base.service import kbase_write_service as write
    write._validate_sizes('x' * 1000, None)
    with pytest.raises(KbValidationError):
        write._validate_sizes('x' * 1001, None)


def test_create_rejects_over_long_head_icon():
    from knowledge_base.service import kbase_write_service as write
    write._validate_sizes(None, 'h' * 255)
    with pytest.raises(KbValidationError):
        write._validate_sizes(None, 'h' * 256)


def test_size_checks_pass_on_none():
    """``@Size`` 对 null 不校验。"""
    from knowledge_base.service import kbase_write_service as write
    write._validate_sizes(None, None)


def test_create_without_props_raises_npe(monkeypatch):
    """``props`` 缺席是 **NPE → 0001**，不是「回落到空 props」。

    缺席时直接取 ``props.embeddingModel`` 会 NPE（V2 建库链同样）；
    写成 ``or {}`` 会静默建库成功。
    """
    from knowledge_base.service import kbase_write_service as write

    with pytest.raises(write._NullPropsNpe):
        write.create_kbase({'name': 'probe_ok_name'}, 'admin', None, '')


def test_npe_precedes_name_lock(monkeypatch):
    """NPE 在取锁之前 —— 别把绑定检查挪到锁后面。"""
    from knowledge_base.service import kbase_write_service as write

    touched = []

    def fake_acquire(org_id, name):
        touched.append(name)
        raise AssertionError('name lock must not be reached')

    monkeypatch.setattr(write.name_lock, 'acquire', fake_acquire)
    with pytest.raises(write._NullPropsNpe):
        write.create_kbase({'name': 'probe_ok_name'}, 'admin', None, '')
    assert touched == []


# ----------------------------------------------------------------------
# 列表排序（orderList）：web 点表头**会**传，早先被写死 created_at DESC 吞掉
#
# 这一条是浏览器 E2E 抓出来的：aria-sort 指示器切换、行顺序纹丝不动。
# 抓包证明前端一直在发 orderList；后端没实现 → 静默忽略（HTTP 200 + 0000）。
# ----------------------------------------------------------------------


def test_build_order_by_defaults_to_created_at_desc():
    from knowledge_base.repository import kbase as kbase_store

    assert kbase_store.build_order_by(None) == 'created_at DESC'
    assert kbase_store.build_order_by([]) == 'created_at DESC'


def test_build_order_by_renders_both_directions():
    from knowledge_base.repository import kbase as kbase_store

    assert kbase_store.build_order_by([{'key': 'createdDate', 'ascending': False}]) \
        == 'created_at DESC'
    assert kbase_store.build_order_by([{'key': 'createdDate', 'ascending': True}]) \
        == 'created_at'


def test_build_order_by_name_uses_gb18030_conversion():
    """name 排序走 ``convert_to(name,'GB18030')``（中文按 GB18030 排）。"""
    from knowledge_base.repository import kbase as kbase_store

    assert kbase_store.build_order_by([{'key': 'name', 'ascending': True}]) \
        == "convert_to(name,'GB18030')"
    assert kbase_store.build_order_by([{'key': 'name', 'ascending': False}]) \
        == "convert_to(name,'GB18030') DESC"


def test_build_order_by_joins_multiple_keys_in_order():
    from knowledge_base.repository import kbase as kbase_store

    assert kbase_store.build_order_by([
        {'key': 'embeddingModel', 'ascending': True},
        {'key': 'createdDate', 'ascending': False},
    ]) == 'embedding_model, created_at DESC'


def test_build_order_by_drops_keys_without_column_mapping():
    """``description`` / ``currentFileCount`` 是合法 key 但没有列映射（源码里被注释掉）
    → 丢弃；一个都不剩才回落默认。"""
    from knowledge_base.repository import kbase as kbase_store

    assert kbase_store.build_order_by([{'key': 'description', 'ascending': True}]) \
        == 'created_at DESC'
    assert kbase_store.build_order_by([{'key': 'currentFileCount', 'ascending': False},
                                       {'key': 'createdBy', 'ascending': True}]) \
        == 'created_by'


def test_build_order_by_drops_missing_ascending():
    """``ascending`` 缺/为 null 时 ``getEnumOfKbaseProp`` 匹配不到 → 该项丢弃。"""
    from knowledge_base.repository import kbase as kbase_store

    assert kbase_store.build_order_by([{'key': 'name'}]) == 'created_at DESC'
    assert kbase_store.build_order_by([{'key': 'name', 'ascending': None}]) \
        == 'created_at DESC'


def test_unknown_order_key_is_rejected_as_0004(client):
    """``key`` 在绑定阶段就要对上允许值 ——
    未知值 → 绑定失败 → 0004，不是「忽略这一项」。"""
    response = client.get(f'{kb_router.KBASE_PREFIX}/knowledge-bases',
                          params={'page': 1, 'size': 5, 'sort': 'bogus:asc'})
    assert response.status_code == 400
    assert response.json()['code'] == 'malformed_request'


def test_null_order_key_is_ignored_not_rejected(client, monkeypatch):
    """``key`` 为 null 合法（绑成 null，后续匹配不到 → 丢弃）。"""
    monkeypatch.setattr(kbase_store, 'count_search_kbases', lambda *a: 0)
    response = client.get(f'{kb_router.KBASE_PREFIX}/knowledge-bases',
                          params={'page': 1, 'size': 5, 'sort': ':asc'})
    assert response.status_code == 200


def test_order_list_reaches_the_store(client, monkeypatch):
    """整链透传：查询参数里的 sort 原样到 store（由 build_order_by 渲染）。"""
    captured = {}

    def fake_search(keyword, categories, embedding_model, org_id, limit, offset,
                    order_list=None):
        captured['order_list'] = order_list
        return [dict(ROW)]

    monkeypatch.setattr(kbase_store, 'count_search_kbases', lambda *a: 1)
    monkeypatch.setattr(kbase_store, 'search_kbases', fake_search)
    monkeypatch.setattr(kbase_store, 'count_files_by_kbase_ids',
                        lambda ids: {ROW['kbase_id']: 1})

    response = client.get(f'{kb_router.KBASE_PREFIX}/knowledge-bases',
                          params={'page': 1, 'size': 5, 'sort': 'name:asc'})

    assert response.status_code == 200
    assert captured['order_list'] == [{'key': 'name', 'ascending': True}]


def test_v1_delete_graph_delegates_to_v2(monkeypatch):
    """v1 路由删图谱库必须走 v2 的完整清理链。"""
    from knowledge_base.service import kbase_write_service as write
    from knowledge_base.service import kbase_v2_service as v2

    monkeypatch.setattr(write.kbase_store, 'select_kbase_by_id',
                        lambda _id: {'kbase_id': 'a' * 32, 'category': 10})
    calls = []
    monkeypatch.setattr(v2, 'delete_kbase',
                        lambda kbase_id, emp_no='': calls.append((kbase_id, emp_no)))

    write.delete_kbase('graph-kb', 'user-1')

    assert calls == [('graph-kb', 'user-1')]


def test_v1_delete_document_keeps_legacy_path(monkeypatch):
    """文档库仍走 v1 的「有文件不许删」，不能被误委托给 v2。"""
    from knowledge_base.service import kbase_write_service as write
    from knowledge_base.service import kbase_v2_service as v2

    monkeypatch.setattr(write.kbase_store, 'select_kbase_by_id',
                        lambda _id: {'kbase_id': 'a' * 32, 'category': 1})
    monkeypatch.setattr(write.kbase_store, 'count_files', lambda _id: 1)
    monkeypatch.setattr(v2, 'delete_kbase',
                        lambda *a, **k: pytest.fail('document must not delegate to v2'))

    with pytest.raises(Exception) as caught:
        write.delete_kbase('doc-kb', 'user-1')

    assert 'can.not.delete' in str(getattr(caught.value, 'key', caught.value))
