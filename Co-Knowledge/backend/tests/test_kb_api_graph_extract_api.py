"""抽图端点（``POST /graph/extract``）的纯逻辑测试。

真实链路（算子 → 产出 → 导入）在 ``tools/verify/verify-graph-extract-diff.py``
与手工探针里验过（算子会调 LLM，很慢，不适合放进单测）。
这里钉的是**入参解析与校验**那几处 —— 它们的错误码分得很细，写错就是静默分叉。

跑法::

    python -m pytest tests/test_kb_api_graph_extract_api.py -q
"""


import pytest

from shared.errors.api import KbApiError, KbServerError  # noqa: E402
from graph.service import graph_extract_api as api  # noqa: E402


# ----------------------------------------------------------------------
# data 解析：空串也**算失败**
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw', ['', '   ', '{bad json', '[1,2]', '"a string"', 'null', '123'])
def test_parse_dto_rejects_bad_input(raw):
    """空串/非对象都算解析失败，不是「当空对象」。"""
    with pytest.raises(KbApiError) as caught:
        api._parse_dto(raw)
    assert caught.value.key == 'graph.extract.json.parse.failed'
    assert caught.value.code == '0004'


def test_parse_dto_accepts_object():
    assert api._parse_dto('{"kbId":"x"}') == {'kbId': 'x'}
    assert api._parse_dto('{}') == {}


def test_parse_dto_message_follows_language():
    """文案是 i18n 键、跟随请求语言 —— 别写成中文字面量（英文请求回英文）。"""
    with pytest.raises(KbApiError) as caught:
        api._parse_dto('{bad')
    assert caught.value.render('en').startswith('Graph extract request parameter JSON')
    assert caught.value.render('zh').startswith('图提取请求参数JSON')


# ----------------------------------------------------------------------
# kbId / operatorId 校验
# ----------------------------------------------------------------------


def test_kb_id_null_passes_through():
    """``validateKbId(null)`` **直接 return** —— 不报错。"""
    api._validate_kb_id(None)          # 不抛


def test_kb_id_over_100_reports_length():
    with pytest.raises(KbApiError) as caught:
        api._validate_kb_id('a' * 101)
    assert caught.value.key == 'graph.extract.kbid.length.exceed'
    assert caught.value.args == (101,)
    assert caught.value.code == '0004'


def test_kb_id_missing_is_0004(monkeypatch):
    """查不到库 → 0004。**打桩**掉存储层，免得单测要连真库。"""
    from knowledge_base.service import kbase_service as kbase_store

    monkeypatch.setattr(kbase_store, 'get_kbase_row', lambda _kbid: None)
    with pytest.raises(KbApiError) as caught:
        api._validate_kb_id('0' * 32)
    assert caught.value.key == 'graph.extract.kbid.not.exist'
    assert caught.value.code == '0004'


def test_kb_id_existing_passes(monkeypatch):
    from knowledge_base.service import kbase_service as kbase_store

    monkeypatch.setattr(kbase_store, 'get_kbase_row', lambda _kbid: {'kbase_id': 'x'})
    api._validate_kb_id('x')           # 不抛


def test_operator_id_null_passes_in_v1_but_not_v2():
    """v1 的 ``validateOperatorId(null)`` **静默放行**，v2 才抛 ``operatorid.empty``。

    测试环境里没库连接，v1 那条会走到真实查询 —— 所以只钉 v2 的严格分支。
    """
    with pytest.raises(KbApiError) as caught:
        api._validate_operator_id(None, strict=True)
    assert caught.value.key == 'graph.extract.operatorid.empty'


def test_operator_id_over_10_reports_length():
    """上限是 **10 个字符**（把 Long 转成字符串再数），不是数值大小。"""
    with pytest.raises(KbApiError) as caught:
        api._validate_operator_id(12345678901)
    assert caught.value.key == 'graph.extract.operatorid.length.exceed'
    assert caught.value.args == (11,)


# ----------------------------------------------------------------------
# 杂项
# ----------------------------------------------------------------------


def test_safe_name_strips_path_and_falls_back():
    assert api.safe_name('a/b/c.md', 0) == 'c.md'
    assert api.safe_name('a\\b\\c.md', 0) == 'c.md'
    assert api.safe_name('', 3) == 'upload_3'
    assert api.safe_name('..', 1) == 'upload_1'


def test_empty_tmp_dir_save_raises_for_v2():
    """空表落临时目录会抛 —— 图谱「更新」一个文件都没有时就是死在这里（→0005）。"""
    with pytest.raises(ValueError):
        api.save_tmp_files([])


def test_no_schema_id_literal_is_the_source_string():
    """没给 schemaId 时写入的字面量必须是 ``"None"`` —— 它会落进任务行，不能改成空串。"""
    assert api.NO_SCHEMA_ID == 'None'


def test_limits_match_source():
    assert api.KB_ID_MAX == 100
    assert api.OPERATOR_ID_MAX == 10


def test_graph_files_are_what_import_engine_reads():
    """算子产出与导入引擎读的条目名必须一致（``entities.jsonl``/``edges.jsonl``）。"""
    from graph.service import graph_import_engine as engine

    assert set(api.GRAPH_FILES) == {engine.ENTITIES_ENTRY, engine.EDGES_ENTRY}


# ----------------------------------------------------------------------
# ``schema`` 参数的注入闸门：只给声明了 schemaId 的专业算子
# ----------------------------------------------------------------------


def _patch_operator(monkeypatch, operator_id, param_names):
    """把算子行与参数表打桩（单测不连库）。"""
    from operators.service import operator_service
    from operators.repository import operator_store

    monkeypatch.setattr(operator_service, 'get_operator_row',
                        lambda _oid: {'id': operator_id})
    monkeypatch.setattr(
        operator_store, 'list_params_by_operator_ids',
        lambda _ids: {operator_id: [{'arg_name': name} for name in param_names]})


def _capture_graph_extract(monkeypatch, operator_id, param_names):
    """打桩算子行 + ``operator_runtime.graph_extract``，返回这次调用的实参。"""
    _patch_operator(monkeypatch, operator_id, param_names)
    from knowledge_base.task import operator_runtime

    captured = {}

    def fake_graph_extract(**call):
        captured.update(call)
        return {'code': '0'}

    monkeypatch.setattr(operator_runtime, 'graph_extract', fake_graph_extract)
    return captured


def test_operator_consumes_schema_reads_declared_params(monkeypatch):
    """判据是算子自己声明的 ``schemaId``：-5 有（专业），-6 没有（通用）。"""
    _patch_operator(monkeypatch, -5, ['schemaId', 'llm'])
    assert api.operator_consumes_schema(-5) is True

    _patch_operator(monkeypatch, -6, ['chunkSize', 'llm', 'overlap'])
    assert api.operator_consumes_schema(-6) is False


def test_operator_consumes_schema_false_when_operator_missing(monkeypatch):
    """算子行查不到 → False（且**不去查参数表**：没有 operator_id 可查）。"""
    from operators.service import operator_service
    from operators.repository import operator_store

    monkeypatch.setattr(operator_service, 'get_operator_row', lambda _oid: None)
    monkeypatch.setattr(operator_store, 'list_params_by_operator_ids',
                        lambda _ids: pytest.fail('不该查参数表'))

    assert api.operator_consumes_schema(-404) is False


def test_call_operator_skips_schema_for_general_operator(monkeypatch):
    """通用算子 + 请求带 schemaId → **不塞** ``schema``（回归闸门）。

    通用算子签名里没有 ``schema`` 形参，无条件注入会 →
    ``TypeError: graph_extract() got an unexpected keyword argument 'schema'``
    → 任务 FAIL。这里同时钉「连 ``graph_schema`` 都不查」（闸门在最前面短路）。
    """
    from graph.repository import graph_schema_store

    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id',
                        lambda _sid: pytest.fail('通用算子不该解析 schema'))
    captured = _capture_graph_extract(monkeypatch, -6, ['chunkSize', 'llm', 'overlap'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'm'}}, -6, '/p.py', '/f.md',
                      'OntologyGraph')

    assert [arg['argName'] for arg in captured['args']] == ['kwargs']
    assert captured['args'][0]['defaultValue'] == {'llm': 'm'}


def test_call_operator_injects_schema_for_professional_operator(monkeypatch):
    """专业算子（声明了 schemaId）仍拿到 ``schema`` —— -5 的签名里它是**必填**。"""
    from graph.repository import graph_schema_store

    monkeypatch.setattr(
        graph_schema_store, 'get_schema_by_id',
        lambda _sid: {'schema_obj': {'schema_id': 'OntologyGraph'}})
    captured = _capture_graph_extract(monkeypatch, -5, ['schemaId', 'llm'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'm'}}, -5, '/p.py', '/f.md',
                      'OntologyGraph')

    assert [arg['argName'] for arg in captured['args']] == ['schema', 'kwargs']
    assert captured['args'][0]['defaultValue'] == {'schema_id': 'OntologyGraph'}


def test_call_operator_skips_schema_when_no_schema_id(monkeypatch):
    """没给 schemaId 时（专业算子也一样）不塞 ``schema``，且不查 graph_schema。"""
    from graph.repository import graph_schema_store

    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id',
                        lambda _sid: pytest.fail('没给 schemaId 不该解析 schema'))
    captured = _capture_graph_extract(monkeypatch, -5, ['schemaId', 'llm'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'm'}}, -5, '/p.py', '/f.md',
                      api.NO_SCHEMA_ID)

    assert [arg['argName'] for arg in captured['args']] == ['kwargs']


# ----------------------------------------------------------------------
# 模型端点（``llmConfig``）：注册表新增的模型才下发
# ----------------------------------------------------------------------


def _fake_resolve(monkeypatch, endpoint):
    """打桩 ``model.resolver.resolve``（不连注册表）。"""
    from model import resolver as model_resolver

    calls = []

    def fake_resolve(kind, model_name=None, operation=None, thinking_profile='answer'):
        calls.append({'kind': kind, 'model_name': model_name,
                      'operation': operation, 'thinking_profile': thinking_profile})
        return endpoint

    monkeypatch.setattr(model_resolver, 'resolve', fake_resolve)
    return calls


def _resolved(**overrides):
    from model.resolver import ResolvedEndpoint

    fields = dict(
        kind='llm', model_name='deepseek-chat-1', api_model='deepseek-chat',
        url=('http://10.0.0.50:30804/codebase-deepseek-chat-0731/v1/v1'
             '/chat/completions'),
        origin='registry', source='user')
    fields.update(overrides)
    return ResolvedEndpoint(**fields)


def _last_operator_kwargs(captured):
    """``extract_params`` 是「后者胜」：取最后一条 ``kwargs``。"""
    entries = [arg for arg in captured['args'] if arg['argName'] == 'kwargs']
    assert entries, '算子调用缺少 kwargs 参数'
    return entries[-1]['defaultValue']


def test_user_model_gets_registry_endpoint(monkeypatch):
    """模型管理页新增的模型（source=user）→ 下发端点，算子不用再猜网关。"""
    _fake_resolve(monkeypatch, _resolved())
    captured = _capture_graph_extract(monkeypatch, -6, ['chunkSize', 'llm', 'overlap'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'deepseek-chat-1'}},
                      -6, '/p.py', '/f.md', api.NO_SCHEMA_ID)

    kwargs = _last_operator_kwargs(captured)
    assert kwargs['llm'] == 'deepseek-chat-1'      # 注册名原样保留（算子只记日志）
    assert kwargs['llmConfig'] == {
        'url': ('http://10.0.0.50:30804/codebase-deepseek-chat-0731/v1/v1'
                '/chat/completions'),
        'model': 'deepseek-chat',                 # 发给端点的才是 api_model
    }


def test_endpoint_config_carries_key_and_thinking_payload(monkeypatch):
    """有 key / 思考片段时一起带过去；``timeout`` 用模型行上的。"""
    _fake_resolve(monkeypatch, _resolved(
        api_key='sk-candidate', timeout=120,
        thinking_payload={'chat_template_kwargs': {'enable_thinking': False}}))
    captured = _capture_graph_extract(monkeypatch, -6, ['llm'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'deepseek-chat-1'}},
                      -6, '/p.py', '/f.md', api.NO_SCHEMA_ID)

    config = _last_operator_kwargs(captured)['llmConfig']
    assert config['api_key'] == 'sk-candidate'
    assert config['timeout'] == 120
    assert config['thinking_payload'] == {'chat_template_kwargs': {'enable_thinking': False}}


def test_env_seeded_model_keeps_the_fixed_gateway(monkeypatch):
    """``.env`` 播种的模型（source=env）**不下发** —— 抽图端点固定走部署网关。"""
    _fake_resolve(monkeypatch, _resolved(
        model_name='deepseek-chat', api_model='deepseek-chat',
        url='http://10.0.0.51:4000/v1/chat/completions', source='env'))
    captured = _capture_graph_extract(monkeypatch, -6, ['llm'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'deepseek-chat'}},
                      -6, '/p.py', '/f.md', api.NO_SCHEMA_ID)

    assert 'llmConfig' not in _last_operator_kwargs(captured)


def test_env_fallback_model_keeps_the_fixed_gateway(monkeypatch):
    """注册表里查不到（``origin='env'`` 回落）也不下发 —— 固定走部署网关。"""
    _fake_resolve(monkeypatch, _resolved(
        model_name='unknown', api_model='unknown', url='http://env-gw/v1/chat/completions',
        origin='env', source='env'))
    captured = _capture_graph_extract(monkeypatch, -6, ['llm'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'unknown'}},
                      -6, '/p.py', '/f.md', api.NO_SCHEMA_ID)

    assert 'llmConfig' not in _last_operator_kwargs(captured)


def test_no_llm_does_not_touch_the_registry(monkeypatch):
    """没 ``llm`` 的请求（错请求）不该为解析端点去查注册表。"""
    from model import resolver as model_resolver

    monkeypatch.setattr(model_resolver, 'resolve',
                        lambda *a, **k: pytest.fail('没有 llm 就不该解析端点'))
    captured = _capture_graph_extract(monkeypatch, -6, ['chunkSize'])

    api.call_operator({'kbId': 'k', 'kwargs': {}}, -6, '/p.py', '/f.md',
                      api.NO_SCHEMA_ID)

    assert 'llmConfig' not in _last_operator_kwargs(captured)


def test_endpoint_resolution_is_documented_as_auxiliary_call(monkeypatch):
    """抽图是逐 chunk 的辅助调用 → 思考片段按 ``aux`` 解析（关闭/最低档）。"""
    calls = _fake_resolve(monkeypatch, _resolved())
    _capture_graph_extract(monkeypatch, -6, ['llm'])

    api.call_operator({'kbId': 'k', 'kwargs': {'llm': 'deepseek-chat-1'}},
                      -6, '/p.py', '/f.md', api.NO_SCHEMA_ID)

    assert calls == [{'kind': 'llm', 'model_name': 'deepseek-chat-1',
                      'operation': 'chat', 'thinking_profile': 'aux'}]


# ----------------------------------------------------------------------
# 系统自产的 schema id（``General_Schema``）：窄例外 + 它的两条边界
# ----------------------------------------------------------------------


def test_general_schema_id_is_the_value_operators_self_report():
    """常量就是通用算子 ``_generate_schema()`` 自报的那个字面量（PVC 上算子源码如此）。"""
    assert api.GENERAL_SCHEMA_ID == 'General_Schema'


def test_resolve_schema_accepts_general_schema_for_general_operator(monkeypatch):
    """``-6`` + ``General_Schema``：不查模板表，返回 ``(id, None)``。

    既存缺陷：系统自己产出的 id 自己不吃 ——
    现在走「没给 schemaId」那条路，schema 对象由算子产出的 schema.json 补上。
    """
    from graph.repository import graph_schema_store

    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id',
                        lambda _sid: pytest.fail('系统自产的 schema id 不该查模板表'))
    _patch_operator(monkeypatch, -6, ['chunkSize', 'llm', 'overlap'])

    assert api._resolve_schema('General_Schema', -6) == ('General_Schema', None)


def test_resolve_schema_rejects_general_schema_for_professional_operator(monkeypatch):
    """``-5``（吃 schema）传 ``General_Schema`` 仍是 **0001** —— 它不是模板。

    判据的第 2 条：这个 id 只在**不吃 schema** 的通用链路里有意义。
    """
    from graph.repository import graph_schema_store

    _patch_operator(monkeypatch, -5, ['schemaId', 'llm'])
    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id', lambda _sid: None)

    with pytest.raises(KbServerError):
        api._resolve_schema('General_Schema', -5)


def test_resolve_schema_still_rejects_unknown_id_for_general_operator(monkeypatch):
    """拼错/不存在的 id 照旧 0001（不能被这个例外放宽）—— 回归闸门。"""
    from graph.repository import graph_schema_store

    _patch_operator(monkeypatch, -6, ['chunkSize', 'llm'])
    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id', lambda _sid: None)

    with pytest.raises(KbServerError):
        api._resolve_schema('no_such_schema', -6)
