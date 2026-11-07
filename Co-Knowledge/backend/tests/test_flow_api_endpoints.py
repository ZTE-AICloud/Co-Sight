"""端点级测试（FastAPI TestClient + InMemoryFlowStore，不碰 DB/网络）。

覆盖验收关心的四件事：空画布、保存/读取往返、preCheck 拒绝结构错误、
发布快照不可变；另附双前缀信封、分页、导出等契约点。
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow import register_flow_api
from workflow.errors import FlowStoreError
from workflow.models import WorkflowRecord
from workflow.repository import InMemoryFlowStore

from conftest import (
    DEFAULT_BOUND_INFO,
    KB_SERVICE_PREFIX,
    create_workflow,
    make_canvas,
)

ADMIN = {'X-Emp-No': 'admin'}
LISI = {'X-Emp-No': 'lisi'}


def save_canvas(client, workflow_id, canvas, headers=ADMIN):
    return client.put(f'{KB_SERVICE_PREFIX}/workflows/{workflow_id}/flow',
                      json=canvas, headers=headers)


def publish(client, workflow_id, headers=ADMIN):
    return client.post(f'{KB_SERVICE_PREFIX}/workflows/{workflow_id}/publication',
                       headers=headers)


def get_flow(client, workflow_id, headers=ADMIN):
    return client.get(f'{KB_SERVICE_PREFIX}/workflows/{workflow_id}/flow', headers=headers)


def kb_bo(response):
    """兼容旧用例的取值器：成功返回 (合成 code, body)，失败返回 (problem, None)。

    响应是纯 JSON / RFC 9457；这里只做测试侧的适配，
    不再断言 ``{code,bo,other}`` 信封。
    """
    if 200 <= response.status_code < 300:
        return {'code': '0000', 'msg': None}, response.json()
    body = response.json()
    assert response.headers['content-type'].startswith('application/problem+json')
    return {'code': body['code'], 'msg': body['detail']}, None


# ----------------------------------------------------------------------
# 1. 空画布
# ----------------------------------------------------------------------

def test_create_seeds_the_default_canvas(client):
    """建流即播种：新画布开箱就是四段算子 + 连线，而不是空画布。

    少了这一步，前端 ``initDefaultNode()`` 兜底只会画出「开始」「结束」两个孤点。
    播种的细节（绑定回填、模板选择）在 ``test_flow_api_templates.py``。
    """
    create_workflow(client, 'wf_seeded')

    code, bo = kb_bo(get_flow(client, 'wf_seeded'))
    assert code['code'] == '0000'
    assert bo['appId'] == 'wf_seeded'
    assert bo['version'] == 1
    assert bo['flowType'] == 'workflow'
    assert {node['componentType'] for node in bo['nodeConfigDTOList']} == {
        'QUERY', 'PRE_RETRIEVER', 'RETRIEVER', 'POST_RETRIEVER', 'RESPONSE_SYNTHESIZER', 'RESPONSE'}
    assert [other['componentType'] for other in bo['otherNodeConfigList']] == ['QUERY_ENGINE', 'EDGES']


def test_loading_unknown_workflow_fails_with_business_error(client):
    response = get_flow(client, 'NO_SUCH')
    assert response.status_code == 404
    code, bo = kb_bo(response)
    assert code['code'] == 'workflow_not_found'
    assert code['msg'] == 'Knowledge retrieval NO_SUCH does not exist'   # 默认语言 en
    assert bo is None


def test_loading_unknown_workflow_renders_chinese_with_accept_language(client):
    """文案语言取 ``Accept-Language``。

    浏览器只发这个头，所以它才是「用户看到的语言」。完整矩阵见
    ``test_flow_api_language.py``；这里钉最基本的 zh-CN 一档。
    """
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/NO_SUCH/flow',
                          headers={'Accept-Language': 'zh-CN'})
    code, _ = kb_bo(response)
    assert code['msg'] == '知识检索 NO_SUCH 不存在'


# ----------------------------------------------------------------------
# 2. 保存 / 读取往返
# ----------------------------------------------------------------------

def test_save_then_load_round_trips_canvas_verbatim(client):
    create_workflow(client, 'wf_rt')
    canvas = make_canvas(kbase_name='doc_u1|#|dev')
    canvas['nodeConfigDTOList'][0]['position'] = {'x': 120, 'y': 40}   # 后端不认识也要原样存
    canvas['nodeConfigDTOList'][0]['nodeName'] = '向量检索'

    code, bo = kb_bo(save_canvas(client, 'wf_rt', canvas))
    assert code['code'] == '0000'
    assert bo == {'version': 1}                      # 保存返回版本号（首次保存 = 1）

    _, loaded = kb_bo(get_flow(client, 'wf_rt'))
    assert loaded['nodeConfigDTOList'] == canvas['nodeConfigDTOList']
    assert loaded['otherNodeConfigList'] == canvas['otherNodeConfigList']
    assert loaded['version'] == 1


def test_save_ignores_version_sent_by_client(client):
    """前端会把当前版本号回传（示例里是 99），草稿保存**不**推进版本 —— 只有发布推进。"""
    create_workflow(client, 'wf_ver')
    canvas = make_canvas()
    canvas['version'] = 99

    save_canvas(client, 'wf_ver', canvas)
    _, loaded = kb_bo(get_flow(client, 'wf_ver'))
    assert loaded['version'] == 1

    assert publish(client, 'wf_ver').json()['version'] == 1
    save_canvas(client, 'wf_ver', canvas)
    _, loaded = kb_bo(get_flow(client, 'wf_ver'))
    assert loaded['version'] == 1                    # 改草稿不推进
    assert publish(client, 'wf_ver').json()['version'] == 2   # 再发布才 +1


def test_save_rejects_empty_canvas_but_precheck_reports_it_first(client):
    create_workflow(client, 'wf_struct')
    empty = {'flowType': 'workflow', 'nodeConfigDTOList': [], 'otherNodeConfigList': []}

    response = save_canvas(client, 'wf_struct', empty)
    code, bo = kb_bo(response)
    assert code['code'] == 'validation_failed'
    assert code['msg'] == 'The canvas is empty; add at least one node before saving'
    assert bo is None
    # 结构错误下什么都没落库：草稿仍是建流时播种的那份，没被这次保存覆盖成空
    _, loaded = kb_bo(get_flow(client, 'wf_struct'))
    assert {node['componentType'] for node in loaded['nodeConfigDTOList']} == {
        'QUERY', 'PRE_RETRIEVER', 'RETRIEVER', 'POST_RETRIEVER', 'RESPONSE_SYNTHESIZER', 'RESPONSE'}


# ----------------------------------------------------------------------
# 3. preCheck
# ----------------------------------------------------------------------

def test_precheck_rejects_missing_engine_as_business_error(client):
    create_workflow(client, 'wf_pre')
    canvas = make_canvas()
    canvas['otherNodeConfigList'] = [{'componentType': 'EDGES', 'variables': {}}]  # 丢了 QUERY_ENGINE

    response = client.post(f'{KB_SERVICE_PREFIX}/workflows/wf_pre/validate',
                           json=canvas, headers={'Accept-Language': 'zh-CN'})
    code, bo = kb_bo(response)
    assert code['code'] == 'validation_failed'
    assert 'QUERY_ENGINE' in code['msg']
    assert '编排引擎' in code['msg']        # zh-CN 下是中文文案（Accept-Language，不是 language-option）
    assert bo is None


def test_precheck_returns_success_true_for_a_clean_canvas(client):
    create_workflow(client, 'wf_pre_ok')
    response = client.post(f'{KB_SERVICE_PREFIX}/workflows/wf_pre_ok/validate',
                           json=make_canvas(), headers=ADMIN)
    code, bo = kb_bo(response)
    assert code['code'] == '0000'                    # 注意：是 0000 + bo.success=false 的形状
    assert bo == {'success': True, 'message': None}


def test_precheck_returns_warning_without_blocking_save(client):
    """preCheck 只给警告（success=false），保存仍然放行 —— 否则半成品草稿存不下来。"""
    create_workflow(client, 'wf_warn')
    canvas = make_canvas(package='core.rag.post_retriever.external_model_reranker',
                         empty_stage='postretriever')
    canvas['nodeConfigDTOList'][0]['variables']['retriever'][0]['operator'] = 'ExternalModelReranker'

    response = client.post(f'{KB_SERVICE_PREFIX}/workflows/wf_warn/validate',
                           json=canvas, headers={'Accept-Language': 'zh-CN'})
    code, bo = kb_bo(response)
    assert code['code'] == '0000'
    assert bo['success'] is False
    assert 'ExternalModelReranker' in bo['message'] and 'rerank' in bo['message']
    assert bo['message'].startswith('当前部署未提供重排')

    code, _ = kb_bo(save_canvas(client, 'wf_warn', canvas))   # 保存放行
    assert code['code'] == '0000'


class StubProbe:
    """替身探测器：``models`` 为空表示「探测不到」，与真探测的 ``None`` 同义。"""

    def __init__(self, models=()):
        self._models = frozenset(models)

    def available(self):
        return self._models or None


@pytest.fixture()
def probed_client(store, capabilities, kbase_provider):
    """带探测结果的端点客户端：生成端点「只有 deepseek-chat」。"""
    def _build(models):
        app = FastAPI()
        register_flow_api(app, store=store, capabilities=capabilities,
                          kbase_provider=kbase_provider, model_probe=StubProbe(models))
        return TestClient(app)
    return _build


def _canvas_with_llm(llm):
    canvas = make_canvas()
    canvas['nodeConfigDTOList'].append({
        'componentType': 'responsesynthesizer',
        'variables': {'responsesynthesizer': [
            {'package': 'core.rag.response_synthesizer.simple_summarizer',
             'operator': 'SimpleSummarizer', 'kwargs': {'llm': llm}},
        ]},
    })
    return canvas


def test_precheck_warns_on_model_the_endpoint_does_not_serve(probed_client):
    """画布选了生成端点没有的模型 → preCheck 警告（但保存照样放行）。"""
    client = probed_client(['deepseek-chat'])
    create_workflow(client, 'wf_model')
    canvas = _canvas_with_llm('ghost-model')

    response = client.post(f'{KB_SERVICE_PREFIX}/workflows/wf_model/validate',
                           json=canvas, headers={'Accept-Language': 'zh-CN'})
    code, bo = kb_bo(response)
    assert code['code'] == '0000'
    assert bo['success'] is False
    assert 'ghost-model' in bo['message']
    assert '生成端点未提供模型' in bo['message']

    code, _ = kb_bo(save_canvas(client, 'wf_model', canvas))     # 保存放行（半成品草稿要能存）
    assert code['code'] == '0000'


def test_publish_rejects_model_the_endpoint_does_not_serve(probed_client):
    """发布是硬门槛：报 0005，且理由里带上模型名。"""
    client = probed_client(['deepseek-chat'])
    create_workflow(client, 'wf_model_pub')
    save_canvas(client, 'wf_model_pub', _canvas_with_llm('ghost-model'))

    code, _ = kb_bo(publish(client, 'wf_model_pub'))
    assert code['code'] == 'upstream_unavailable'
    assert 'ghost-model' in code['msg']


def test_publish_passes_when_model_is_served(probed_client):
    client = probed_client(['deepseek-chat'])
    create_workflow(client, 'wf_model_ok')
    save_canvas(client, 'wf_model_ok', _canvas_with_llm('deepseek-chat'))
    code, _ = kb_bo(publish(client, 'wf_model_ok'))
    assert code['code'] == '0000'


def test_probe_failure_never_blocks_publish(probed_client):
    """**无法判定 ≠ 不可用**：探测拿不到清单时，画布怎么写都放行。

    这是整套探测的安全阀 —— 生成端点抖动、或部署根本不支持 /models 时，
    都不能把用户挡在发布之外。
    """
    client = probed_client([])          # 空 = 探测不到
    create_workflow(client, 'wf_model_unknown')
    save_canvas(client, 'wf_model_unknown', _canvas_with_llm('whatever-model'))
    code, _ = kb_bo(publish(client, 'wf_model_unknown'))
    assert code['code'] == '0000'


def test_client_without_probe_stays_permissive(client):
    """没装配探测器时（既有测试与无生成端点的部署）行为不变。"""
    create_workflow(client, 'wf_no_probe')
    save_canvas(client, 'wf_no_probe', _canvas_with_llm('anything'))
    code, _ = kb_bo(publish(client, 'wf_no_probe'))
    assert code['code'] == '0000'


def test_precheck_reports_reasoning_model_warning(client):
    create_workflow(client, 'wf_reason')
    canvas = make_canvas()
    canvas['nodeConfigDTOList'][0]['variables']['preretriever'] = [
        {'package': 'pre_retriever.query_transform.query_rewrite',
         'operator': 'LLMQueryRewriter', 'kwargs': {'llm': 'DeepSeek-R1'}},
    ]
    response = client.post(f'{KB_SERVICE_PREFIX}/workflows/wf_reason/validate',
                           json=canvas, headers=ADMIN)
    _, bo = kb_bo(response)
    assert bo['success'] is False
    assert 'DeepSeek-R1' in bo['message']


# ----------------------------------------------------------------------
# 4. 发布
# ----------------------------------------------------------------------

def test_publish_creates_immutable_snapshot(client):
    create_workflow(client, 'wf_pub')
    canvas_a = make_canvas(kbase_name='doc_u1|#|dev')
    save_canvas(client, 'wf_pub', canvas_a)

    code, version = kb_bo(publish(client, 'wf_pub'))
    assert code['code'] == '0000' and version == {'version': 1}

    # 发布后继续改草稿
    canvas_b = make_canvas(kbase_name='doc_u2|#|dev')
    canvas_b['nodeConfigDTOList'][0]['variables']['retriever'][0]['kwargs']['top_k'] = 7
    save_canvas(client, 'wf_pub', canvas_b)

    # 草稿是新版；已发布快照仍是发布那一刻的内容
    _, draft = kb_bo(get_flow(client, 'wf_pub'))
    assert draft['nodeConfigDTOList'][0]['variables']['retriever'][0]['kwargs']['top_k'] == 7

    published_response = client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_pub/publication', headers=ADMIN)
    _, published = kb_bo(published_response)
    assert published['version'] == 1
    assert published['nodeConfigDTOList'] == canvas_a['nodeConfigDTOList']
    assert 'top_k' not in published['nodeConfigDTOList'][0]['variables']['retriever'][0]['kwargs']

    # 列表页要显示「有未发布的修改」：publishType 1 → 2
    _, page = kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows', params={'currentPage': 1,
                                                                       'pageSize': 10}, headers=ADMIN))
    assert page['items'][0]['publishType'] == 2


def test_publish_records_each_version_separately(client):
    create_workflow(client, 'wf_versions')
    save_canvas(client, 'wf_versions', make_canvas())
    assert publish(client, 'wf_versions').json()['version'] == 1

    save_canvas(client, 'wf_versions', make_canvas(kbase_name='doc_u9|#|dev'))
    assert publish(client, 'wf_versions').json()['version'] == 2

    published = client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_versions/publication', headers=ADMIN)
    _, bo = kb_bo(published)
    assert bo['version'] == 2
    assert bo['nodeConfigDTOList'][0]['variables']['retriever'][0]['kwargs']['knowledge_info_list'] \
        == [{'knowledge_base_name': 'doc_u9|#|dev'}]


def test_publish_without_draft_fails(client, store):
    """老数据：工作流建出来了、但从来没有画布。

    现在建流一定会播种，所以这个状态只能来自**本次改动之前**建的流（库里已有）。
    直接往 store 塞一条这样的记录 —— 它是真实存在的历史数据，不是假想分支。
    """
    store._workflows['wf_nodraft'] = WorkflowRecord(workflow_id='wf_nodraft', name='wf')

    code, _ = kb_bo(publish(client, 'wf_nodraft'))
    assert code['code'] == 'workflow_not_found'
    assert code['msg'] == 'Knowledge retrieval wf_nodraft has no saved canvas yet and cannot be published'


def test_read_published_before_publish_fails_explicitly(client):
    create_workflow(client, 'wf_nopub')
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_nopub/publication', headers=ADMIN)
    code, _ = kb_bo(response)
    assert code['code'] == 'published_workflow_not_found'
    assert 'no published version' in code['msg']


def test_publish_is_hard_gate_while_save_is_not(client):
    """同一份画布：preCheck 警告 + 保存放行，但发布硬拒（bk-service 的刻意设计）。"""
    create_workflow(client, 'wf_gate')
    canvas = make_canvas(package='retriever.unknown_retriever')
    assert save_canvas(client, 'wf_gate', canvas).status_code == 200

    code, _ = kb_bo(publish(client, 'wf_gate'))
    assert code['code'] == 'unsupported_operator'
    assert code['msg'] == 'Operator VectorRetriever cannot run in this version'

    # 硬拒之后不能留下任何已发布版本
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_gate/publication', headers=ADMIN)
    assert response.status_code == 404


def test_publish_conflict_maps_to_business_error_not_500(capabilities, kbase_provider):
    """并发发布撞上 (workflow_id, version) 唯一键 → 可读业务错误，不是 500。"""

    class ConflictingStore(InMemoryFlowStore):
        def insert_published(self, published):
            raise FlowStoreError(FlowStoreError.DUPLICATE,
                                 'duplicate key value violates unique constraint "flow_published_pkey"')

    api = FastAPI()
    register_flow_api(api, store=ConflictingStore(), capabilities=capabilities,
                      kbase_provider=kbase_provider)
    isolated = TestClient(api)
    create_workflow(isolated, 'wf_conflict')
    assert isolated.put(f'{KB_SERVICE_PREFIX}/workflows/wf_conflict/flow',
                        json=make_canvas(), headers=ADMIN).status_code == 200

    response = isolated.post(f'{KB_SERVICE_PREFIX}/workflows/wf_conflict/publication',
                             headers=ADMIN)
    assert response.status_code == 409
    body = response.json()
    assert body['code'] == 'publish_conflict'
    assert body['detail'] == ('Knowledge retrieval wf_conflict is being published concurrently, '
                              'please retry')


# ----------------------------------------------------------------------
# 其他契约点
# ----------------------------------------------------------------------

def test_download_asset_returns_octet_stream_file(client):
    create_workflow(client, 'wf_dl')
    canvas = make_canvas(kbase_name='doc_u1|#|dev')
    save_canvas(client, 'wf_dl', canvas)

    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_dl/export',
                           headers=ADMIN)
    assert response.status_code == 200
    # 不能是 application/json：前端 axios 会把 json 的 blob 当错误信封解析
    assert response.headers['content-type'].startswith('application/octet-stream')
    assert response.headers['content-disposition'] == \
        "attachment; filename*=utf-8''wf_dl.json"
    assert json.loads(response.content.decode('utf-8'))['nodeConfigDTOList'] == canvas['nodeConfigDTOList']


def test_download_asset_error_still_returns_envelope(client):
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/NO_SUCH/export',
                           headers=ADMIN)
    assert response.status_code == 404
    code, bo = kb_bo(response)
    assert code['code'] == 'workflow_not_found' and bo is None


def test_all_status_kbase_passes_kb_service_groups_through(client):
    """分组按对外契约的语义判定，RKB 原样透传 —— 包括 dev 里那条 ``status='0'``。

    回归点：RKB 曾按自己的 ``state=0``（处理成功）规则重新分组，而对外契约的
    ``0`` 是「待发布」—— 重算会把 dev-kb 提进 running，前端就会把待发布的库
    显示成「运行中」。
    """
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/knowledge-bases', headers=ADMIN)
    code, bo = kb_bo(response)
    assert code['code'] == '0000'
    assert [item['name'] for item in bo['running']] == ['demo-kb']
    assert sorted(item['name'] for item in bo['dev']) == ['dev-kb', 'graph-kb']
    assert [item['status'] for item in bo['dev']] == ['0', '5']       # 一个都不许被提走
    running = bo['running'][0]
    assert running['tableName'] == 'kb-1'            # 检索基名（运行期补 data_ 前缀）
    assert running['dbTableName'] == 'data_kb-1'
    assert running['assetId'] and running['kbasePkId'] == 'kb-1'
    # 图谱库不加 data_ 前缀
    graph = [item for item in bo['dev'] if item['name'] == 'graph-kb'][0]
    assert graph['dbTableName'] == 'graph-3'


def test_all_status_kbase_filters_by_embedding_model(client):
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/knowledge-bases',
                          params={'embedding': 'no-such-model'}, headers=ADMIN)
    _, bo = kb_bo(response)
    assert bo == {'running': [], 'dev': []}


def test_all_status_kbase_provider_failure_is_an_error_not_an_empty_dropdown(store, capabilities):
    """数据源挂了必须是显式错误（0001），不能回一个空分组让前端显示「无数据」。

    这是本模块的立身之本（见 kbase_provider 模块头）；用 router 的错误渲染兜底，
    所以这里锁一条端到端的断言。
    """
    class ExplodingProvider:
        def list_options(self, embedding_model=None):
            raise FlowStoreError(FlowStoreError.DB_ERROR, '知识库服务 unreachable')

    app = FastAPI()
    register_flow_api(app, store=store, capabilities=capabilities, kbase_provider=ExplodingProvider())
    response = TestClient(app).get(f'{KB_SERVICE_PREFIX}/workflows/knowledge-bases', headers=ADMIN)

    code, bo = kb_bo(response)
    assert code['code'] == 'internal_error' and bo is None




def test_workflow_page_contract(client):
    for name in ('alpha', 'beta', 'gamma'):
        create_workflow(client, f'wf_{name}', name=name, user='admin')

    response = client.get(f'{KB_SERVICE_PREFIX}/workflows',
                          params={'currentPage': '1', 'pageSize': '2'}, headers=ADMIN)
    _, bo = kb_bo(response)
    assert set(bo) == {'items', 'total', 'page', 'pageSize'}
    assert (bo['total'], bo['page'], bo['pageSize'], len(bo['items'])) == (3, 1, 2, 2)
    assert bo['items'][0]['workFlowId'].startswith('wf_')          # 字段名大写 F（前端契约）
    assert 'kbPkIds' in bo['items'][0] and 'graphKbPkIds' in bo['items'][0]

    # 名称模糊匹配
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows', params={'name': 'et'}, headers=ADMIN)
    _, bo = kb_bo(response)
    assert [item['name'] for item in bo['items']] == ['beta']

    # pageSize 上限 1000（防一次拉爆）
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows', params={'pageSize': '100000'}, headers=ADMIN)
    assert kb_bo(response)[1]['pageSize'] == 1000


def test_workflow_search_matches_name_id_and_creator(client):
    """搜索框的 hint 是「名称、ID 或创建人」，三列都要命中（大小写不敏感）。"""
    create_workflow(client, 'wf_alpha_1', name='Alpha', user='admin')
    create_workflow(client, 'wf_beta_2', name='Beta', user='lisi')

    def names(**params):
        _, bo = kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows', params=params, headers=ADMIN))
        return [item['name'] for item in bo['items']]

    assert names(keyword='alp') == ['Alpha']            # 名称模糊
    assert names(keyword='wf_beta_2') == ['Beta']       # 完整 ID
    assert names(keyword='BETA_2') == ['Beta']          # ID 片段 + 大小写
    assert names(keyword='LISI') == ['Beta']            # 创建人
    # LIKE 元字符按字面量：``_`` 不再当通配符
    assert names(keyword='wf_betax2') == []
    assert names(keyword='wf_beta_2') == ['Beta']


def test_workflow_page_filters_by_publish_type(client):
    """``publishType`` 在 SQL/存储层过滤：total 与当前页条数必须一致。"""
    create_workflow(client, 'wf_pub', name='pub')
    create_workflow(client, 'wf_draft', name='draft')
    assert publish(client, 'wf_pub').status_code == 201

    _, bo = kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows',
                             params={'publishType': '1'}, headers=ADMIN))
    assert [item['workFlowId'] for item in bo['items']] == ['wf_pub']
    assert bo['total'] == 1

    _, bo = kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows', headers=ADMIN))
    assert bo['total'] == 2

    code, _ = kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows',
                               params={'publishType': '9'}, headers=ADMIN))
    assert code['code'] == 'validation_failed'


def test_create_workflow_validation(client):
    # 字符集：只允许字母/数字/下划线
    response = client.post(f'{KB_SERVICE_PREFIX}/workflows',
                           json={'workFlowId': 'bad-id!', 'name': 'x'}, headers=ADMIN)
    code, _ = kb_bo(response)
    assert code['code'] == 'validation_failed'

    # 空 ID / 空名称
    assert kb_bo(client.post(f'{KB_SERVICE_PREFIX}/workflows',
                             json={'name': 'x'}, headers=ADMIN))[0]['code'] == 'validation_failed'
    assert kb_bo(client.post(f'{KB_SERVICE_PREFIX}/workflows',
                             json={'workFlowId': 'wf_x'}, headers=ADMIN))[0]['code'] == 'validation_failed'

    # 重名
    create_workflow(client, 'wf_dup')
    code, _ = kb_bo(client.post(f'{KB_SERVICE_PREFIX}/workflows',
                                json={'workFlowId': 'wf_dup', 'name': 'x'}, headers=ADMIN))
    assert code['code'] == 'workflow_exists'
    assert code['msg'] == 'Knowledge retrieval wf_dup already exists'


def test_create_workflow_accepts_workflow_id_json_alias(client):
    """前端两个历史字段名都要认（``@JsonAlias({"workflowId","appId"})``）。"""
    response = client.post(f'{KB_SERVICE_PREFIX}/workflows',
                           json={'workflowId': 'wf_alias', 'name': 'x', 'template': 'Sequential',
                                 'boundInfo': DEFAULT_BOUND_INFO}, headers=ADMIN)
    assert kb_bo(response)[1]['workFlowId'] == 'wf_alias'


def test_update_and_delete_workflow(client):
    create_workflow(client, 'wf_ud', name='old')
    save_canvas(client, 'wf_ud', make_canvas())
    publish(client, 'wf_ud')

    response = client.patch(f'{KB_SERVICE_PREFIX}/workflows/wf_ud',
                            json={'workFlowId': 'wf_ud', 'name': 'new', 'description': 'd'},
                           headers=ADMIN)
    code, bo = kb_bo(response)
    assert code['code'] == '0000'
    assert bo['name'] == 'new' and bo['description'] == 'd'
    assert bo['publishType'] == 1      # 改元数据不算「修改画布」

    deleted = client.delete(f'{KB_SERVICE_PREFIX}/workflows/wf_ud', headers=ADMIN)
    assert deleted.status_code == 204
    # 三张表都清了：草稿、快照、元数据
    assert kb_bo(get_flow(client, 'wf_ud'))[0]['code'] == 'workflow_not_found'
    assert kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_ud/publication',
                            headers=ADMIN))[0]['code'] == 'workflow_not_found'
    assert kb_bo(client.delete(f'{KB_SERVICE_PREFIX}/workflows/wf_ud',
                              headers=ADMIN))[0]['code'] == 'workflow_not_found'


def test_malformed_json_body_returns_validation_envelope(client):
    """畸形体 = 参数绑定失败 → 0004 + ``RetCode.illegalArgument``（随语言）。

    基线实测（``POST /flow?appId=…`` + 坏体）：0004，en 文案
    "Argument is illegal, please check and retry."；以前这里回的是自造的
    ``request.invalid``（"The request body is invalid; …"），不是对外契约的键。
    """
    create_workflow(client, 'wf_badjson')
    response = client.put(f'{KB_SERVICE_PREFIX}/workflows/wf_badjson/flow',
                           content=b'{not json', headers={**ADMIN, 'content-type': 'application/json'})
    assert response.status_code == 400
    code, _ = kb_bo(response)
    assert code['code'] == 'malformed_request'
    assert code['msg'] == 'Malformed request; check the request and retry'


def test_empty_body_save_reports_missing_body_not_500(client):
    """0 字节体 = 必填请求体缺席：0004 + 写死的英文，不是走到服务层的 0005。

    基线实测：``POST /flow?appId=…`` 不带体 → 0004
    "Required request body is missing"（ExceptionAdvice 对
    HttpMessageNotReadableException 的特判，**不随语言变**）。
    """
    create_workflow(client, 'wf_nobody')
    response = client.put(f'{KB_SERVICE_PREFIX}/workflows/wf_nobody/flow',
                           headers=ADMIN)
    code, _ = kb_bo(response)
    assert code['code'] == 'malformed_request'
    assert code['msg'] == 'Malformed request; check the request and retry'


# ----------------------------------------------------------------------
# 4.1 取消发布（0.1.7 批量取消发布 / 行内取消发布）
# ----------------------------------------------------------------------

def test_unpublish_clears_publish_type_and_keeps_snapshot(client):
    create_workflow(client, 'wf_unpub')
    save_canvas(client, 'wf_unpub', make_canvas())
    assert publish(client, 'wf_unpub').status_code == 201

    response = client.delete(f'{KB_SERVICE_PREFIX}/workflows/wf_unpub/publication', headers=ADMIN)
    assert response.status_code == 204
    assert not response.content

    # 列表页回到「未发布」（publishType=0），但历史快照仍然可读
    _, page = kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows',
                               params={'currentPage': 1, 'pageSize': 10}, headers=ADMIN))
    assert page['items'][0]['publishType'] == 0
    _, published = kb_bo(client.get(
        f'{KB_SERVICE_PREFIX}/workflows/wf_unpub/publication', headers=ADMIN))
    assert published['version'] == 1

    # 重复取消发布保持幂等
    assert client.delete(
        f'{KB_SERVICE_PREFIX}/workflows/wf_unpub/publication', headers=ADMIN).status_code == 204


def test_unpublish_unknown_workflow_is_404(client):
    response = client.delete(
        f'{KB_SERVICE_PREFIX}/workflows/wf_missing/publication', headers=ADMIN)
    code, _ = kb_bo(response)
    assert code['code'] == 'workflow_not_found'
