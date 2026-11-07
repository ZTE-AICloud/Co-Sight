"""模型注册表的增删改查与校验（``{RKB_PREFIX}/models``）。

**不依赖 DB / 网络**：store 注 ``InMemoryModelStore``，引用检查注桩，
探针通过 ``http_get`` / ``http_post`` 注入 —— 与 ``tests/test_kb_api_llm_list.py``
同一套裸 TestClient 写法。

断言的都是**对外契约**：信封形状（``{code:{code,msg,msgId},bo,other}``，
前端 ``base.js`` 按它解包）、错误码（0004 校验 / 0005 业务）、
以及**明文 api_key 绝不出现在任何响应里**。

跑法（服务目录下）::

    python -m pytest tests/test_model_api_crud.py -q
"""


from dataclasses import replace

import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from model.models import (  # noqa: E402
    MODEL_KIND_LLM,
    ModelRecord,
    new_model_id,
)
from model.router import MODEL_PREFIX, register_model_api  # noqa: E402
from model.service import (  # noqa: E402
    RERANK_TEST_DOCUMENTS,
    RERANK_TEST_QUERY,
    ModelService,
)
from model.repository import InMemoryModelStore  # noqa: E402

LLM_BODY = {
    'modelKind': 'llm',
    'modelName': 'deepseek-chat',
    'displayName': 'DeepSeek Chat',
    'baseUrl': 'http://10.0.0.1:4000/v1',
    'apiKey': 'sk-abcdefghijklmnop',
}


class _References:
    """引用检查桩：默认没人用。"""

    def __init__(self, used=0):
        self.used = used

    def __call__(self, kind, model_name):
        return self.used


@pytest.fixture()
def store():
    return InMemoryModelStore()


@pytest.fixture()
def service(store):
    return ModelService(store, reference_checker=_References(0))


@pytest.fixture()
def client(service):
    app = FastAPI()
    register_model_api(app, service=service)
    return TestClient(app)


def _ok(response):
    """断言 2xx 并返回纯 JSON body。"""
    assert 200 <= response.status_code < 300, response.text
    return response.json()


def _code(response):
    payload = response.json()
    assert response.status_code >= 400, '错误必须是真实 4xx/5xx'
    assert response.headers['content-type'].startswith('application/problem+json')
    return payload['code'], payload['detail']


def _url(path):
    return f'{MODEL_PREFIX}{path}'


# ---------------------------------------------------------------------------
# 增删改查
# ---------------------------------------------------------------------------
def test_create_then_list_returns_the_row_in_table_group_shape(client):
    created = _ok(client.post(_url('/models'), json=LLM_BODY))

    assert created['modelId']
    assert created['modelName'] == 'deepseek-chat'
    assert created['modelKind'] == MODEL_KIND_LLM
    assert created['source'] == 'user'

    # 前端 tableGroup.vue 的 returnStructFun 读的就是这两个字段
    listed = _ok(client.get(_url('/models'), params={'kind': 'llm'}))
    assert listed['total'] == 1
    assert listed['items'][0]['modelId'] == created['modelId']


def test_create_never_echoes_plain_api_key(client):
    created = _ok(client.post(_url('/models'), json=LLM_BODY))

    assert 'apiKey' not in created, '明文 key 不能出现在响应里'
    assert created['apiKeyMasked'] == '****mnop'
    assert created['hasApiKey'] is True
    # 整个响应体里也不能有明文（防止有人把它塞进别的字段）
    assert LLM_BODY['apiKey'] not in client.post(_url('/models'), json=LLM_BODY).text


def test_short_api_key_is_fully_masked(client):
    body = dict(LLM_BODY, apiKey='sk-123')
    created = _ok(client.post(_url('/models'), json=body))
    assert created['apiKeyMasked'] == '****'


def test_get_update_delete_round_trip(client):
    model_id = _ok(client.post(_url('/models'), json=LLM_BODY))['modelId']

    assert _ok(client.get(_url(f'/models/{model_id}')))['displayName'] == 'DeepSeek Chat'

    updated = _ok(client.put(_url(f'/models/{model_id}'), json={'displayName': '改过的名字'}))
    assert updated['displayName'] == '改过的名字'
    # 没传的字段保持原值（部分合并）
    assert updated['modelName'] == 'deepseek-chat'
    assert updated['baseUrl'] == 'http://10.0.0.1:4000/v1'

    assert _ok(client.delete(_url(f'/models/{model_id}')))['modelId'] == model_id
    assert _ok(client.get(_url('/models')))['total'] == 0


def test_thinking_off_payload_round_trip(client, store):
    off = {'chat_template_kwargs': {'thinking': False}}
    created = _ok(client.post(_url('/models'), json=dict(
        LLM_BODY, thinkingMode='custom', thinkingPayload=off)))
    model_id = created['modelId']
    assert created['thinkingMode'] == 'custom'
    assert created['thinkingPayload'] == off

    # 部分 PUT 没带这些键 → 保持原值（不能被默认值冲掉）
    updated = _ok(client.put(_url(f'/models/{model_id}'), json={'displayName': '改名'}))
    assert updated['thinkingMode'] == 'custom'
    assert updated['thinkingPayload'] == off
    assert store.get_record(model_id).thinking_mode == 'custom'

    cleared = _ok(client.put(_url(f'/models/{model_id}'), json={'thinkingMode': 'none'}))
    assert cleared['thinkingMode'] == 'none'
    assert cleared['thinkingPayload'] is None


def test_thinking_is_normalized_to_none_for_non_llm(client, store):
    """字段只有 LLM 有意义；embedding/rerank 即使传了也归一为 none。"""
    body = dict(LLM_BODY, modelKind='embedding', modelName='emb-1',
                dimension=768, thinkingMode='custom',
                thinkingPayload={'thinking': {'type': 'disabled'}})
    created = _ok(client.post(_url('/models'), json=body))
    assert created['thinkingMode'] == 'none'
    assert created['thinkingPayload'] is None
    stored = store.get_record(created['modelId'])
    assert stored.thinking_mode == 'none' and stored.thinking_payload is None


def test_thinking_auto_matches_deepseek(client):
    created = _ok(client.post(_url('/models'), json=dict(LLM_BODY, thinkingMode='auto')))

    assert created['thinkingMode'] == 'auto'
    assert created['thinkingMatchedPresetId'] == 'deepseek-vllm'
    assert created['thinkingWarning'] == ''
    # auto 不把匹配结果固化成 payload（运行时再匹配）
    assert created['thinkingPayload'] is None


def test_thinking_auto_unknown_saves_with_warning(client):
    body = dict(LLM_BODY, modelName='private-model-1', thinkingMode='auto')
    created = _ok(client.post(_url('/models'), json=body))

    assert created['thinkingMode'] == 'auto'
    assert created['thinkingMatchedPresetId'] == ''
    assert created['thinkingWarning'] == 'no_preset_match'


def test_thinking_preset_snapshots_the_catalog_payload(client, store):
    body = dict(LLM_BODY, thinkingMode='preset', thinkingPreset='qwen-vllm')
    created = _ok(client.post(_url('/models'), json=body))

    assert created['thinkingMode'] == 'preset'
    assert created['thinkingPreset'] == 'qwen-vllm'
    assert created['thinkingPayload'] == {
        'chat_template_kwargs': {'enable_thinking': False}}
    stored = store.get_record(created['modelId'])
    assert stored.thinking_mode == 'preset'
    assert stored.thinking_payload == {'chat_template_kwargs': {'enable_thinking': False}}


def test_thinking_custom_round_trip_and_partial_update(client, store):
    payload = {'reasoning_effort': 'minimal'}
    created = _ok(client.post(_url('/models'), json=dict(
        LLM_BODY, thinkingMode='custom', thinkingPayload=payload)))
    model_id = created['modelId']
    assert created['thinkingMode'] == 'custom'
    assert created['thinkingPayload'] == payload

    updated = _ok(client.put(_url(f'/models/{model_id}'), json={'displayName': '改名'}))
    assert updated['thinkingMode'] == 'custom'
    assert updated['thinkingPayload'] == payload
    assert store.get_record(model_id).thinking_payload == payload

    cleared = _ok(client.put(_url(f'/models/{model_id}'), json={'thinkingMode': 'none'}))
    assert cleared['thinkingMode'] == 'none'
    assert cleared['thinkingPayload'] is None


@pytest.mark.parametrize('body', [
    dict(LLM_BODY, thinkingMode='bogus'),
    dict(LLM_BODY, thinkingMode='preset'),
    dict(LLM_BODY, thinkingMode='preset', thinkingPreset='missing'),
    dict(LLM_BODY, thinkingMode='custom', thinkingPayload={'messages': []}),
    dict(LLM_BODY, thinkingMode='custom', thinkingPayload={'reasoning_effort': ''}),
])
def test_invalid_thinking_config_is_0004(client, body):
    code, _message = _code(client.post(_url('/models'), json=body))
    assert code == 'validation_failed'


def test_thinking_presets_catalog_route_and_match(client):
    result = _ok(client.get(_url('/models/thinking-presets'), params={
        'modelName': 'deepseek-chat',
        'baseUrl': 'http://10.0.0.1:4000/v1',
    }))

    assert result['matchedPresetId'] == 'deepseek-vllm'
    assert result['matchedBy'] == 'model_name'
    assert any(entry['presetId'] == 'deepseek-vllm' for entry in result['presets'])
    assert 'chat_template_kwargs' in result['allowedPayloadKeys']
    assert result['maxPayloadBytes'] > 0


def test_thinking_presets_empty_for_non_llm(client):
    result = _ok(client.get(_url('/models/thinking-presets'), params={'kind': 'embedding'}))
    assert result['presets'] == []
    assert result['matchedPresetId'] == ''


def test_update_with_blank_api_key_keeps_the_stored_one(client):
    model_id = _ok(client.post(_url('/models'), json=LLM_BODY))['modelId']

    # 编辑页拿不到明文，那个框默认是空的 —— 空串不能当成「清空」
    kept = _ok(client.put(_url(f'/models/{model_id}'), json={'apiKey': '', 'displayName': 'x'}))
    assert kept['hasApiKey'] is True

    cleared = _ok(client.put(_url(f'/models/{model_id}'), json={'clearApiKey': True}))
    assert cleared['hasApiKey'] is False


def test_paths_default_to_openai_standard_and_can_be_overridden(client):
    created = _ok(client.post(_url('/models'), json=LLM_BODY))
    assert created['chatPath'] == '/chat/completions'
    assert created['modelsPath'] == '/models'

    # 路径字段必须能逐行覆盖（不同端点实现的路径不同）
    overridden = _ok(client.post(_url('/models/'), json=dict(
        LLM_BODY, modelName='other', embeddingsPath='/embeddings',
        modelKind='embedding', dimension=768)))
    assert overridden['embeddingsPath'] == '/embeddings'


def test_update_does_not_freeze_a_default_path_into_an_override(client, store):
    """没改过路径的行，不能因为一次无关更新就把默认值固化成覆盖值。

    ``to_public()`` 返回的是**生效值**（覆盖 or 默认），直接拿它回写就会把默认值
    固化成覆盖值 —— 症状是「以后改默认值对这个模型不生效」，而且看不出来。
    所以断言的是**库里的原始字段**，不是接口返回的 ``chatPath``。
    """
    model_id = _ok(client.post(_url('/models'), json=LLM_BODY))['modelId']
    _ok(client.put(_url(f'/models/{model_id}'), json={'displayName': 'y'}))

    stored = store.get_record(model_id)
    assert stored.chat_path == '', '覆盖值必须仍为空（= 用默认）'
    assert stored.path_for('chat') == '/chat/completions', '生效值不变'


# ---------------------------------------------------------------------------
# 校验与业务错误
# ---------------------------------------------------------------------------
def test_invalid_kind_is_0004(client):
    code, message = _code(client.post(_url('/models'), json=dict(LLM_BODY, modelKind='vlm')))
    assert code == 'validation_failed'
    assert 'llm' in message and 'embedding' in message and 'rerank' in message


def test_missing_name_is_0004(client):
    code, _ = _code(client.post(_url('/models'), json=dict(LLM_BODY, modelName='   ')))
    assert code == 'validation_failed'


@pytest.mark.parametrize('base_url', ['', '  ', 'file:///etc/passwd', '10.0.0.1:4000/v1'])
def test_bad_base_url_is_0004(client, base_url):
    code, _ = _code(client.post(_url('/models'), json=dict(LLM_BODY, baseUrl=base_url)))
    assert code == 'validation_failed'


def test_overlong_base_url_is_0004_not_500(client):
    """超长端点地址若不拦截，会落到 varchar(1000) 变成 500。

    超长输入应在校验层返回 422（0004），而不是数据库层报内部错误。
    """
    too_long = 'http://' + ('a' * 1000) + '.com/v1'
    code, message = _code(client.post(_url('/models'), json=dict(LLM_BODY, baseUrl=too_long)))
    assert code == 'validation_failed'
    assert '1000' in message


@pytest.mark.parametrize('field,value', [
    ('displayName', 'x' * 256),
    ('apiModel', 'x' * 256),
    ('chatPath', '/' + 'x' * 255),
    ('remark', 'x' * 501),
    ('apiKey', 'x' * 1401),
    ('apiKey', '密' * 500),  # UTF-8 1500 字节，按字符数会漏
])
def test_overlong_text_fields_are_0004(client, field, value):
    """其余文本列也要在写库前拒绝，避免同类 500。"""
    body = dict(LLM_BODY, **{field: value})
    code, _ = _code(client.post(_url('/models'), json=body))
    assert code == 'validation_failed'


def test_long_existing_api_key_does_not_block_unrelated_update(client, store):
    """历史行里接近上限的 key 不能把「改显示名」也卡死。

    apiKey 只在用户提交新值时校验；编辑时的 merged 里是解密后的旧值，
    不能拿它去套新写入的上限。
    """
    model_id = _ok(client.post(_url('/models'), json=LLM_BODY))['modelId']
    stored = store.get_record(model_id)
    store.update(replace(stored, api_key='k' * 1450))

    updated = _ok(client.put(_url(f'/models/{model_id}'), json={'displayName': 'renamed'}))
    assert updated['displayName'] == 'renamed'


def test_embedding_requires_dimension(client):
    body = dict(LLM_BODY, modelKind='embedding', modelName='Qwen3-Embedding-0.6B')
    code, _ = _code(client.post(_url('/models'), json=body))
    assert code == 'validation_failed'


def test_duplicate_name_in_same_kind_is_0005(client):
    _ok(client.post(_url('/models'), json=LLM_BODY))
    code, message = _code(client.post(_url('/models'), json=dict(LLM_BODY, baseUrl='http://2.2.2.2/v1')))
    assert code == 'model_name_conflict'
    assert 'deepseek-chat' in message


def test_same_name_in_another_kind_is_allowed(client):
    _ok(client.post(_url('/models'), json=LLM_BODY))
    body = dict(LLM_BODY, modelKind='embedding', dimension=1024)
    assert _ok(client.post(_url('/models'), json=body))['modelName'] == 'deepseek-chat'


def test_unknown_model_is_0005(client):
    code, _ = _code(client.get(_url('/models/does-not-exist')))
    assert code == 'model_not_found'


def test_malformed_body_is_0004(client):
    response = client.post(_url('/models'), content=b'{not json',
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert response.json()['code'] == 'malformed_request'


def test_at_most_one_default_per_kind(store):
    service = ModelService(store, reference_checker=_References(0))
    service.create_model(dict(LLM_BODY, isDefault=True))
    service.create_model(dict(LLM_BODY, modelName='qwen3-32b', isDefault=True))

    defaults = [r for r in store.list_records(MODEL_KIND_LLM) if r.is_default]
    assert [r.model_name for r in defaults] == ['qwen3-32b']


def test_disabled_model_cannot_be_default(service):
    created = service.create_model(dict(LLM_BODY, isDefault=True, enabled=False))
    assert created.enabled is False
    assert created.is_default is False


def test_disabling_default_model_clears_default(service):
    created = service.create_model(dict(LLM_BODY, isDefault=True))
    updated = service.update_model(created.model_id, {'enabled': False})
    assert updated.enabled is False
    assert updated.is_default is False


def test_deleting_an_embedding_model_in_use_is_refused():
    store = InMemoryModelStore()
    service = ModelService(store, reference_checker=_References(used=3))
    model_id = service.create_model({
        'modelKind': 'embedding', 'modelName': 'bge-base-zh-v1.5',
        'baseUrl': 'http://local/v1', 'dimension': 768,
    }).model_id

    with pytest.raises(Exception) as error:
        service.delete_model(model_id)
    assert '3' in str(error.value) or '3' in getattr(error.value, 'args', ('',))[0]
    assert store.get_record(model_id) is not None

    # 没有引用时删得掉
    ModelService(store, reference_checker=_References(0)).delete_model(model_id)
    assert store.get_record(model_id) is None


def test_llm_model_is_not_blocked_by_the_reference_checker():
    """引用检查只对 embedding 生效：LLM 不在任何知识库上绑定。"""
    store = InMemoryModelStore()
    service = ModelService(store, reference_checker=_References(used=99))
    model_id = service.create_model(dict(LLM_BODY)).model_id
    service.delete_model(model_id)
    assert store.get_record(model_id) is None


# ---------------------------------------------------------------------------
# 连接测试
# ---------------------------------------------------------------------------
class _Response:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


def test_test_endpoint_reports_probed_models(store):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        assert url == 'http://10.0.0.1:4000/v1/models'
        assert headers.get('Authorization') == f"Bearer {LLM_BODY['apiKey']}"
        return _Response({'object': 'list', 'data': [{'id': 'deepseek-chat'}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        seen['url'] = url
        seen['body'] = json
        seen['auth'] = headers.get('Authorization')
        return _Response({'choices': [{'message': {'content': 'hi'}}]})

    service = ModelService(store, reference_checker=_References(0),
                           http_get=fake_get, http_post=fake_post)
    result = service.test_connection({'modelKind': 'llm', 'baseUrl': 'http://10.0.0.1:4000/v1',
                                      'modelName': 'deepseek-chat',
                                      'apiKey': LLM_BODY['apiKey']})

    # LLM 的判据是真实调用，清单只是补充信息
    assert result['ok'] is True
    assert result['chatOk'] is True
    assert result['chatError'] == ''
    assert result['probed'] is True
    assert result['models'] == ['deepseek-chat']
    # 请求形状：与运行时同一条 chat 路径、同一个模型名、同一把 key
    assert seen['url'] == 'http://10.0.0.1:4000/v1/chat/completions'
    assert seen['body']['model'] == 'deepseek-chat'
    assert seen['body']['messages'] == [{'role': 'user', 'content': 'hi'}]
    assert seen['body']['max_tokens'] > 0
    assert seen['auth'] == f"Bearer {LLM_BODY['apiKey']}"


def test_probe_sends_thinking_off_only_when_requested(store):
    """连接测试要与运行时同形状：行上有开关才发，没有就不发。"""
    bodies = []

    def fake_get(url, headers=None, timeout=None):
        return _Response({'data': [{'id': 'deepseek-chat'}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        bodies.append(json)
        return _Response({'choices': [{'message': {'content': 'hi'}}]})

    service = ModelService(store, reference_checker=_References(0),
                           http_get=fake_get, http_post=fake_post)
    base = {'modelKind': 'llm', 'baseUrl': 'http://10.0.0.1:4000/v1',
            'modelName': 'deepseek-chat'}

    service.test_connection(dict(base, thinkingMode='custom',
                                   thinkingPayload={'chat_template_kwargs': {'thinking': False}}))
    service.test_connection(dict(base))

    assert bodies[0]['chat_template_kwargs'] == {'thinking': False}
    assert 'chat_template_kwargs' not in bodies[1]


def test_probe_merges_auto_preset_and_custom_payloads(store):
    bodies = []

    def fake_get(url, headers=None, timeout=None):
        return _Response({'data': [{'id': 'x'}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        bodies.append(json)
        return _Response({'choices': [{'message': {'content': 'hi'}}]})

    service = ModelService(store, reference_checker=_References(0),
                           http_get=fake_get, http_post=fake_post)
    base = {'modelKind': 'llm', 'baseUrl': 'http://10.0.0.1:4000/v1'}

    service.test_connection(dict(base, modelName='deepseek-chat',
                                 thinkingMode='auto'))
    service.test_connection(dict(base, modelName='deepseek-chat',
                                 thinkingMode='preset', thinkingPreset='qwen-vllm'))
    service.test_connection(dict(base, modelName='deepseek-chat',
                                 thinkingMode='custom',
                                 thinkingPayload={'reasoning_effort': 'minimal'}))

    assert bodies[0]['chat_template_kwargs'] == {'thinking': False}
    assert bodies[1]['chat_template_kwargs'] == {'enable_thinking': False}
    assert bodies[2]['reasoning_effort'] == 'minimal'


def test_saved_model_probe_uses_the_stored_thinking_switch(client, service):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        return _Response({'data': [{'id': 'deepseek-chat'}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        seen['body'] = json
        return _Response({'choices': []})

    model_id = _ok(client.post(_url('/models'), json=dict(
        LLM_BODY, thinkingMode='custom',
        thinkingPayload={'chat_template_kwargs': {'thinking': False}})))['modelId']
    service._http_get = fake_get
    service._http_post = fake_post

    _ok(client.post(_url(f'/models/{model_id}/test'), json={}))

    assert seen['body']['chat_template_kwargs'] == {'thinking': False}


def test_test_endpoint_treats_unreachable_as_undetermined_not_broken(store):
    """探测失败 ≠ 模型不可用（契约的硬约定）：如实报告但**不据此拒绝**。"""
    def boom(url, headers=None, timeout=None, **_kwargs):
        raise OSError('connection refused')

    service = ModelService(store, reference_checker=_References(0),
                           http_get=boom, http_post=boom)
    result = service.test_connection({'modelKind': 'llm', 'baseUrl': 'http://10.0.0.1:4000/v1'})
    assert result['ok'] is False
    assert result['chatOk'] is False
    assert result['probed'] is None
    assert result['models'] is None
    assert 'model call failed' in result['message']
    # 用户可见文案要归类，底层异常类型/堆栈只进日志
    assert 'connection failed' in result['message']
    assert 'OSError' not in result['message']


def test_llm_model_in_the_list_is_not_enough_when_chat_returns_404(store):
    """真实回归（qwen3-32b）：``/models`` 里仍有该名字，但实际调用 404。

    修前这里 `ok=True`（清单探测成功即判通过），修后必须如实判失败。
    """
    def fake_get(url, headers=None, timeout=None):
        return _Response({'data': [{'id': 'qwen3-32b'}, {'id': 'deepseek-chat'}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        return _Response({'error': {
            'message': 'litellm.NotFoundError: NotFoundError: OpenAIException - '
                       'Error code: 404. Received Model Group=qwen3-32b'}}, status=404)

    service = ModelService(store, reference_checker=_References(0),
                           http_get=fake_get, http_post=fake_post)
    result = service.test_connection({'modelKind': 'llm',
                                      'baseUrl': 'http://10.0.0.1:4000/v1',
                                      'modelName': 'qwen3-32b'})

    assert result['probed'] is True
    assert 'qwen3-32b' in result['models']
    assert result['chatOk'] is False
    assert result['ok'] is False
    assert 'HTTP 404' in result['message']
    assert 'Received Model Group' in result['message']



def test_test_endpoint_measures_embedding_dimension_and_flags_mismatch(store):
    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == 'http://10.0.0.1:4000/v1/embeddings'
        assert json == {'input': ['hello'], 'model': 'Qwen3-Embedding-0.6B'}
        return _Response({'data': [{'embedding': [0.0] * 1024}]})

    service = ModelService(store, reference_checker=_References(0), http_post=fake_post)
    result = service.test_connection({
        'modelKind': 'embedding', 'baseUrl': 'http://10.0.0.1:4000/v1',
        'modelName': 'Qwen3-Embedding-0.6B', 'dimension': 768,
    })
    assert result['dimension'] == 1024
    assert result['dimensionMatches'] is False
    assert result['embeddingsOk'] is True
    assert result['embeddingsError'] == ''
    assert '1024' in result['message'] and '768' in result['message']


def test_test_endpoint_embedding_failure_reports_url_and_status(store):
    """路径少一段（``/embeddings`` vs ``/v1/embeddings``）时，结果不能只回
    「endpoint unreachable or undetermined」把人引向网络排查。

    embedding 失败必须带**实际请求的 URL + HTTP 状态**，且 ``embeddingsOk=False``
    让前端按「模型调用失败」渲染，而不是「端点可达，但无法确认模型清单」。
    """

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == 'https://llm.example.com/embeddings'
        return _Response({}, status=404)

    service = ModelService(store, reference_checker=_References(0), http_post=fake_post)
    result = service.test_connection({
        'modelKind': 'embedding', 'baseUrl': 'https://llm.example.com',
        'modelName': 'Qwen3-Embedding-0.6B', 'dimension': 1024,
    })

    assert result['embeddingsOk'] is False
    assert result['ok'] is False
    assert result['dimension'] is None
    assert result['embeddingsError'] == result['message']
    assert 'HTTP 404' in result['message']
    assert 'https://llm.example.com/embeddings' in result['message']


def test_embedding_and_rerank_never_probe_the_model_list(store):
    """清单是 **LLM-only** 能力：行里填了 ``modelsPath`` 也不拼。

    消费者只有生成端点那两处（发布校验 + 连接测试的补充信息）；embedding 的判据是
    维度实测、rerank 的是重排调用，清单对它们没有意义（端点 /models 通常 404）。
    """
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append(url)
        raise AssertionError('embedding/rerank 不应探测 /models')

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith('/embeddings'):
            return _Response({'data': [{'embedding': [0.0] * 8}]})
        return _Response({'results': [{'index': 0, 'relevance_score': 0.5}]})

    service = ModelService(store, reference_checker=_References(0),
                           http_get=fake_get, http_post=fake_post)

    emb = service.test_connection({
        'modelKind': 'embedding', 'baseUrl': 'http://10.0.0.1:4000/v1',
        'modelName': 'Qwen3-Embedding-0.6B', 'modelsPath': '/v1/models',
    })
    assert emb['probed'] is None and emb['models'] is None
    assert emb['dimension'] == 8
    # 成功文案不能再说「model list undetermined」——清单已经不在 embedding 的判定里
    assert emb['message'] == 'model call succeeded'

    rr = service.test_connection({
        'modelKind': 'rerank', 'baseUrl': 'http://10.0.0.1:8003',
        'modelName': 'Qwen3-Reranker-0.6B', 'modelsPath': '/v1/models',
    })
    assert rr['probed'] is None and rr['models'] is None
    assert rr['rerankOk'] is True

    assert seen == []


def test_test_endpoint_judges_rerank_by_real_call(store):
    """rerank 行必须真发一次 ``POST /rerank``：只探测清单会把正确的端点
    报成「端点可达，但无法确认模型清单」+ 0ms。

    判据 = 真发一次 ``POST /rerank``；清单探测对它不适用（``DEFAULT_PATHS`` 里
    rerank 没有 ``models`` 这条能力）。
    """
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen['url'] = url
        seen['body'] = json
        return _Response({'results': [
            {'index': 0, 'relevance_score': 0.98},
            {'index': 1, 'relevance_score': 0.01},
        ]})

    service = ModelService(store, reference_checker=_References(0), http_post=fake_post)
    result = service.test_connection({'modelKind': 'rerank',
                                      'baseUrl': 'http://10.0.0.1:8003',
                                      'modelName': 'Qwen3-Reranker-0.6B'})

    assert result['ok'] is True
    assert result['rerankOk'] is True
    assert result['rerankError'] == ''
    assert result['probed'] is None
    assert result['models'] is None
    assert result['message'] == 'model call succeeded'
    # 请求形状与运行时（invoke_rerank_client）一致
    assert seen['url'] == 'http://10.0.0.1:8003/rerank'
    assert seen['body'] == {
        'model': 'Qwen3-Reranker-0.6B',
        'query': RERANK_TEST_QUERY,
        'documents': list(RERANK_TEST_DOCUMENTS),
    }


def test_rerank_probe_uses_configured_path_key_and_data_envelope(store):
    """路径可覆盖（``/v1/rerank``），响应容忍 ``data`` 而不是 ``results``。"""
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen['url'] = url
        seen['auth'] = headers.get('Authorization')
        return _Response({'data': [{'index': 0, 'relevance_score': 0.5},
                                   {'index': 1, 'relevance_score': 0.1}]})

    service = ModelService(store, reference_checker=_References(0), http_post=fake_post)
    result = service.test_connection({
        'modelKind': 'rerank', 'baseUrl': 'http://10.0.0.1:8003',
        'modelName': 'Qwen3-Reranker-0.6B', 'apiKey': 'sk-rerank-123456',
        'rerankPath': '/v1/rerank',
    })

    assert result['rerankOk'] is True
    assert seen['url'] == 'http://10.0.0.1:8003/v1/rerank'
    assert seen['auth'] == 'Bearer sk-rerank-123456'


def test_rerank_probe_surfaces_http_error_detail(store):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _Response({'error': {'message': 'The model `nope` does not exist.'}}, status=404)

    service = ModelService(store, reference_checker=_References(0), http_post=fake_post)
    result = service.test_connection({'modelKind': 'rerank',
                                      'baseUrl': 'http://10.0.0.1:8003',
                                      'modelName': 'nope'})

    assert result['ok'] is False
    assert result['rerankOk'] is False
    assert 'HTTP 404' in result['message']
    assert 'does not exist' in result['message']
    assert result['rerankError'] == result['message']


def test_rerank_probe_rejects_2xx_without_usable_results(store):
    """2xx ≠ 可用：运行时只认 ``results[].index + relevance_score``，
    缺了就静默退回原顺序（= 重排没生效），所以这里也要如实判失败。"""
    def fake_post(url, json=None, headers=None, timeout=None):
        return _Response({'results': [{'index': 0, 'score': 0.9}]})

    service = ModelService(store, reference_checker=_References(0), http_post=fake_post)
    result = service.test_connection({'modelKind': 'rerank',
                                      'baseUrl': 'http://10.0.0.1:8003',
                                      'modelName': 'Qwen3-Reranker-0.6B'})

    assert result['ok'] is False
    assert result['rerankOk'] is False
    assert 'no usable results' in result['message']


def test_rerank_probe_reports_unreachable_endpoint(store):
    def boom(url, json=None, headers=None, timeout=None):
        raise OSError('connection refused')

    service = ModelService(store, reference_checker=_References(0), http_post=boom)
    result = service.test_connection({'modelKind': 'rerank',
                                      'baseUrl': 'http://10.0.0.1:8003',
                                      'modelName': 'Qwen3-Reranker-0.6B'})

    assert result['rerankOk'] is False
    assert 'connection failed' in result['message']
    assert 'connection refused' not in result['message']


def test_saved_model_test_uses_the_stored_key(client, service, monkeypatch):
    """``POST /models/{id}/test`` 用的是库里那把 key，不需要前端再传一次。"""
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen['auth'] = headers.get('Authorization')
        return _Response({'data': [{'id': 'deepseek-chat'}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        seen['chat_auth'] = headers.get('Authorization')
        return _Response({'choices': []})

    model_id = _ok(client.post(_url('/models'), json=LLM_BODY))['modelId']
    service._http_get = fake_get
    service._http_post = fake_post

    result = _ok(client.post(_url(f'/models/{model_id}/test'), json={}))
    assert result['probed'] is True
    assert result['chatOk'] is True
    # 两条探测（清单 + 真实调用）都必须带上库里那把 key
    assert seen['auth'] == f"Bearer {LLM_BODY['apiKey']}"
    assert seen['chat_auth'] == f"Bearer {LLM_BODY['apiKey']}"


def test_saved_model_test_pins_endpoint_when_no_new_key(client, service, monkeypatch):
    """安全：不重填 apiKey 时不允许把已保存的密钥发到调用方指定的端点。"""
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen['url'] = url
        return _Response({'data': [{'id': 'deepseek-chat'}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        seen['chat_url'] = url
        return _Response({'choices': []})

    model_id = _ok(client.post(_url('/models'), json=LLM_BODY))['modelId']
    service._http_get = fake_get
    service._http_post = fake_post

    _ok(client.post(_url(f'/models/{model_id}/test'), json={
        'baseUrl': 'http://attacker.example/v1'
    }))

    assert seen['url'].startswith('http://10.0.0.1:4000/v1')
    assert seen['chat_url'].startswith('http://10.0.0.1:4000/v1')
    assert 'attacker.example' not in seen['url']
    assert 'attacker.example' not in seen['chat_url']


def test_unsaved_test_endpoint_is_reachable_through_http(client, service):
    service._http_get = lambda url, headers=None, timeout=None: _Response(
        {'data': [{'id': 'm1'}, {'id': 'm2'}]})
    service._http_post = lambda url, json=None, headers=None, timeout=None: _Response(
        {'choices': []})
    result = _ok(client.post(_url('/models/test'), json={
        'modelKind': 'llm', 'baseUrl': 'http://10.0.0.1:4000/v1'}))
    assert result['models'] == ['m1', 'm2']
    assert result['chatOk'] is True


# ---------------------------------------------------------------------------
# 列表分页与过滤
# ---------------------------------------------------------------------------
def test_list_filters_by_kind_and_keyword(client, service):
    service.create_model(dict(LLM_BODY, isDefault=True))
    service.create_model({'modelKind': 'embedding', 'modelName': 'Qwen3-Embedding-0.6B',
                          'baseUrl': 'http://10.0.0.1:4000/v1', 'dimension': 1024})

    assert _ok(client.get(_url('/models')))['total'] == 2
    assert _ok(client.get(_url('/models'), params={'kind': 'llm'}))['total'] == 1
    assert _ok(client.get(_url('/models'), params={'keyword': 'qwen'}))['total'] == 1


def test_default_model_sorts_first(client, service):
    service.create_model(dict(LLM_BODY))
    service.create_model(dict(LLM_BODY, modelName='aaa-first-alphabetically'))
    service.create_model(dict(LLM_BODY, modelName='qwen3-32b', isDefault=True))

    listed = _ok(client.get(_url('/models'), params={'kind': 'llm'}))
    assert [r['modelName'] for r in listed['items']][0] == 'qwen3-32b'


def test_list_is_paginated(client, service):
    for index in range(5):
        service.create_model(dict(LLM_BODY, modelName=f'm{index}'))
    listed = _ok(client.get(_url('/models'), params={'kind': 'llm', 'currentPage': 2, 'pageSize': 2}))
    assert listed['total'] == 5
    assert len(listed['items']) == 2


def test_seeded_records_are_visible_in_the_list(store):
    store.insert(ModelRecord(model_id=new_model_id(), model_kind=MODEL_KIND_LLM,
                             model_name='deepseek-chat', base_url='http://gw/v1',
                             source='env'))
    service = ModelService(store, reference_checker=_References(0))
    listed = service.list_models(kind='llm')
    assert listed['items'][0]['source'] == 'env'


# ---------------------------------------------------------------------------
# 装配顺序（kb_api 的兜底路由会吃掉晚注册的端点）
# ---------------------------------------------------------------------------
def test_model_routes_win_over_the_kb_api_catch_all(service):
    """**注册顺序的回归守卫**。

    ``register_rkb_api`` 末尾有一条 ``/{unknown_path:path}`` 兜底路由（kb_api 用它返回
    未知路径的 0005 + msg:null）。同前缀下它会把**晚注册**的端点整批吃掉 ——
    症状是「接口全返回 0005 且没有 msg」，排查时很难想到是顺序问题。
    `src/app.py` 里因此把 ``register_model_api`` 放在它**之前**；这条用例用最小装配
    把那个顺序钉住（不 import app.py，见 tests/conftest.py 的说明）。
    """
    from http_api import register_rkb_api

    app = FastAPI()
    register_model_api(app, service=service)   # 先
    register_rkb_api(app)                       # 后（带兜底路由）

    client = TestClient(app)
    listed = client.get(f'{MODEL_PREFIX}/models', params={'kind': 'llm'})
    assert listed.status_code == 200, '被兜底路由吃掉了 → 404 problem'
    assert isinstance(listed.json(), dict)
    assert 'items' in listed.json()


# ---------------------------------------------------------------------------
# 端点变更与 SSRF 防护
# ---------------------------------------------------------------------------
def test_update_base_url_without_new_key_clears_stored_key(client, service):
    """改端点却不重新给 key：旧 key 不能跟着新端点走。

    否则可以「先 PUT 改 baseUrl（不传 apiKey）→ POST /models/{id}/test」，
    让服务端把库里保存的凭据发到攻击者指定的端点。
    """
    created = _ok(client.post(_url('/models'), json=LLM_BODY))
    model_id = created['modelId']

    _ok(client.put(_url(f'/models/{model_id}'),
                   json={'baseUrl': 'https://evil.example.com/v1'}))

    record = service.get_model(model_id)
    assert record.base_url == 'https://evil.example.com/v1'
    assert record.api_key == ''


def test_update_base_url_with_new_key_keeps_the_new_key(client, service):
    """显式重新输入 key 时，按新值保存（这是合法换端点的路径）。"""
    created = _ok(client.post(_url('/models'), json=LLM_BODY))
    model_id = created['modelId']

    _ok(client.put(_url(f'/models/{model_id}'),
                   json={'baseUrl': 'https://new.example.com/v1',
                         'apiKey': 'sk-new-key-123456'}))

    record = service.get_model(model_id)
    assert record.base_url == 'https://new.example.com/v1'
    assert record.api_key == 'sk-new-key-123456'


@pytest.mark.parametrize('base_url', [
    'http://169.254.169.254/latest',
    'http://[fe80::1]/v1',
    'http://0.0.0.0:8000/v1',
])
def test_base_url_rejects_link_local_and_metadata_hosts(client, base_url):
    """云元数据/链路本地地址不是合法的模型端点。"""
    response = client.post(_url('/models'), json={**LLM_BODY, 'baseUrl': base_url})
    code, _ = _code(response)
    assert code == 'validation_failed'


# ---------------------------------------------------------------------------
# 写操作/连接测试的管理员门禁
# ---------------------------------------------------------------------------
def test_model_write_requires_admin():
    from types import SimpleNamespace

    from model.router import _require_admin
    from shared.errors.api import KbApiError

    request = SimpleNamespace(state=SimpleNamespace(auth_user=SimpleNamespace(role='user')))
    with pytest.raises(KbApiError) as exc:
        _require_admin(request)
    assert exc.value.status == 403

    _require_admin(SimpleNamespace(
        state=SimpleNamespace(auth_user=SimpleNamespace(role='admin'))))
    _require_admin(SimpleNamespace(state=SimpleNamespace()))
