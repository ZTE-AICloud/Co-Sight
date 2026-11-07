"""四段算子加载回归：画布 → 翻译 → 契约 → 实例化 → 分桶。

这是本次「能力补齐」后必须钉住的一条链：八个内置算子 + 顺序引擎，
每一个都能走**真实路径**（`RagContext` → `load_rag_operator` →
`_build_rag_operator` → `instance_operator` → `from_args(params)`，params 里会被注入
`headers`/`user_request`）实例化出来，并被 `OperatorBean` 分到正确的桶里。

链上任何一处断了都会红：
  * 清单（default_packages_info）与真实类名/模块漂移 → import/getattr 失败；
  * 算子构造参数与画布产物（translator 的 kwargs）对不上 → from_args 失败；
  * 分桶类型漂移（比如 retriever 不再继承 BaseRagRetriever）→ 桶是空的、引擎缺件。
"""

import pytest


from engine.common.beans.rag_request import RagRequest
from engine.common.beans.rag_request_headers import RagRequestHeaders
from engine.common.exception.rag_exception import RagException
from chat import flow_config_provider
from engine.context.rag_context import RagContext
from engine.post_retriever.external_model_reranker import ExternalModelReranker
from engine.post_retriever.llm_reranker import LLMReranker
from engine.pre_retriever.query_selector.query_routing import LLMSemanticRouting
from engine.pre_retriever.query_transform.query_rewrite import LLMQueryRewriter
from engine.query_engine import OperatorBean, load_rag_operator
from engine.query_engine.multi_transform_query_engine import MultiTransformQueryEngine
from engine.response_synthesizer.simple_summarizer import RagSimpleSummarizer
from engine.retriever.fusion_retriever import FusionRetriever
from engine.retriever.keyword_retriever import KeywordRetriever
from engine.retriever.vector_retriever import VectorRetriever
from engine.rag_utils import instance_operator, instance_query_engine

WORKFLOW_ID = 'RAG_Workflow_stage_regression'
MODEL = 'deepseek-chat'


def _operator(name, package, kwargs):
    return {'id': 1, 'package': package, 'operator': name, 'desc': '', 'kwargs': kwargs}


def _stage_node(node_id, stage_key, *operators):
    return {'nodeId': node_id, 'componentType': stage_key.upper(),
            'variables': {stage_key: list(operators)}}


def _engine_node():
    return {'componentType': 'QUERY_ENGINE',
            'variables': {'queryengine': {
                'id': 0,
                'package': 'core.rag.query_engine.sequential_query_engine',
                'operator': 'SequentialQueryEngine', 'kwargs': {}}}}


def _edges_node(*pairs):
    return {'componentType': 'EDGES',
            'variables': {'edges': [{'source': s, 'target': t} for s, t in pairs]}}


def _canvas():
    """四段齐活，且**每个算子**都被画上一遍（kwargs 取默认值）。"""
    return {
        'nodeConfigDTOList': [
            _stage_node('n1', 'preretriever',
                        _operator('LLMQueryRewriter',
                                  'core.rag.pre_retriever.query_transform.query_rewrite',
                                  {'llm': MODEL, 'prompt': ''}),
                        _operator('LLMSemanticRouting',
                                  'core.rag.pre_retriever.query_selector.query_routing',
                                  {'llm': MODEL, 'prompt': ''})),
            _stage_node('n2', 'retriever',
                        _operator('VectorRetriever', 'core.rag.retriever.vector_retriever',
                                  {'strategy': 0, 'desc_info': '',
                                   'knowledge_info_list': [{'knowledge_base_name': ['doc_7'],
                                                            'priority': 10, 'top_k': 8, 'score': 0}]}),
                        _operator('KeywordRetriever', 'core.rag.retriever.keyword_retriever',
                                  {'knowledge_base_name': ['doc_7'],
                                   'priority': 10, 'top_k': 8, 'score': 0}),
                        _operator('FusionRetriever', 'core.rag.retriever.fusion_retriever',
                                  {'weights': [0.5, 0.5]})),
            _stage_node('n3', 'postretriever',
                        _operator('LLMReranker', 'core.rag.post_retriever.llm_reranker',
                                  {'llm': MODEL, 'top_n': 3}),
                        _operator('ExternalModelReranker', 'core.rag.post_retriever.external_model_reranker',
                                  {'top_n': 3})),
            _stage_node('n4', 'responsesynthesizer',
                        _operator('RagSimpleSummarizer',
                                  'core.rag.response_synthesizer.simple_summarizer',
                                  {'generator-config': [{'llm': MODEL, 'knowledge_base_name': []}]})),
        ],
        'otherNodeConfigList': [_engine_node(),
                                _edges_node(('n1', 'n2'), ('n2', 'n3'), ('n3', 'n4'))],
    }


@pytest.fixture
def rag_context(monkeypatch):
    """一条真的 RagContext：配置来自假的已发布快照，不 mock 任何算子。"""
    payload = dict(_canvas(), version=1)

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return payload

    # 画布配置走进程内 transport（签名是 app_id/scope，不是 URL/params）
    monkeypatch.setattr(flow_config_provider.rkb_transport, 'get_flow_config',
                        lambda app_id, scope='': _Response())

    user_request = RagRequest(question='知识库怎么用？', conversation_id='d-stage-1',
                              workflow_id=WORKFLOW_ID, stream=False)
    headers = RagRequestHeaders(language_option='zh')
    return RagContext(user_request, headers, flow_config_provider.get_workflow_config)


def test_all_eight_operators_are_instantiated_and_bucketed(rag_context):
    operands = load_rag_operator(rag_context)
    assert len(operands) == 8, f'八个算子应该全部加载：{[type(o).__name__ for o in operands.values()]}'

    bean = OperatorBean(operands, rag_context.get_workflow_nodes())

    assert len(bean.query_transforms) == 1 and isinstance(bean.query_transforms[0], LLMQueryRewriter)
    assert isinstance(bean.query_selector, LLMSemanticRouting)
    assert [type(r) for r in bean.retrievers] == [VectorRetriever, KeywordRetriever]
    assert isinstance(bean.fusion_retriever, FusionRetriever)
    assert [type(p) for p in bean.post_retrievers] == [LLMReranker, ExternalModelReranker]
    assert len(bean.response_synthesizers) == 1
    assert isinstance(bean.get_first_response_synthesizer(), RagSimpleSummarizer)


def test_headers_and_user_request_are_injected_into_every_operator(rag_context):
    """`_pre_setting_params` 必须注入：算子靠 config_info 里的这两个对象
    取多轮历史 / 语言 / 会话 id。少注入会在运行期 AttributeError，不在加载期。

    只有**保留** config_info 的算子能在这里断言（`LLMSemanticRouting` / `LLMReranker`
    经 `from_defaults` 构造后不带该属性 —— 这是有意保持的构造方式）。
    保留 config_info 的算子必须一个不漏，否则断言会悄悄变成空跑。
    """
    operands = load_rag_operator(rag_context)
    carrying = [operator for operator in operands.values() if hasattr(operator, 'config_info')]

    assert sorted(type(o).__name__ for o in carrying) == [
        'ExternalModelReranker', 'KeywordRetriever', 'LLMQueryRewriter', 'RagSimpleSummarizer', 'VectorRetriever']
    for operator in carrying:
        info = operator.config_info
        assert info['headers'] is rag_context.request_headers
        assert info['user_request'] is rag_context.user_request


def test_sequential_engine_is_built_from_the_loaded_operators(rag_context):
    """引擎装配也是真实路径：instance_query_engine 收的就是 RagContext。"""
    engine = instance_query_engine('core.rag.query_engine.sequential_query_engine',
                                   'SequentialQueryEngine', rag_context)

    assert isinstance(engine, MultiTransformQueryEngine)
    assert len(engine.query_transforms) == 1


def test_unknown_operator_fails_loudly_with_the_original_error_tag():
    """画布上出现清单之外的算子（自定义算子在本仓不支持）：
    报 workflow-has-no-operator，而不是 import 一个空模块名。"""
    with pytest.raises(RagException) as excinfo:
        instance_operator('custom.operator.package', 'MyCustomRetriever', {})

    assert excinfo.value.get_error_tag() == 'workflow-has-no-operator'


def test_builtin_operator_wins_over_the_canvas_package_string():
    """package 字段以清单为准：画布上存的包名错了也不影响内置算子（内置算子优先）。"""
    operator = instance_operator('a.wrong.package', 'VectorRetriever',
                                 {'headers': RagRequestHeaders(), 'user_request': None})

    assert isinstance(operator, VectorRetriever)
