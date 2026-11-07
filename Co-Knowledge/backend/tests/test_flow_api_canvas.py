"""画布解析 / 校验 / 文案的单元测试（不起 HTTP，不碰 DB）。

这些函数是「同一份画布 JSON 被重复解释」的地方 —— 解释错了不会报错，只会在
运行期跑出空结果或让发布放行不该放的编排，所以逐条钉住。
"""

import pytest

from workflow import canvas as canvas_util
from workflow import messages, validation
from workflow.errors import FlowError
from workflow.models import FlowCanvasInput
from workflow.runtime_config import RuntimeCapabilities, from_env

from conftest import make_canvas

RERANK_URL = 'http://rerank.local:9997/v1/rerank'


def _canvas(**kwargs) -> FlowCanvasInput:
    return FlowCanvasInput.from_payload(make_canvas(**kwargs))


# ----------------------------------------------------------------------
# 画布解析
# ----------------------------------------------------------------------

def test_find_engine_operator_reads_query_engine_node():
    canvas = _canvas()
    assert canvas_util.find_engine_operator(canvas.other_node_config_list) == 'SequentialQueryEngine'


def test_find_engine_operator_returns_none_without_engine_node():
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {}}],
        'otherNodeConfigList': [{'componentType': 'EDGES', 'variables': {}}],
    })
    assert canvas_util.find_engine_operator(canvas.other_node_config_list) is None


def test_find_engine_operator_tolerates_broken_nodes():
    # 画布字段是前端自由构造的：variables 不是 dict、queryengine 是字符串都不能抛
    broken = [
        {'componentType': 'QUERY_ENGINE', 'variables': 'not-a-dict'},
        {'componentType': 'QUERY_ENGINE', 'variables': {'queryengine': 'not-a-dict'}},
        {'componentType': 'QUERY_ENGINE'},
        'not-a-node',
        None,
    ]
    assert canvas_util.find_engine_operator(broken) is None


def test_extract_operators_takes_every_list_of_dicts():
    """有意「多报」：variables 下任何 list 里的 dict 都算算子。"""
    variables = {
        'retriever': [{'operator': 'VectorRetriever'}],
        'responsesynthesizer': [{'operator': 'SimpleSummarizer'}],
        'something_unexpected': [{'operator': 'SurpriseOperator'}],
        'not_a_list': {'operator': 'Ignored'},
        'list_of_strings': ['a', 'b'],
    }
    names = [item['operator'] for item in canvas_util.extract_operators(variables)]
    assert names == ['VectorRetriever', 'SimpleSummarizer', 'SurpriseOperator']


def test_collect_bound_kbase_names_merges_three_locations():
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [
            {'variables': {'retriever': [{'kwargs': {
                'knowledge_base_name': 'kb_keyword|#|dev',
                'knowledge_info_list': [{'knowledge_base_name': 'kb_vector|#|publish'},
                                        {'knowledge_base_name': 'kb_vector'}],
                'generator_config': [{'knowledge_base_name': 'kb_generator'}],
            }}]}},
        ],
    })
    # 去 scope 后缀、按出现顺序去重（kb_vector 出现两次只留一次）
    assert canvas_util.collect_bound_kbase_names(canvas.node_config_dto_list) == [
        'kb_keyword', 'kb_vector', 'kb_generator',
    ]


def test_collect_bound_kbase_names_accepts_plain_string_and_array():
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {'responsesynthesizer': [{'kwargs': {
            'knowledge_base_name': ['kb_a', ' kb_b ', '', None],
        }}]}}],
    })
    assert canvas_util.collect_bound_kbase_names(canvas.node_config_dto_list) == ['kb_a', 'kb_b']


def test_collect_bound_kbase_names_ignores_operators_without_kwargs():
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {'retriever': [{'operator': 'VectorRetriever'},
                                                           {'kwargs': 'not-a-dict'}]}}],
    })
    assert canvas_util.collect_bound_kbase_names(canvas.node_config_dto_list) == []


@pytest.mark.parametrize('raw,expected', [
    ('doc_abc|#|dev', 'doc_abc'),
    ('doc_abc|#|publish', 'doc_abc'),
    ('doc_abc', 'doc_abc'),
    ('plain', 'plain'),
])
def test_drop_scope_suffix(raw, expected):
    assert canvas_util.drop_scope_suffix(raw) == expected


@pytest.mark.parametrize('raw,expected', [
    ('graph_uuid-2', 'uuid-2'),
    ('data_uuid-3', 'uuid-3'),
    ('uuid-4', 'uuid-4'),
    ('doc_uuid-5', 'uuid-5'),
    ('doc_uuid-6_vector', 'uuid-6'),
])
def test_strip_kb_prefix(raw, expected):
    assert canvas_util.strip_kb_prefix(raw) == expected


# ----------------------------------------------------------------------
# 校验
# ----------------------------------------------------------------------

def test_check_structure_rejects_empty_canvas():
    with pytest.raises(FlowError) as excinfo:
        validation.check_structure(FlowCanvasInput(), 'zh')
    assert excinfo.value.key == 'canvas.empty'
    assert excinfo.value.render('zh') == '画布为空，请至少添加一个节点后再保存'


def test_check_structure_rejects_canvas_without_engine():
    canvas = FlowCanvasInput.from_payload({'nodeConfigDTOList': [{'variables': {}}]})
    with pytest.raises(FlowError) as excinfo:
        validation.check_structure(canvas, 'en')
    assert excinfo.value.key == 'canvas.no.engine'


def test_check_structure_rejects_oversized_canvas():
    # 真造一份 >5MB 的画布，钉住边界值本身（不是只走一遍分支）
    huge = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {'retriever': [{'kwargs': {'blob': 'x' * (5 * 1024 * 1024)}}]}}],
        'otherNodeConfigList': [{'componentType': 'QUERY_ENGINE', 'variables': {'queryengine': {'operator': 'SequentialQueryEngine'}}}],
    })
    with pytest.raises(FlowError) as excinfo:
        validation.check_structure(huge, 'zh')
    assert excinfo.value.key == 'canvas.too.large'
    assert '5MB' in excinfo.value.render('zh')


def test_find_unrunnable_operators_reports_names_sorted_and_deduped():
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [
            {'variables': {
                'retriever': [
                    {'package': 'core.rag.retriever.vector_retriever', 'operator': 'VectorRetriever'},
                    {'package': 'vendor.missing_pkg', 'operator': 'ZetaOperator'},
                    {'package': 'vendor.missing_pkg', 'operator': 'ZetaOperator'},
                    {'package': 'vendor.another_missing'},
                ],
            }},
        ],
    })
    assert validation.find_unrunnable_operators(canvas) == ['ZetaOperator', 'vendor.another_missing']


def test_check_runnable_rejects_non_sequential_engine():
    canvas = _canvas(engine='ParallelQueryEngine')
    with pytest.raises(FlowError) as excinfo:
        validation.check_runnable(canvas, RuntimeCapabilities())
    assert excinfo.value.key == 'engine.unsupported'
    assert 'ParallelQueryEngine' in excinfo.value.render('en')


def test_check_runnable_rejects_unknown_operator_package():
    canvas = _canvas(package='retriever.some_new_retriever')
    with pytest.raises(FlowError) as excinfo:
        validation.check_runnable(canvas, RuntimeCapabilities())
    assert excinfo.value.key == 'operator.unsupported'


def test_external_model_reranker_is_runable_only_when_rerank_endpoint_deployed():
    """判据是**部署能力**而不是算子名单。"""
    canvas = _rerank_canvas()

    without_endpoint = RuntimeCapabilities(rerank_url='')
    with_endpoint = RuntimeCapabilities(rerank_url=RERANK_URL)

    assert validation.uses_external_model_reranker_without_endpoint(canvas, without_endpoint) is True
    assert validation.uses_external_model_reranker_without_endpoint(canvas, with_endpoint) is False
    with pytest.raises(FlowError) as excinfo:
        validation.check_runnable(canvas, without_endpoint)
    assert excinfo.value.key == 'rerank.endpoint.missing'
    # 配了端点就该放行（不能再报 operator.unsupported 之外的错）
    validation.check_runnable(canvas, with_endpoint)


def _rerank_canvas(model=None, operator='ExternalModelReranker',
                   package='core.rag.post_retriever.external_model_reranker') -> FlowCanvasInput:
    """一张带外部重排算子的最小画布；``model=None`` 表示没写这个键。"""
    canvas = _canvas(package=package)
    node = canvas.node_config_dto_list[0]['variables']['retriever'][0]
    node['operator'] = operator
    node['kwargs'] = {}
    if model is not None:
        node['kwargs']['model'] = model
    return canvas


def test_rerank_model_check_only_applies_to_explicit_choices():
    """空值 = 跟随部署默认，不算「不可用」；显式选了才比对，且大小写不敏感。"""
    capabilities = RuntimeCapabilities(rerank_url=RERANK_URL,
                                       rerank_models=('Qwen3-Reranker-4B',))

    assert validation.find_unavailable_rerank_models(_rerank_canvas(), capabilities) == []
    assert validation.find_unavailable_rerank_models(_rerank_canvas(''), capabilities) == []
    assert validation.find_unavailable_rerank_models(
        _rerank_canvas('qwen3-reranker-4b'), capabilities) == []
    assert validation.find_unavailable_rerank_models(
        _rerank_canvas('BAAI/bge-reranker-large'), capabilities) == ['BAAI/bge-reranker-large']


def test_rerank_model_check_is_skipped_when_the_deployment_has_no_rerank():
    """没有端点时由 ``rerank.endpoint.missing`` 报错，避免同一原因两条警告。"""
    capabilities = RuntimeCapabilities(rerank_url='', rerank_models=())

    assert validation.find_unavailable_rerank_models(
        _rerank_canvas('whatever'), capabilities) == []


def test_check_runnable_rejects_a_rerank_model_missing_from_the_registry():
    canvas = _rerank_canvas('BAAI/bge-reranker-large')
    capabilities = RuntimeCapabilities(rerank_url=RERANK_URL,
                                       rerank_models=('Qwen3-Reranker-4B',))

    with pytest.raises(FlowError) as excinfo:
        validation.check_runnable(canvas, capabilities)

    assert excinfo.value.key == 'rerank.model.unavailable'
    assert 'BAAI/bge-reranker-large' in excinfo.value.render('en')


def test_precheck_warns_about_a_rerank_model_missing_from_the_registry():
    canvas = _rerank_canvas('BAAI/bge-reranker-large')
    capabilities = RuntimeCapabilities(rerank_url=RERANK_URL,
                                       rerank_models=('Qwen3-Reranker-4B',))

    warnings = validation.precheck_warnings(canvas, 'zh', capabilities)

    assert any('BAAI/bge-reranker-large' in warning for warning in warnings)


def test_find_reasoning_model_in_query_rewriter_is_case_insensitive():
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {'preretriever': [
            {'operator': 'LLMQueryRewriter', 'kwargs': {'llm': 'DeepSeek-R1'}},
        ]}}],
    })
    capabilities = RuntimeCapabilities(reasoning_models=('deepseek-r1', 'qwq-32b'))
    assert validation.find_reasoning_model_in_query_rewriter(canvas, capabilities) == 'DeepSeek-R1'


def test_find_reasoning_model_ignores_other_operators_and_missing_llm():
    capabilities = RuntimeCapabilities(reasoning_models=('deepseek-r1',))
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {'preretriever': [
            {'operator': 'LLMQuerySelector', 'kwargs': {'llm': 'deepseek-r1'}},
            {'operator': 'LLMQueryRewriter', 'kwargs': {}},
            {'operator': 'LLMQueryRewriter', 'kwargs': {'llm': 'qwen-72b'}},
        ]}}],
    })
    assert validation.find_reasoning_model_in_query_rewriter(canvas, capabilities) is None


def _llm_node(*llms: str, stage: str = 'responsesynthesizer') -> dict:
    """一个合法算子的节点，每个 llm 一个算子实例（用来同时塞可用/不可用的模型）。"""
    return {
        'componentType': stage,
        'variables': {stage: [
            {'package': 'core.rag.response_synthesizer.simple_summarizer',
             'operator': 'SimpleSummarizer', 'kwargs': {'llm': llm}}
            for llm in llms
        ]},
    }


def _canvas_with_llm(*llms: str) -> FlowCanvasInput:
    """最小可用画布（``make_canvas`` 带 QUERY_ENGINE，能过引擎/算子两道） + 带 llm 的合成器节点。

    ``check_runnable`` 的检查是**按顺序短路**的，所以只想验「模型不可用」那条时，
    画布必须先满足引擎与算子两项 —— 否则抛的是前一条。
    """
    return FlowCanvasInput.from_payload(make_canvas(extra_node=_llm_node(*llms)))


def test_find_unavailable_models_is_silent_when_not_probed():
    """**无法判定 ≠ 不可用**：没探测到（空集）时必须一律放行。

    这条是整套探测的安全阀 —— 生成端点抖一下、或某个部署根本不支持 /models，
    都不能把用户挡在发布之外。
    """
    canvas = _canvas_with_llm('随便什么模型')
    assert validation.find_unavailable_models(canvas, RuntimeCapabilities()) == []
    assert validation.find_unavailable_models(
        canvas, RuntimeCapabilities(available_models=frozenset())) == []
    # 连发布门槛也要放行
    validation.check_runnable(canvas, RuntimeCapabilities())


def test_find_unavailable_models_reports_only_the_missing_ones():
    canvas = _canvas_with_llm('deepseek-chat', 'ghost-model')
    capabilities = RuntimeCapabilities(available_models=frozenset({'deepseek-chat', 'qwen3-32b'}))
    assert validation.find_unavailable_models(canvas, capabilities) == ['ghost-model']


def test_find_unavailable_models_tolerates_case_and_provider_prefix():
    """网关报别名（``deepseek/deepseek-chat``）而画布写短名，或反过来，都算同一个。

    宁可漏报也不误报：误报会把能跑的编排拦在发布之外。
    """
    long_name = _canvas_with_llm('deepseek/deepseek-chat')
    short_name = _canvas_with_llm('DeepSeek-Chat')
    available = frozenset({'deepseek-chat'})

    assert validation.find_unavailable_models(long_name, RuntimeCapabilities(available_models=available)) == []
    assert validation.find_unavailable_models(short_name, RuntimeCapabilities(available_models=available)) == []
    # 反过来：网关只有带前缀的名字，画布写短名
    prefixed = frozenset({'deepseek/deepseek-chat'})
    assert validation.find_unavailable_models(
        _canvas_with_llm('deepseek-chat'), RuntimeCapabilities(available_models=prefixed)) == []


def test_find_unavailable_models_ignores_operators_without_llm():
    # make_canvas 的检索器 kwargs 里没有 llm，只有 knowledge_info_list
    canvas = _canvas()
    capabilities = RuntimeCapabilities(available_models=frozenset({'deepseek-chat'}))
    assert validation.find_unavailable_models(canvas, capabilities) == []


def test_check_runnable_rejects_unavailable_model():
    canvas = _canvas_with_llm('ghost-model')
    capabilities = RuntimeCapabilities(available_models=frozenset({'deepseek-chat'}))
    with pytest.raises(FlowError) as excinfo:
        validation.check_runnable(canvas, capabilities)
    assert excinfo.value.key == 'model.unavailable'
    assert 'ghost-model' in excinfo.value.args[0]


def test_find_unavailable_models_skips_self_hosted_registered_model():
    """模型管理里自带端点的注册模型：探测只探部署生成端点，对它没有判据。

    误报场景：注册名 ``deepseek-chat-1`` 指向自己的
    候选端点（10.0.0.50），画布选它时可运行，但探测清单（部署网关）里没有
    这个名字 → 保存报警告、**发布被硬拦**。自带端点要放行。
    """
    canvas = _canvas_with_llm('deepseek-chat-1')
    capabilities = RuntimeCapabilities(
        available_models=frozenset({'deepseek-chat'}),
        self_hosted_models=frozenset({'deepseek-chat-1'}),
    )
    assert validation.find_unavailable_models(canvas, capabilities) == []
    # 发布门槛（check_runnable）也必须放行，否则保存能过、发布永远过不去
    validation.check_runnable(canvas, capabilities)


def test_find_unavailable_models_compares_api_model_for_registered_alias():
    """注册名 ≠ api_model、且都走部署生成端点：按运行时真正发送的 api_model 比对。"""
    canvas = _canvas_with_llm('flash-alias')
    capabilities = RuntimeCapabilities(
        available_models=frozenset({'deepseek-chat'}),
        llm_api_models={'flash-alias': 'deepseek-chat'},
    )
    assert validation.find_unavailable_models(canvas, capabilities) == []


def test_find_unavailable_models_still_reports_gateway_model_missing_from_endpoint():
    """走部署生成端点的注册模型照旧校验，**不能**因为进了注册表就一律放行。"""
    canvas = _canvas_with_llm('old-alias')
    capabilities = RuntimeCapabilities(
        available_models=frozenset({'deepseek-chat'}),
        llm_api_models={'old-alias': 'gone-model'},
    )
    assert validation.find_unavailable_models(canvas, capabilities) == ['old-alias']


def test_find_empty_stages_lists_stage_keys():
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {
            'preretriever': [], 'retriever': [{'operator': 'VectorRetriever'}],
            'postretriever': [], 'responsesynthesizer': [{'operator': 'SimpleSummarizer'}],
        }}],
    })
    assert validation.find_empty_stages(canvas) == ['preretriever', 'postretriever']


def test_precheck_warnings_follow_kb_service_order():
    """前 5 条警告的顺序 = 引擎 → 算子 → rerank → 空环节 → 推理模型。

    **第 6 条「模型不可用」是 RKB 独有的**，见
    :func:`test_unavailable_model_warning_comes_last` —— workflow 端点已由本服务
    接管（``frontend/nginx.conf`` 的 ``/api/co-knowledge/v1/workflows``），不再有独立的 preCheck
    与生成端点配置可探，所以只在 RKB 侧加。本用例刻意不探测（``available_models`` 为空），
    断言的就仍是前 5 条警告的固定顺序。
    """
    canvas = FlowCanvasInput.from_payload({
        'nodeConfigDTOList': [{'variables': {
            'preretriever': [{'package': 'core.rag.pre_retriever.query_transform.query_rewrite',
                              'operator': 'LLMQueryRewriter', 'kwargs': {'llm': 'DeepSeek-R1'}}],
            'retriever': [{'package': 'retriever.unknown_retriever', 'operator': 'NewRetriever'}],
            'postretriever': [],
            'responsesynthesizer': [],
        }}],
        'otherNodeConfigList': [{'componentType': 'QUERY_ENGINE',
                                 'variables': {'queryengine': {'operator': 'ParallelQueryEngine'}}}],
    })
    capabilities = RuntimeCapabilities(reasoning_models=('deepseek-r1',))
    warnings = validation.precheck_warnings(canvas, 'zh', capabilities)

    assert len(warnings) == 4
    assert 'ParallelQueryEngine' in warnings[0]          # engine.unsupported
    assert 'NewRetriever' in warnings[1]                 # operator.unsupported
    assert 'postretriever' in warnings[2]                # empty.stage（两个空环节合并成一句）
    assert 'responsesynthesizer' in warnings[2]
    assert 'DeepSeek-R1' in warnings[3]                  # reasoning.model.recommend
    assert validation.join_warnings(warnings) == '；'.join(warnings)


def test_unavailable_model_warning_comes_last():
    """第 6 条（模型不可用）**殿后**，且只在探测成功时才出现。

    顺序有语义：前端把 ``join_warnings`` 的结果整句弹出来，基线警告在前更像「主要问题」，
    而模型不可用是运行期才暴露的那类，放最后。
    """
    # 用不可运行的算子包，让 operator.unsupported 也出现 —— 才验得出「殿后」而不是「唯一」
    canvas = FlowCanvasInput.from_payload(make_canvas(
        package='retriever.unknown_retriever', extra_node=_llm_node('ghost-model')))
    capabilities = RuntimeCapabilities(available_models=frozenset({'deepseek-chat'}))
    warnings = validation.precheck_warnings(canvas, 'zh', capabilities)

    assert warnings[-1] == validation.render('model.unavailable', 'zh', 'ghost-model')
    # operator.unsupported 仍在最前（报的是 operator 名，包名不认识时才回退报包名）
    assert warnings[0] == validation.render('operator.unsupported', 'zh', 'VectorRetriever')
    assert len(warnings) == 2

    # 同一份画布、探测不到时 → 那一条必须消失（无法判定 ≠ 不可用）
    assert len(validation.precheck_warnings(canvas, 'zh', RuntimeCapabilities())) == 1


def test_model_unavailable_message_is_translated():
    """文案是对外契约的一部分：中英都得有，且要带上模型名。"""
    zh = messages.render('model.unavailable', 'zh', 'ghost-model')
    en = messages.render('model.unavailable', 'en', 'ghost-model')
    assert 'ghost-model' in zh and 'ghost-model' in en
    assert zh != en


def test_precheck_warnings_single_warning_joins_to_itself():
    canvas = _rerank_canvas()
    warnings = validation.precheck_warnings(canvas, 'en', RuntimeCapabilities())
    # ExternalModelReranker 是 vendor 算子 → 只剩「没配 rerank 端点」一条
    assert len(warnings) == 1
    assert 'ExternalModelReranker' in warnings[0]
    assert 'LLMReranker' in warnings[0]
    assert validation.join_warnings(warnings) == warnings[0]


@pytest.mark.parametrize('raw,expected', [
    ('wf_1', 'wf_1.json'),
    ('wf-1.2', 'wf-1.2.json'),
    ('中文名', '___.json'),
    ('', 'rag_workflow.json'),
    (None, 'rag_workflow.json'),
    ('%2e%2e/../../etc/passwd', '_2e_2e_.._.._etc_passwd.json'),
    ('a\r\nX-Injected: 1', 'a__X-Injected__1.json'),
])
def test_safe_file_name(raw, expected):
    assert validation.safe_file_name(raw) == expected


def test_safe_file_name_truncates_to_reasonable_length():
    assert len(validation.safe_file_name('a' * 500)) == 100 + len('.json')


# ----------------------------------------------------------------------
# 运行能力配置与文案
# ----------------------------------------------------------------------

def test_runtime_capabilities_from_env_parses_models_and_rerank_url():
    capabilities = from_env({
        'RKB_FLOW_LLM_MODELS': 'm1=模型一; m2=Model-Two',
        'RKB_FLOW_REASONING_MODELS': 'r1, R2 ,, r3',
        'RKB_RERANK_URL': RERANK_URL,
        'RERANK_MODEL': 'Qwen3-Reranker-4B',
        'EMBEDDING_MODEL': 'Qwen3-Embedding-0.6B',
    })
    assert capabilities.llm_models == (('m1', '模型一'), ('m2', 'Model-Two'))
    assert capabilities.reasoning_models == ('r1', 'R2', 'r3')
    assert capabilities.has_rerank_endpoint() is True
    assert capabilities.rerank_models == ('Qwen3-Reranker-4B',)
    # 没有注册表时运行期只认 .env 这个向量模型名
    assert capabilities.embedding_models == ('Qwen3-Embedding-0.6B',)


def test_runtime_capabilities_from_env_falls_back_to_defaults():
    capabilities = from_env({})
    assert capabilities.llm_models  # 内置默认清单，不能是空的
    assert 'deepseek-reasoner' in capabilities.reasoning_models
    assert capabilities.has_rerank_endpoint() is False
    # 没有端点就没有可选的模型（不是「有一个 bge 可用」）
    assert capabilities.rerank_models == ()
    # 没配向量模型 = 无法判定，校验放行（不是「所有模型都不可用」）
    assert capabilities.embedding_models == ()


def test_default_llm_model_entries_use_display_name_fallback():
    capabilities = from_env({'RKB_FLOW_LLM_MODELS': 'only-model'})
    assert capabilities.llm_models == (('only-model', 'only-model'),)


@pytest.mark.parametrize('language,expected', [
    ('zh', '知识检索 wf_1 不存在'),
    ('zh-CN', '知识检索 wf_1 不存在'),
    ('en', 'Knowledge retrieval wf_1 does not exist'),
    (None, 'Knowledge retrieval wf_1 does not exist'),
])
def test_message_language_normalization(language, expected):
    assert messages.render('workflow.not.exist', language, 'wf_1') == expected


def test_message_rendering_and_unknown_key_fallback():
    assert messages.render('workflowId.too.long', 'zh') == '知识检索ID长度不能超过128'
    # 未知键回落成键名（排障时一眼看出是文案缺失，而不是空提示）
    assert messages.render('no.such.key', 'zh') == 'no.such.key'
    # 参数个数对不上时返回原文案，不应抛异常
    assert '{0}' in messages.render('workflow.not.exist', 'zh')


# ----------------------------------------------------------------------
# 向量模型不在注册表
# ----------------------------------------------------------------------
def _embedding_canvas(model=None, kbase=None) -> FlowCanvasInput:
    """最小可用画布 + 检索器上的向量模型；``model=None`` 表示没写这个键。"""
    canvas = _canvas()
    operator = canvas.node_config_dto_list[0]['variables']['retriever'][0]
    operator['kwargs'] = {}
    if model is not None:
        operator['kwargs']['embedding'] = model
    if kbase is not None:
        operator['kwargs']['knowledge_base_name'] = [kbase]
    return canvas


def test_embedding_model_check_only_applies_to_explicit_choices():
    """空值 = 跟随部署默认（运行期取注册表默认行）；显式写了才比对，且大小写不敏感。"""
    capabilities = RuntimeCapabilities(embedding_models=('Qwen3-Embedding-0.6B',))

    assert validation.find_unavailable_embedding_models(_embedding_canvas(), capabilities) == []
    assert validation.find_unavailable_embedding_models(_embedding_canvas(''), capabilities) == []
    assert validation.find_unavailable_embedding_models(
        _embedding_canvas('qwen3-embedding-0.6b'), capabilities) == []
    assert validation.find_unavailable_embedding_models(
        _embedding_canvas('stella-large-zh-v3-1792d'), capabilities) == [
            'stella-large-zh-v3-1792d']


def test_embedding_model_check_is_skipped_when_the_registry_is_unreadable():
    """空清单 = 无法判定（不是「一个模型都没有」），发布门槛必须放行。"""
    canvas = _embedding_canvas('whatever')

    assert validation.find_unavailable_embedding_models(canvas, RuntimeCapabilities()) == []
    validation.check_runnable(canvas, RuntimeCapabilities())


def test_check_runnable_rejects_an_embedding_model_missing_from_the_registry():
    canvas = _embedding_canvas('stella-large-zh-v3-1792d')
    capabilities = RuntimeCapabilities(embedding_models=('Qwen3-Embedding-0.6B',))

    with pytest.raises(FlowError) as excinfo:
        validation.check_runnable(canvas, capabilities)

    assert excinfo.value.key == 'embedding.model.unavailable'
    assert 'stella-large-zh-v3-1792d' in excinfo.value.render('en')


def test_precheck_warns_about_an_embedding_model_missing_from_the_registry():
    canvas = _embedding_canvas('stella-large-zh-v3-1792d')
    capabilities = RuntimeCapabilities(embedding_models=('Qwen3-Embedding-0.6B',))

    warnings = validation.precheck_warnings(canvas, 'zh', capabilities)

    assert any('stella-large-zh-v3-1792d' in warning for warning in warnings)


def _bound_canvas_payload(model, kbase) -> dict:
    """``make_canvas`` 的原始 payload + 检索器上的模型与绑定库（给 FlowService 用）。"""
    payload = make_canvas()
    operator = payload['nodeConfigDTOList'][0]['variables']['retriever'][0]
    operator['kwargs'] = {'embedding': model, 'knowledge_base_name': [kbase]}
    return payload


def test_find_embedding_dimension_mismatches_reports_the_kbase_and_both_dims():
    canvas = _embedding_canvas('stella-large-zh-v3-1792d', kbase='graph_abc')
    capabilities = RuntimeCapabilities(
        embedding_models=('stella-large-zh-v3-1792d',),
        embedding_dimensions={'stella-large-zh-v3-1792d': 1792})

    mismatches = validation.find_embedding_dimension_mismatches(
        canvas, capabilities, {'graph_abc': 1024})

    assert len(mismatches) == 1
    assert 'graph_abc' in mismatches[0]
    assert '1024' in mismatches[0] and '1792' in mismatches[0]


def test_embedding_dimension_check_is_silent_without_judgement():
    """任何一侧拿不到维度都**放行** —— 无法判定 ≠ 不一致（与模型清单同一条安全阀）。"""
    canvas = _embedding_canvas('m', kbase='graph_abc')

    # 模型维度未知（注册表行没填 dimension、也没 .env 默认）
    assert validation.find_embedding_dimension_mismatches(
        canvas, RuntimeCapabilities(), {'graph_abc': 1024}) == []
    # 库维度未知（表还没建 / 读不到）
    capabilities = RuntimeCapabilities(embedding_dimensions={'m': 1024})
    assert validation.find_embedding_dimension_mismatches(canvas, capabilities, {}) == []
    assert validation.find_embedding_dimension_mismatches(canvas, capabilities) == []


def test_embedding_dimension_check_ignores_operators_without_a_bound_kbase():
    canvas = _embedding_canvas('m')
    capabilities = RuntimeCapabilities(embedding_dimensions={'m': 1024})

    assert validation.find_embedding_dimension_mismatches(
        canvas, capabilities, {'graph_abc': 1792}) == []


def test_check_runnable_rejects_an_embedding_dimension_mismatch():
    canvas = _embedding_canvas('stella-large-zh-v3-1792d', kbase='graph_abc')
    capabilities = RuntimeCapabilities(
        embedding_models=('stella-large-zh-v3-1792d',),
        embedding_dimensions={'stella-large-zh-v3-1792d': 1792})

    with pytest.raises(FlowError) as excinfo:
        validation.check_runnable(canvas, capabilities, {'graph_abc': 1024})

    assert excinfo.value.key == 'embedding.dimension.mismatch'
    assert 'graph_abc' in excinfo.value.render('en')


def test_precheck_warns_about_an_embedding_dimension_mismatch():
    canvas = _embedding_canvas('stella-large-zh-v3-1792d', kbase='graph_abc')
    capabilities = RuntimeCapabilities(
        embedding_models=('stella-large-zh-v3-1792d',),
        embedding_dimensions={'stella-large-zh-v3-1792d': 1792})

    warnings = validation.precheck_warnings(canvas, 'zh', capabilities, {'graph_abc': 1024})

    assert any('graph_abc' in warning for warning in warnings)


def test_publish_rejects_a_kbase_whose_vector_dimension_differs():
    """发布是最后一道配置门槛：维度对不上必须在这里停住，而不是等用户点发送。"""
    from workflow.models import FlowDraft, WorkflowRecord
    from workflow.repository import InMemoryFlowStore
    from workflow.service import FlowService

    from conftest import FakeKbaseOptionProvider

    payload = _bound_canvas_payload('stella-large-zh-v3-1792d', 'graph_abc')
    store = InMemoryFlowStore()
    store.create_workflow_with_draft(
        WorkflowRecord(workflow_id='wf_dim', name='wf_dim'),
        FlowDraft(workflow_id='wf_dim',
                  node_config=payload['nodeConfigDTOList'],
                  other_node_config=payload['otherNodeConfigList']))
    service = FlowService(
        store,
        capabilities=RuntimeCapabilities(
            embedding_models=('stella-large-zh-v3-1792d',),
            embedding_dimensions={'stella-large-zh-v3-1792d': 1792}),
        kbase_provider=FakeKbaseOptionProvider(),
        kbase_dimension_provider=lambda names: {name: 1024 for name in names})

    with pytest.raises(FlowError) as excinfo:
        service.publish('wf_dim', 'tester', 'en')

    assert excinfo.value.key == 'embedding.dimension.mismatch'
