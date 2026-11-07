"""配置契约（`core/config/rag_config_bean.py`）与取配置入口（`flow_config_provider`）的测试。

链路：画布 blob → `translator` 翻译 → **契约校验** → `RagContext`。
这里钉住的是第二段与第三段之间的那道闸门：
  * 正常形状的翻译结果必须通过（否则会把好配置拦掉）；
  * 形状不对的必须**在校验这一步**就失败，而不是等到算子实例化。
"""

import pytest


from engine.common.exception.rag_exception import RagException
from engine.config.rag_config_bean import ConfigBean, RagConfig
from chat import flow_config_provider
from chat.translator import canvas_to_rag_config


def operator(name, package='core.rag.retriever.vector_retriever', **kwargs):
    return {'id': 1, 'package': package, 'operator': name, 'desc': '', 'kwargs': kwargs}


def stage_node(node_id, stage_key, *operators):
    return {'nodeId': node_id, 'componentType': stage_key.upper(), 'variables': {stage_key: list(operators)}}


def engine_node():
    return {'componentType': 'QUERY_ENGINE',
            'variables': {'queryengine': {'package': 'core.rag.query_engine.sequential_query_engine',
                                          'operator': 'SequentialQueryEngine', 'kwargs': {}}}}


def edges_node(*pairs):
    return {'componentType': 'EDGES',
            'variables': {'edges': [{'source': s, 'target': t} for s, t in pairs]}}


def canvas():
    return {
        'nodeConfigDTOList': [
            stage_node('n1', 'preretriever', operator('LLMQueryRewriter', llm='deepseek-chat')),
            stage_node('n2', 'retriever', operator('VectorRetriever', knowledge_info_list=[])),
            stage_node('n3', 'postretriever', operator('LLMReranker', llm='deepseek-chat', top_n=3)),
            stage_node('n4', 'responsesynthesizer',
                       operator('RagSimpleSummarizer', generator_config=[{'llm': 'deepseek-chat'}])),
        ],
        'otherNodeConfigList': [engine_node(), edges_node(('n1', 'n2'), ('n2', 'n3'), ('n3', 'n4'))],
    }


def test_translated_canvas_matches_the_contract():
    """翻译产物必须能过契约模型（别名/类型都对齐），否则会被闸门拦掉。"""
    config = canvas_to_rag_config('RAG_Workflow_t', canvas()['nodeConfigDTOList'],
                                  canvas()['otherNodeConfigList'])
    parsed = RagConfig.model_validate(config)
    assert parsed.workflow_id == 'RAG_Workflow_t'
    assert isinstance(parsed.pre_retriever[0], ConfigBean)
    assert parsed.pre_retriever[0].operator == 'LLMQueryRewriter'
    assert [op.id for op in parsed.retriever] == [2]
    assert parsed.workflow['edges'] == [[1, 2], [2, 3], [3, 4]]


def test_contract_rejects_operator_without_required_fields():
    """算子少了 package/operator/kwargs 时必须在契约这一层被拒。"""
    with pytest.raises(Exception) as excinfo:
        RagConfig.model_validate({'workflow_id': 'x', 'retriever': [{'id': 1}]})
    assert 'package' in str(excinfo.value)


class FakeConfigResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {'Content-Type': 'application/json'}
        self.text = ''

    def json(self):
        return self._payload


@pytest.fixture
def fake_kb_service(monkeypatch):
    """换掉进程内 transport，记录被请求的 app_id 与 scope。

    进程内调用没有 URL —— 「读草稿还是读快照」由 **scope** 表达，
    断言随之落在 scope 上。
    """
    captured = {}

    def _install(payload, status_code=200):
        def _get(app_id, scope=''):
            captured['app_id'] = app_id
            captured['scope'] = scope
            return FakeConfigResponse(payload, status_code)

        monkeypatch.setattr(flow_config_provider.rkb_transport, 'get_flow_config', _get)
        return captured

    return _install


def _published_payload(canvas_body):
    return canvas_body


def test_get_workflow_config_reads_the_published_snapshot(fake_kb_service):
    captured = fake_kb_service(_published_payload(dict(canvas(), version=7, workflow_name='t')))
    config = flow_config_provider.get_workflow_config('RAG_Workflow_t', '')
    assert captured['scope'] == '', '默认读**发布快照**（scope 非 dev）'
    assert captured['app_id'] == 'RAG_Workflow_t'
    assert config['workflow_id'] == 'RAG_Workflow_t'
    assert len(config['pre-retriever']) == 1


def test_get_workflow_config_uses_draft_for_dev_scope(fake_kb_service):
    captured = fake_kb_service(_published_payload(dict(canvas(), version=3)))
    flow_config_provider.get_workflow_config('RAG_Workflow_t', 'dev')
    assert captured['scope'] == 'dev', 'dev scope 读**草稿**'


def test_get_workflow_config_fails_loudly_on_missing_workflow(fake_kb_service):
    fake_kb_service({'code': 'published_workflow_not_found', 'status': 404,
                     'detail': 'not exist'}, status_code=404)
    with pytest.raises(RagException) as excinfo:
        flow_config_provider.get_workflow_config('RAG_Workflow_t', '')
    assert excinfo.value.get_error_tag() == 'published-workflow-not-found'


def test_get_workflow_config_maps_a_non_json_body_to_a_business_error(fake_kb_service):
    """正文不是 JSON 也必须是业务错误，不能让 JSONDecodeError 冒到 app 层。

    ⚠️ 这条**只对 transport 替身成立**：进程内调用不会产出
    HTML 错误页（那是「请求打到代理」的症状）。保留它是因为 `get_workflow_config`
    里那段 `except ValueError` 仍在，且仍应把契约外的响应折成业务错误 ——
    将来若 transport 换成别的实现（比如又走网络），这道防线还在。
    """
    class _Html(FakeConfigResponse):
        text = '\n<html><head><title>DNS解析失败</title></head></html>'

        def json(self):
            raise ValueError('Expecting value: line 2 column 1 (char 1)')

    fake_kb_service(_Html(None))
    with pytest.raises(RagException) as excinfo:
        flow_config_provider.get_workflow_config('RAG_Workflow_t', '')
    assert excinfo.value.get_error_tag() == 'request-knowledgebase-failed'


def test_get_workflow_config_rejects_a_broken_canvas(fake_kb_service):
    """画布能取到、但翻译出来的形状不对 → 报 workflow-config-invalid，不往下跑。"""
    broken = {
        'nodeConfigDTOList': [
            # kwargs 存成了 JSON 字符串（而不是对象）：下游 `_pre_setting_params` 会往它里面
            # 塞 headers/user_request —— 字符串不支持赋值，报错点离这里很远
            {'nodeId': 'n1', 'componentType': 'RETRIEVER',
             'variables': {'retriever': [{'package': 'core.rag.retriever.vector_retriever',
                                          'operator': 'VectorRetriever',
                                          'kwargs': '{"top_k": 8}'}]}},
        ],
        'otherNodeConfigList': [engine_node()],
    }
    fake_kb_service(_published_payload(broken))
    with pytest.raises(RagException) as excinfo:
        flow_config_provider.get_workflow_config('RAG_Workflow_t', '')
    assert excinfo.value.get_error_tag() == 'workflow-config-invalid'
    assert 'kwargs' in excinfo.value.get_args()[1]


def test_get_workflow_config_rejects_operator_with_empty_name(fake_kb_service):
    """别名/类型都对、但算子是空串：契约发现不了，靠 _validate_contract 的第二道检查。"""
    broken = {
        'nodeConfigDTOList': [
            {'nodeId': 'n1', 'componentType': 'RETRIEVER',
             'variables': {'retriever': [{'package': '', 'operator': '', 'kwargs': {}}]}},
        ],
        'otherNodeConfigList': [engine_node()],
    }
    fake_kb_service(_published_payload(broken))
    with pytest.raises(RagException) as excinfo:
        flow_config_provider.get_workflow_config('RAG_Workflow_t', '')
    assert excinfo.value.get_error_tag() == 'workflow-config-invalid'
    assert 'retriever[0]' in excinfo.value.get_args()[1]
