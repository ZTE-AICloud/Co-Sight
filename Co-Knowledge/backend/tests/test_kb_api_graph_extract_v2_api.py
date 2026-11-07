"""v2 抽图端点（``/graph/extract*``）的纯逻辑测试。

错误码在这一族里**分得很细**，而且是两条路各一套（创建 / 更新），写错就是静默分叉 ——
需要真库、真算子的链路校验不在这里；这里钉的是纯逻辑判据。

跑法::

    python -m pytest tests/test_kb_api_graph_extract_v2_api.py -q
"""

import json

import pytest

from shared.errors.api import KbApiError  # noqa: E402
from graph.service import graph_extract_v2_api as api  # noqa: E402


def dto(**over):
    base = {'name': 'goodname', 'description': 'd', 'category': 10,
            'props': {'embeddingModel': 'm'}, 'operatorId': -6, 'kwargs': {}}
    base.update(over)
    return json.dumps(base)


# ----------------------------------------------------------------------
# data 解析
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw', ['', '   ', '{bad', '[1,2]', '"s"', 'null', '7'])
def test_parse_dto_rejects_non_objects(raw):
    with pytest.raises(KbApiError) as caught:
        api.parse_dto(raw)
    assert caught.value.key == 'graph.extract.json.parse.failed'
    assert caught.value.code == '0004'


def test_parse_dto_fails_on_wrong_field_type():
    """``operatorId`` 是 ``Long`` —— 给字符串会让 ``readValue`` 直接抛，算**解析失败**。"""
    with pytest.raises(KbApiError) as caught:
        api.parse_dto(dto(operatorId='abc'))
    assert caught.value.key == 'graph.extract.json.parse.failed'


def test_parse_dto_fills_props_dto_defaults():
    """``props: {}`` 不是空对象：``PropsDTO`` 的字段默认值会补上（并写进库里）。"""
    parsed = api.parse_dto(dto(props={}))
    assert parsed['props']['embeddingModel'] == api._default_embedding_model()
    assert parsed['props']['splitMethod'] == 'comprehensiveSplitter'
    assert parsed['props']['regex'] == '\\n\\n'


def test_parse_dto_keeps_none_props():
    """``props: null`` 要保持 None —— 那是「Embedding 模型不能为空」那条 0004 的入口。"""
    assert api.parse_dto(dto(props=None))['props'] is None


def test_dto_defaults_match_source():
    parsed = api.parse_dto(json.dumps({'name': 'ab'}))
    assert parsed['category'] == 1        # ``GraphExtractReqDTOV2.category = 1``
    assert parsed['coverFlag'] is False   # ``coverFlag = false``


# ----------------------------------------------------------------------
# parseStringList
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw', ['', 'NOT-JSON', '{"a":1}', '["a", 1, null]'])
def test_parse_string_list_swallows_bad_input(raw):
    """畸形/非数组**吞掉当空表**（只 warn），不报错 —— 与 ``data`` 的严格解析相反。"""
    assert api.parse_string_list(raw) in ([], ['a'])


def test_parse_string_list_keeps_only_strings():
    assert api.parse_string_list('["a","b"]') == ['a', 'b']
    assert api.parse_string_list('["a",1]') == ['a']


# ----------------------------------------------------------------------
# validateGraphExtractRequest（全是 0004）
# ----------------------------------------------------------------------


@pytest.mark.parametrize('name', [None, 'a', 'n' * 31, 'a@b#c$'])
def test_bad_name_reports_name_validation(name):
    with pytest.raises(KbApiError) as caught:
        api._validate_kbase({'name': name, 'props': {}})
    assert caught.value.key == 'kbase.name.validation'
    assert caught.value.code == '0004'


def test_all_whitespace_name_has_its_own_key():
    """5 个空格能过正则（``\\s`` 在类里），所以会走到**第二条**判据。"""
    with pytest.raises(KbApiError) as caught:
        api._validate_kbase({'name': '     ', 'props': {}})
    assert caught.value.key == 'kbase.name.not.all.whitespace'


def test_description_over_1000():
    with pytest.raises(KbApiError) as caught:
        api._validate_kbase({'name': 'goodname', 'description': 'x' * 1001, 'props': {}})
    assert caught.value.key == 'description.validation'


@pytest.mark.parametrize('props', [None])
def test_props_missing_is_validation_not_npe(props):
    """⚠️ 这里回 **0004**；``createKbase`` 那条 NPE（0001）在校验之后、够不着。"""
    with pytest.raises(KbApiError) as caught:
        api._validate_kbase({'name': 'goodname', 'props': props})
    assert caught.value.key == 'kbase.prop.validation'
    assert caught.value.code == '0004'


def test_operator_id_empty_only_in_v2():
    """v2 的 null **抛**；v1 那条同名方法是静默放行 —— 两条不能统一。"""
    with pytest.raises(KbApiError) as caught:
        api._validate_operator_id(None)
    assert caught.value.key == 'graph.extract.operatorid.empty'
    assert caught.value.code == '0004'


def test_operator_id_length_counts_characters():
    with pytest.raises(KbApiError) as caught:
        api._validate_operator_id(12345678901)
    assert caught.value.key == 'graph.extract.operatorid.length.exceed'
    assert caught.value.args == (11,)


def test_operator_id_unknown_uses_messageformat_separator(monkeypatch):
    """数字参数渲染带千分位（``987654`` → ``987,654``）。"""
    from operators.service import operator_service

    monkeypatch.setattr(operator_service, 'get_operator_row', lambda _op: None)
    with pytest.raises(KbApiError) as caught:
        api._validate_operator_id(987654)
    assert caught.value.key == 'graph.extract.operatorid.not.exist'
    assert caught.value.render('zh') == '算子不存在，算子ID：987,654'


# ----------------------------------------------------------------------
# kwargs：三处最容易写错的
# ----------------------------------------------------------------------


def test_kwargs_ignores_unknown_keys():
    api._validate_kwargs({'somethingElse': 'whatever', 'txId': 'x'})


def test_chunk_size_bounds():
    api._validate_kwargs({'chunkSize': 512})
    api._validate_kwargs({'chunkSize': 10240})
    with pytest.raises(KbApiError) as caught:
        api._validate_kwargs({'chunkSize': 100})
    assert caught.value.key == 'graph.extract.chunkSize.range.invalid'
    assert caught.value.render('zh') == '切片大小不合法，必须在[512, 10240]范围内，当前值：100'


def test_chunk_size_high_renders_thousands_separator():
    with pytest.raises(KbApiError) as caught:
        api._validate_kwargs({'chunkSize': 99999})
    assert caught.value.render('zh').endswith('当前值：99,999')


def test_chunk_size_float_truncates():
    """``((Number) 512.7).intValue()`` = 512 —— **能过**。"""
    api._validate_kwargs({'chunkSize': 512.7})


def test_non_numeric_chunk_size_is_0001():
    """⚠️ 那条 ``.invalid`` 文案在 properties 里不存在 → ``getMessageWithArgs``
    自己抛 → **0001**（``"abc"`` 与对象两种输入都一样）。"""
    for bad in ('abc', {'a': 1}):
        with pytest.raises(KbApiError) as caught:
            api._validate_kwargs({'chunkSize': bad})
        assert caught.value.code == '0001'


def test_overlap_bounds():
    api._validate_kwargs({'overlap': 0})
    with pytest.raises(KbApiError) as caught:
        api._validate_kwargs({'overlap': 99999})
    assert caught.value.key == 'graph.extract.overlap.range.invalid'


def test_llm_validation_is_fail_open(monkeypatch):
    """拿不到大模型列表就放行：列表不可用不能阻断抽图。"""
    monkeypatch.delenv('KB_EXTRACT_LLM_LIST', raising=False)
    api._validate_llm('no-such-llm')           # 不抛


def test_llm_validation_uses_env_hook_when_set(monkeypatch):
    monkeypatch.setenv('KB_EXTRACT_LLM_LIST', 'deepseek-chat,qwen')
    api._validate_llm('deepseek-chat')
    with pytest.raises(KbApiError) as caught:
        api._validate_llm('nope')
    assert caught.value.key == 'graph.extract.llm.invalid'


# ----------------------------------------------------------------------
# 默认文件夹名 / 语言
# ----------------------------------------------------------------------


def test_dir_title_only_zh_cn_is_chinese():
    """语言判定是**精确等于** ``zh-CN``；``zh`` / ``zh-TW`` 都算英文。"""
    assert api._dir_title('zh-CN') == '默认文件夹'
    for other in ('zh', 'zh-TW', 'en-US', '', None):
        assert api._dir_title(other) == 'Default'


# ----------------------------------------------------------------------
# update 与 create 的差别
# ----------------------------------------------------------------------


def test_update_does_not_validate_schema_id():
    """``updateGraph`` 里**没有** ``validateSchemaId`` —— 源码里就是没调。"""
    import inspect

    src = inspect.getsource(api.update_graph)
    assert 'validate_schema_id' not in src


def test_update_checks_kbase_existence_as_business_error(monkeypatch):
    """``checkIsExist`` 报业务异常 → **0005**（不是 0004）。

    顺带钉住顺序：算子校验（0004）在查库（0005）**之前** —— 先
    ``validateGraphExtractRequest`` 再 ``getKbaseById``。
    """
    from operators.service import operator_service
    from knowledge_base.service import kbase_service as kbase_store

    monkeypatch.setattr(operator_service, 'get_operator_row', lambda _op: {'id': -6})
    monkeypatch.setattr(kbase_store, 'get_kbase_row', lambda _kb: None)
    with pytest.raises(KbApiError) as caught:
        api.update_graph('nosuchkb', [], dto(), '[]', '[]', 'zh-CN', 'admin', '')
    assert caught.value.key == 'graph.extract.kbid.not.exist'
    assert caught.value.code == '0005'


def test_update_rejects_document_kbase(monkeypatch):
    """文档库不能重抽：抽图状态写到文档库上会让它一直停在「生成失败」。

    文档库的库行状态恒为 0（文档进度记在 ``kb_directory`` 行上），而抽图会写
    1/2/3/4/101…104；写进去后重新解析文档不会复原 —— 判据与图谱导入/导出同一套。
    """
    from operators.service import operator_service
    from knowledge_base.service import kbase_service as kbase_store

    monkeypatch.setattr(operator_service, 'get_operator_row', lambda _op: {'id': -6})
    monkeypatch.setattr(kbase_store, 'get_kbase_row', lambda _kb: {'category': 1})
    with pytest.raises(KbApiError) as caught:
        api.update_graph('dockb', [], dto(), '[]', '[]', 'zh-CN', 'admin', '')
    assert caught.value.key == 'graph.export.kbase.not.graph'


def test_generate_failed_is_0005():
    error = api._generate_failed()
    assert error.key == 'Retcode.generate.graph.schema.fail'
    assert error.code == '0005'
    assert error.render('zh') == '生成图谱失败，请稍后再试'


# ----------------------------------------------------------------------
# 异步状态机的两处常量
# ----------------------------------------------------------------------


def test_kbase_status_codes_match_enum():
    from graph.service import graph_extract_v2_service as service

    assert service.STATUS_PARSING == 1
    assert service.STATUS_PARSING_FAIL == 101
    assert service.STATUS_GENERATING_FAIL == 103
    assert service.STATUS_STORING == 4
    assert service.STATUS_STORING_FAIL == 104
    assert service.STATUS_PENDING == 5


def test_fail_reason_pairs_are_bilingual():
    from graph.service import graph_extract_v2_service as service

    for zh, en in (service.FAIL_REASON_SPLIT, service.FAIL_REASON_STORE):
        assert zh and en


def test_align_schema_id_rewrites_both_key_spellings():
    from graph.service import graph_extract_v2_service as service

    obj = {'schemaId': 'old', 'schema_id': 'old', 'other': 1}
    service._align_schema_id(obj, 'new')
    assert obj == {'schemaId': 'new', 'schema_id': 'new', 'other': 1}


def test_resolve_schema_reads_snake_case_schema_id(monkeypatch):
    """``schema_id`` 是下划线形式，不是 ``schemaId``。"""
    from graph.service import graph_extract_v2_service as service
    from graph.repository import graph_extract_store

    monkeypatch.setattr(graph_extract_store, 'update_task_schema_id', lambda *a: None)
    produced = [{'schema': {'schema_id': 'e2e_schema'}}]
    actual, obj = service._resolve_schema('task', {'schemaId': None}, None, produced, None)
    assert actual == 'e2e_schema'
    assert obj['schema_id'] == 'e2e_schema'


def test_resolve_schema_falls_back_to_misspelled_default(monkeypatch):
    """拿不到 ``schema_id`` 时的兜底值是拼错的 ``General_schema`` —— 这是对外契约，不能改。"""
    from graph.service import graph_extract_v2_service as service
    from graph.repository import graph_extract_store

    monkeypatch.setattr(graph_extract_store, 'update_task_schema_id', lambda *a: None)
    produced = [{'schema': {'entities': []}}]
    actual, _obj = service._resolve_schema('task', {'schemaId': None}, None, produced, None)
    assert actual == service.DEFAULT_SCHEMA_ID == 'General_schema'


def test_resolve_schema_raises_when_nothing_produced():
    """``schema.json`` 一个都没有 → 抛错（任务判失败），不是静默继续。"""
    from graph.service import graph_extract_v2_service as service

    with pytest.raises(RuntimeError):
        service._resolve_schema('task', {'schemaId': None, 'kbId': 'k'}, None, [], None)


# ----------------------------------------------------------------------
# 系统自产的 schema id（``General_Schema``）：窄例外 + 它的两条边界
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


def test_validate_schema_id_accepts_general_schema_for_general_operator(monkeypatch):
    """``-6`` + ``General_Schema``：不查模板表（既存缺陷：系统自产的 id 自己不吃）。"""
    from graph.repository import graph_schema_store

    _patch_operator(monkeypatch, -6, ['llm', 'chunkSize'])
    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id',
                        lambda _sid: pytest.fail('系统自产的 schema id 不该查模板表'))

    api._validate_schema_id('General_Schema', -6)          # 不抛


def test_validate_schema_id_rejects_general_schema_for_professional_operator(monkeypatch):
    """``-5``（吃 schema）传 ``General_Schema`` 仍是 **0004** —— 它不是模板。"""
    from graph.repository import graph_schema_store

    _patch_operator(monkeypatch, -5, ['schemaId', 'llm'])
    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id', lambda _sid: None)

    with pytest.raises(KbApiError) as caught:
        api._validate_schema_id('General_Schema', -5)
    assert caught.value.key == 'graph.extract.schema.not.found'
    assert caught.value.code == '0004'


def test_validate_schema_id_still_rejects_typo_variants(monkeypatch):
    """拼写变体（例如拼错的 ``General_schema``）不认 —— 回归闸门。

    例外只认那**一个**字面量；任何其他值照旧走模板表、查不到就是 0004，
    否则「拼错的不存在 id」与「系统自产 id」就分不开了。
    """
    from graph.repository import graph_schema_store

    _patch_operator(monkeypatch, -6, ['llm'])
    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id', lambda _sid: None)

    with pytest.raises(KbApiError) as caught:
        api._validate_schema_id('General_schema', -6)
    assert caught.value.code == '0004'


def test_resolve_schema_for_task_returns_none_obj_for_general_schema(monkeypatch):
    """建任务那次解析：``(id, None)`` —— 对象由异步里算子产出的 schema.json 补。"""
    from graph.repository import graph_schema_store

    _patch_operator(monkeypatch, -6, ['llm'])
    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id',
                        lambda _sid: pytest.fail('系统自产的 schema id 不该查模板表'))

    assert api._resolve_schema_for_task('General_Schema', -6) == ('General_Schema', None)


def test_resolve_schema_for_task_still_rejects_unknown_id(monkeypatch):
    """``no_such_schema`` 照旧 0004（建任务这次是 0004，v1 才是 0001）。"""
    from graph.repository import graph_schema_store

    _patch_operator(monkeypatch, -6, ['llm'])
    monkeypatch.setattr(graph_schema_store, 'get_schema_by_id', lambda _sid: None)

    with pytest.raises(KbApiError) as caught:
        api._resolve_schema_for_task('no_such_schema', -6)
    assert caught.value.code == '0004'


# ----------------------------------------------------------------------
# 异步 _run 的失败落库
# ----------------------------------------------------------------------


def test_operator_stage_failure_marks_task_fail(monkeypatch, tmp_path):
    """算子阶段异常时，任务行必须落 ``FAIL``，不能停在 ``RUNNING/50``。

    算子插件 ImportError 后如果只更新了 kbase 表，任务行会永远停在 RUNNING ——
    排障时看不出已经结束。
    """
    from graph.repository import graph_extract_store
    from graph.service import graph_extract_v2_service as service
    from knowledge_base.service import kbase_service

    calls = []
    monkeypatch.setattr(graph_extract_store, 'update_task_status',
                        lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(kbase_service, 'update_process', lambda *a, **k: None)
    monkeypatch.setattr(kbase_service, 'update_fail_reason', lambda *a, **k: None)
    monkeypatch.setattr(service, '_call_operator',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('operator boom')))

    # tmp_dir 非空才能走到算子阶段；用测试临时目录，finally 里的 rmtree 只清它
    service._run('task-1', str(tmp_path / 'input'), {'kbId': 'kb-1'}, None, False)

    assert calls[-1][0] == 'task-1'
    assert calls[-1][1] == graph_extract_store.STATUS_FAIL
    assert calls[-1][2] == 0
    assert 'operator boom' in calls[-1][3]


def test_create_update_task_drops_graph_database(monkeypatch):
    """更新/重抽任务必须先 drop 图谱库。

    ``kbase_v2_service._delete_graph_db`` 不存在，调用它会让「修改 → 重新构建」
    每次 AttributeError（任务停 INIT）。
    """
    from graph.repository import graph_extract_store
    from graph.service import graph_extract_v2_api as api
    from graph.service import graph_extract_v2_service, lifecycle
    from knowledge_base.service import kbase_service

    calls = []
    monkeypatch.setattr(api.graph_extract_api, 'save_tmp_files', lambda files: '/tmp/x/input')
    monkeypatch.setattr(graph_extract_store, 'insert_task', lambda **kwargs: 'task-1')
    monkeypatch.setattr(kbase_service, 'update_operator_id', lambda *a: None)
    monkeypatch.setattr(lifecycle, 'delete_graph_database',
                        lambda kb_id: calls.append(('drop', kb_id)))
    monkeypatch.setattr(graph_extract_v2_service, 'submit_update',
                        lambda *a, **k: calls.append(('submit', a[0])))

    task_id = api.create_update_task(
        {'kbId': 'kb-1', 'operatorId': -6}, [],
        {'schema_id': 'S', 'schema_obj': None}, 'emp-1', None)

    assert task_id == 'task-1'
    assert calls == [('drop', 'kb-1'), ('submit', 'task-1')]
