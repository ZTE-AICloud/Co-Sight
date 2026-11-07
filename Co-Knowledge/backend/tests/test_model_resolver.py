"""运行期端点解析（``core/gateway/model_resolver.py``）。

三条必须钉住的性质：

1. **回落**：注册表为空 / 读不到 → 结果与纯读 ``.env`` 逐项一致。
   这是「升级不炸、回滚干净」的前提。
2. **接管**：注册表有行 → 端点、key、模型名、维度全部来自注册表。
3. **立即生效**：写完调 :func:`invalidate` 之后，**同一个进程里下一次解析就能看到**——
   「不停机新增模型」这句话能不能兑现，全看这条。

不依赖 DB / 网络：用 ``InMemoryModelStore`` 替掉 ``_make_store``（**只换 store，
不桩掉缓存与解析**，否则等于把要测的逻辑一起跳过）。

跑法（服务目录下）::

    python -m pytest tests/test_model_resolver.py -q
"""


import pytest

from model.models import ModelRecord, new_model_id  # noqa: E402
from model.repository import InMemoryModelStore  # noqa: E402
from model import resolver as model_resolver  # noqa: E402

ENV = {
    'GENERATION_GATEWAY_URL': 'http://env-gw:4000/v1',
    'GENERATION_MODEL': 'env-default-llm',
    'GENERATION_API_KEY': 'sk-env',
    'GENERATION_MODELS_PATH': '/models',
    'GENERATION_MAX_TOKENS': '8192',
    'GENERATION_TEMPERATURE': '0.01',
    'GENERATION_TIMEOUT': '180',
    'MODEL_GATEWAY_URL': 'https://env-embed',
    'MODEL_GATEWAY_EMBEDDINGS_PATH': '/v1/embeddings',
    'MODEL_GATEWAY_API_KEY': 'sk-mgw',
    'EMBEDDING_MODEL': 'Qwen3-Embedding-0.6B',
    'EMBEDDING_MODEL_NAME': 'Qwen3-Embedding-0.6B',
    'EMBEDDING_DIMENSION': '1024',
    'RKB_FLOW_LLM_MODELS': 'env-a=Env-A;env-b=Env-B',
    'RKB_FLOW_REASONING_MODELS': 'env-a',
    'RERANK_URL': '',
}

MODEL_ID = new_model_id()


def _llm(model_name='reg-llm', **kwargs):
    base = dict(model_id=new_model_id(), model_kind='llm', model_name=model_name,
                display_name=model_name.upper(), base_url='http://reg-gw:5000/v1',
                api_model='endpoint-name-of-' + model_name, api_key='sk-reg',
                max_tokens=4096, temperature=0.2, timeout=90)
    base.update(kwargs)
    return ModelRecord(**base)


def _rerank(model_name='reg-rerank', **kwargs):
    base = dict(model_id=new_model_id(), model_kind='rerank', model_name=model_name,
                display_name=model_name.upper(), base_url='http://reg-rerank:8003',
                rerank_path='/v1/rerank', is_default=True)
    base.update(kwargs)
    return ModelRecord(**base)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """每个用例一套干净的环境变量与缓存（模块级缓存会跨用例串味）。"""
    for name in list(ENV):
        monkeypatch.setenv(name, ENV[name])
    monkeypatch.delenv('RERANK_MODEL', raising=False)
    monkeypatch.delenv('RKB_RERANK_URL', raising=False)
    model_resolver.invalidate()
    yield
    model_resolver.invalidate()


def _use(monkeypatch, records=None, boom=False):
    """把注册表换成内存实现；``boom=True`` 模拟读库失败。"""
    if boom:
        def explode():
            raise RuntimeError('connection refused')

        monkeypatch.setattr(model_resolver, '_make_store', explode)
        return
    store = InMemoryModelStore(records or [])
    monkeypatch.setattr(model_resolver, '_make_store', lambda: store)
    return store


# ---------------------------------------------------------------------------
# 1. 回落
# ---------------------------------------------------------------------------
def test_empty_registry_falls_back_to_env(monkeypatch):
    _use(monkeypatch, [])

    llm = model_resolver.resolve('llm')
    assert llm.origin == 'env'
    assert llm.url == 'http://env-gw:4000/v1/chat/completions'
    assert llm.api_model == 'env-default-llm'
    assert llm.api_key == 'sk-env'
    assert (llm.max_tokens, llm.temperature, llm.timeout) == (8192, 0.01, 180)

    embedding = model_resolver.resolve('embedding')
    assert embedding.origin == 'env'
    assert embedding.url == 'https://env-embed/v1/embeddings'
    assert embedding.api_model == 'Qwen3-Embedding-0.6B'
    assert embedding.dimension == 1024


def test_unreadable_registry_falls_back_to_env_without_clearing_anything(monkeypatch):
    """读库失败 ≠ 一个模型都没有：下拉必须照旧有内容。"""
    _use(monkeypatch, boom=True)

    assert model_resolver.resolve('llm').origin == 'env'
    assert model_resolver.llm_models() == (('env-a', 'Env-A'), ('env-b', 'Env-B'))
    assert model_resolver.reasoning_models() == ('env-a',)
    # embedding_models 的 None = 说不准（调用方据此回落 kb_embedding），不是空清单
    assert model_resolver.embedding_models() is None


def test_llm_models_path_comes_from_env_when_probing(monkeypatch):
    _use(monkeypatch, [])
    assert model_resolver.resolve('llm', operation='models').url == 'http://env-gw:4000/v1/models'


def test_rerank_without_configuration_stays_empty(monkeypatch):
    """没有重排端点时必须给出空串 —— 调用方据此显式报 rerank-endpoint-not-configured。"""
    _use(monkeypatch, [])
    assert model_resolver.resolve('rerank').url == ''
    assert model_resolver.rerank_url() == ''
    assert model_resolver.rerank_model() == 'bge-reranker-large'


# ---------------------------------------------------------------------------
# 2. 注册表接管
# ---------------------------------------------------------------------------
def test_registry_row_wins_and_carries_every_field(monkeypatch):
    _use(monkeypatch, [_llm(thinking_mode='custom', thinking_payload={'chat_template_kwargs': {'thinking': False}})])

    resolved = model_resolver.resolve('llm', 'reg-llm')
    assert resolved.origin == 'registry'
    assert resolved.source == 'user', '行的来源要跟着走：抽图只给 user 行下发端点'
    assert resolved.url == 'http://reg-gw:5000/v1/chat/completions'
    assert resolved.api_model == 'endpoint-name-of-reg-llm', '发给端点的是 api_model，不是注册名'
    assert resolved.api_key == 'sk-reg'
    assert (resolved.max_tokens, resolved.temperature, resolved.timeout) == (4096, 0.2, 90)
    assert resolved.thinking_mode == 'custom'
    assert resolved.headers()['Authorization'] == 'Bearer sk-reg'


def test_lookup_accepts_either_the_registered_or_the_endpoint_name(monkeypatch):
    _use(monkeypatch, [_llm()])
    assert model_resolver.resolve('llm', 'reg-llm').origin == 'registry'
    assert model_resolver.resolve('llm', 'endpoint-name-of-reg-llm').origin == 'registry'


def test_unknown_name_falls_back_to_the_registry_default(monkeypatch):
    """UI 注册了模型、``.env`` 还留着占位名：用注册表默认行，别打 .env 的死端点。"""
    _use(monkeypatch, [_llm('aaa'), _llm('zzz', is_default=True)])

    resolved = model_resolver.resolve('llm', 'not-registered')

    assert resolved.origin == 'registry'
    assert resolved.model_name == 'zzz'
    assert resolved.url == 'http://reg-gw:5000/v1/chat/completions'
    assert resolved.api_model == 'endpoint-name-of-zzz'


def test_unknown_name_falls_back_to_env_only_when_no_row_is_enabled(monkeypatch):
    """注册表里一条启用行都没有 → 仍然回落 .env，且尊重调用方点名的模型。"""
    _use(monkeypatch, [_llm('off', enabled=False)])

    resolved = model_resolver.resolve('llm', 'not-registered')

    assert resolved.origin == 'env'
    assert resolved.source == 'env'
    assert resolved.api_model == 'not-registered'


def test_default_row_is_used_when_no_name_is_given(monkeypatch):
    _use(monkeypatch, [_llm('aaa'), _llm('zzz', is_default=True)])
    assert model_resolver.resolve('llm').model_name == 'zzz'


def test_first_enabled_row_is_used_when_nothing_is_marked_default(monkeypatch):
    _use(monkeypatch, [_llm('bbb'), _llm('aaa')])
    # store 的排序是 (kind, is_default DESC, model_name) → aaa 在前
    assert model_resolver.resolve('llm').model_name == 'aaa'


def test_disabled_rows_are_invisible(monkeypatch):
    _use(monkeypatch, [_llm('off', enabled=False)])
    assert model_resolver.resolve('llm', 'off').origin == 'env'
    assert model_resolver.llm_models() == (('env-a', 'Env-A'), ('env-b', 'Env-B'))


def test_registry_embedding_carries_the_dimension(monkeypatch):
    _use(monkeypatch, [ModelRecord(
        model_id=new_model_id(), model_kind='embedding', model_name='bge-base-zh-v1.5',
        api_model='BAAI/bge-base-zh-v1.5', base_url='http://local:8000',
        embeddings_path='/embeddings', dimension=768)])

    resolved = model_resolver.resolve('embedding', 'bge-base-zh-v1.5')
    assert resolved.url == 'http://local:8000/embeddings', '逐行覆盖的路径必须生效（契约的三种实现）'
    assert resolved.dimension == 768
    assert model_resolver.embedding_models() == ['bge-base-zh-v1.5']


def test_registry_rerank_makes_the_endpoint_appear(monkeypatch):
    _use(monkeypatch, [ModelRecord(
        model_id=new_model_id(), model_kind='rerank', model_name='bge-reranker-large',
        base_url='https://gw/v1', rerank_path='', is_default=True)])
    assert model_resolver.rerank_url() == 'https://gw/v1/rerank'
    assert model_resolver.resolve('rerank').url == 'https://gw/v1/rerank'


def test_rerank_model_options_are_empty_without_an_endpoint(monkeypatch):
    """没有端点就没有可选项 —— 与 ``rerank_url() == ''`` 同义，不能凭空列出常量。"""
    _use(monkeypatch, [])

    assert model_resolver.rerank_model_options() == []
    assert model_resolver.rerank_model_names() == ()


def test_rerank_model_options_fall_back_to_env_when_url_is_configured(monkeypatch):
    """注册表没有 rerank 行、但 ``.env`` 配了端点 → 只有 ``RERANK_MODEL`` 那一项。"""
    _use(monkeypatch, [])
    # URL 的回落来源是 RuntimeCapabilities（RKB_RERANK_URL），与 rerank_url() 同源
    monkeypatch.setenv('RKB_RERANK_URL', 'https://env-rerank/rerank')
    monkeypatch.setenv('RERANK_MODEL', 'env-reranker')

    assert model_resolver.rerank_model_options() == [
        {'value': 'env-reranker', 'label': 'env-reranker', 'isDefault': True}]
    assert model_resolver.rerank_model_names() == ('env-reranker',)


def test_rerank_model_options_expose_labels_and_the_default_row(monkeypatch):
    """下拉的 value 是**注册名**（运行期按它解析），label 是展示名，默认行打标。

    顺序跟 ``InMemoryModelStore`` / ``PgModelStore`` 的 ORDER BY 一致：
    默认行排最前，其余按注册名。
    """
    _use(monkeypatch, [
        _rerank('qwen-rerank', display_name='Qwen3-Reranker-4B', is_default=False),
        _rerank('bge-rerank', display_name='BGE Reranker', is_default=True),
        _rerank('disabled', enabled=False, is_default=False),
    ])

    assert model_resolver.rerank_model_options() == [
        {'value': 'bge-rerank', 'label': 'BGE Reranker', 'isDefault': True},
        {'value': 'qwen-rerank', 'label': 'Qwen3-Reranker-4B', 'isDefault': False},
    ]
    assert model_resolver.rerank_model_names() == ('bge-rerank', 'qwen-rerank')


# ---------------------------------------------------------------------------
# 3. 立即生效（「不停机」的技术支点）
# ---------------------------------------------------------------------------
def test_a_model_added_after_the_cache_was_filled_is_visible_immediately(monkeypatch):
    store = _use(monkeypatch, [])

    assert model_resolver.resolve('llm', 'brand-new').origin == 'env', '先填上缓存'

    store.insert(_llm('brand-new'))
    # 没有 invalidate：应仍读缓存里的旧快照（这正是缓存存在的意义）
    assert model_resolver.resolve('llm', 'brand-new').origin == 'env'

    model_resolver.invalidate()
    resolved = model_resolver.resolve('llm', 'brand-new')
    assert resolved.origin == 'registry'
    assert resolved.url == 'http://reg-gw:5000/v1/chat/completions'


def test_invalidate_makes_a_deleted_model_disappear_immediately(monkeypatch):
    store = _use(monkeypatch, [_llm('gone')])
    assert model_resolver.resolve('llm', 'gone').origin == 'registry'

    store.delete(store.list_records()[0].model_id)
    model_resolver.invalidate()
    assert model_resolver.resolve('llm', 'gone').origin == 'env'


# ---------------------------------------------------------------------------
# 4. 播种后行为不变（升级路径的核心性质）
# ---------------------------------------------------------------------------
def test_resolving_a_seeded_row_is_identical_to_the_env_fallback(monkeypatch):
    """**升级不回归**的可执行断言，端到端地表达一次：

    把 `.env` 播种进注册表之后，解析出来的（端点 / key / 模型名 / 生成参数）
    必须与「注册表读不到、纯靠 .env 回落」时**逐项相同**。差任何一项，
    升级到本功能就会静默改变运行期行为 —— 而那种改动没有报错，只有跑起来才发现。
    """
    from model.seed import build_seed_records

    def snapshot(resolved):
        return (resolved.url, resolved.api_model, resolved.api_key,
                resolved.timeout, resolved.max_tokens, resolved.temperature,
                resolved.thinking_payload)

    # 1) 注册表读不到 → 纯 .env
    _use(monkeypatch, boom=True)
    before = {kind: snapshot(model_resolver.resolve(kind)) for kind in ('llm', 'embedding')}

    # 2) 按**同一份** .env 播种 → 逐项比
    seeded = build_seed_records(dict(ENV, RKB_FLOW_LLM_MODELS='env-default-llm=Env Default LLM'))
    _use(monkeypatch, seeded)

    after = {kind: snapshot(model_resolver.resolve(kind)) for kind in ('llm', 'embedding')}

    assert after['llm'] == before['llm'], '播种后 LLM 解析结果必须与纯 .env 一致'
    assert after['embedding'][:3] == before['embedding'][:3], 'embedding 的 url/模型/key 也必须一致'


# ---------------------------------------------------------------------------
# 3. 每模型 thinking 开关：注册表行权威，全局 env 只给回落端点
# ---------------------------------------------------------------------------
def test_effective_kwargs_from_registry_true(monkeypatch):
    _use(monkeypatch, [_llm(thinking_mode='custom', thinking_payload={'chat_template_kwargs': {'thinking': False}})])
    endpoint = model_resolver.resolve('llm', 'reg-llm')

    assert model_resolver.effective_generation_overrides(endpoint) == {
        'chat_template_kwargs': {'thinking': False}}


def test_registry_false_suppresses_the_global_env(monkeypatch):
    """行内 false = 明确不关；不能被部署级变量重新打开。"""
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": true}')
    _use(monkeypatch, [_llm(thinking_mode='none')])

    endpoint = model_resolver.resolve('llm', 'reg-llm')
    assert endpoint.thinking_mode == 'none'
    assert model_resolver.effective_generation_overrides(endpoint) is None


def test_env_fallback_still_honors_the_global_switch(monkeypatch):
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": false}')
    _use(monkeypatch, [])

    endpoint = model_resolver.resolve('llm')
    assert endpoint.origin == 'env'
    assert model_resolver.effective_generation_overrides(endpoint) == {
        'chat_template_kwargs': {'thinking': False}}


def test_invalid_global_switch_is_ignored(monkeypatch):
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{not-json')
    _use(monkeypatch, [])

    assert model_resolver.effective_generation_overrides(
        model_resolver.resolve('llm')) is None


def test_registry_auto_resolves_catalog_payload(monkeypatch):
    _use(monkeypatch, [_llm('deepseek-chat', thinking_mode='auto')])
    endpoint = model_resolver.resolve('llm', 'deepseek-chat')

    assert endpoint.thinking_mode == 'auto'
    assert endpoint.thinking_payload == {'chat_template_kwargs': {'thinking': False}}
    assert model_resolver.effective_generation_overrides(endpoint) == {
        'chat_template_kwargs': {'thinking': False}}


def test_registry_preset_and_custom_payloads(monkeypatch):
    _use(monkeypatch, [
        _llm('preset-llm', thinking_mode='preset', thinking_preset='qwen-vllm'),
        _llm('custom-llm', thinking_mode='custom',
             thinking_payload={'reasoning_effort': 'minimal'}),
    ])

    preset_endpoint = model_resolver.resolve('llm', 'preset-llm')
    custom_endpoint = model_resolver.resolve('llm', 'custom-llm')

    assert preset_endpoint.thinking_payload == {
        'chat_template_kwargs': {'enable_thinking': False}}
    assert custom_endpoint.thinking_payload == {'reasoning_effort': 'minimal'}


def test_registry_auto_unknown_sends_nothing(monkeypatch):
    _use(monkeypatch, [_llm('private-model', thinking_mode='auto')])
    endpoint = model_resolver.resolve('llm', 'private-model')

    assert endpoint.thinking_payload is None
    assert model_resolver.effective_generation_overrides(endpoint) is None


def test_aux_profile_forces_off_for_registry_model_with_no_answer_config(monkeypatch):
    _use(monkeypatch, [_llm('deepseek-chat', thinking_mode='none')])

    answer = model_resolver.resolve('llm', 'deepseek-chat')
    auxiliary = model_resolver.resolve(
        'llm', 'deepseek-chat', thinking_profile='aux')

    assert answer.thinking_payload is None
    assert auxiliary.thinking_payload == {'chat_template_kwargs': {'thinking': False}}


def test_aux_profile_ignores_registry_preset_and_custom(monkeypatch):
    """辅助调用不读取模型行：回答侧的高推理/别的预置不能漏到改写、重排、路由。"""
    _use(monkeypatch, [
        _llm('deepseek-chat', thinking_mode='custom',
             thinking_payload={'reasoning_effort': 'high'}),
        _llm('preset-llm', thinking_mode='preset', thinking_preset='qwen-vllm'),
        _llm('private-model', thinking_mode='custom',
             thinking_payload={'reasoning_effort': 'high'}),
    ])

    deepseek = model_resolver.resolve(
        'llm', 'deepseek-chat', thinking_profile='aux')
    preset = model_resolver.resolve(
        'llm', 'preset-llm', thinking_profile='aux')
    private = model_resolver.resolve(
        'llm', 'private-model', thinking_profile='aux')

    # 行里 custom=high，aux 仍按模型名匹配到 DeepSeek 的关闭写法
    assert deepseek.thinking_payload == {'chat_template_kwargs': {'thinking': False}}
    # 行里 preset=Qwen，但 aux 仍按模型名（preset-llm）匹配，未命中就不发
    assert preset.thinking_payload is None
    # 目录未覆盖的模型：不因为行里 custom 就把 high 发给辅助调用
    assert private.thinking_payload is None


def test_env_fallback_wraps_the_global_value(monkeypatch):
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"enable_thinking": false}')
    _use(monkeypatch, [])

    endpoint = model_resolver.resolve('llm')
    assert endpoint.thinking_payload == {
        'chat_template_kwargs': {'enable_thinking': False}}
    assert model_resolver.effective_generation_overrides(endpoint) == {
        'chat_template_kwargs': {'enable_thinking': False}}


# ---------------------------------------------------------------------------
# 4. llm_routes：模型清单校验用的派生值
# ---------------------------------------------------------------------------
def test_llm_routes_maps_registration_name_to_api_model_on_the_gateway(monkeypatch):
    """注册名 ≠ api_model、且都在部署生成端点上：校验要按 api_model 比。"""
    _use(monkeypatch, [_llm(model_name='flash-alias', api_model='deepseek-chat',
                            base_url=ENV['GENERATION_GATEWAY_URL'])])

    api_models, self_hosted = model_resolver.llm_routes()

    assert api_models['flash-alias'] == 'deepseek-chat'
    assert api_models['deepseek-chat'] == 'deepseek-chat'
    assert self_hosted == frozenset()


def test_llm_routes_marks_models_with_their_own_endpoint_as_self_hosted(monkeypatch):
    """自带端点（≠ 部署生成端点）的行：探测清单对它没有判据，校验必须跳过。"""
    _use(monkeypatch, [_llm(
        model_name='deepseek-chat-1', api_model='deepseek-chat',
        base_url='http://10.0.0.50:30804/codebase-deepseek-chat-0731/v1/v1')])

    api_models, self_hosted = model_resolver.llm_routes()

    assert api_models['deepseek-chat-1'] == 'deepseek-chat'
    assert {'deepseek-chat-1', 'deepseek-chat'} <= self_hosted


def test_llm_routes_first_enabled_row_wins_like_pick(monkeypatch):
    """同名 key 以行序第一条启用的行为准（与 ``_pick`` 同义），后面的行不覆盖。"""
    _use(monkeypatch, [
        _llm(model_name='deepseek-chat', api_model='deepseek-chat',
             base_url=ENV['GENERATION_GATEWAY_URL']),
        _llm(model_name='flash-candidate', api_model='deepseek-chat',
             base_url='http://other-gw:5000/v1'),
    ])

    api_models, self_hosted = model_resolver.llm_routes()

    assert api_models['deepseek-chat'] == 'deepseek-chat'
    assert 'deepseek-chat' not in self_hosted      # 首条命中部署网关行
    assert 'flash-candidate' in self_hosted


def test_llm_routes_falls_back_when_registry_unreadable(monkeypatch):
    _use(monkeypatch, boom=True)
    assert model_resolver.llm_routes() == ({}, frozenset())


# ---------------------------------------------------------------------------
# 4. 向量模型清单（画布校验用）
# ---------------------------------------------------------------------------
def _embedding(model_name='reg-embed', **kwargs):
    base = dict(model_id=new_model_id(), model_kind='embedding', model_name=model_name,
                display_name=model_name.upper(), base_url='http://reg-embed:8001/v1',
                api_model='endpoint-name-of-' + model_name, embeddings_path='/embeddings',
                dimension=1024, is_default=True)
    base.update(kwargs)
    return ModelRecord(**base)


def test_embedding_model_names_include_registration_and_endpoint_names(monkeypatch):
    """注册名与 api_model 都认 —— 与 ``_pick`` 的匹配口径一致。"""
    _use(monkeypatch, [_embedding()])

    names = model_resolver.embedding_model_names()

    assert 'reg-embed' in names
    assert 'endpoint-name-of-reg-embed' in names


def test_embedding_model_names_include_the_env_fallback(monkeypatch):
    """未命中注册表的名字会回落 ``.env`` 端点，所以 ``.env`` 那个模型名同样可用。"""
    _use(monkeypatch, [_embedding()])

    assert 'Qwen3-Embedding-0.6B' in model_resolver.embedding_model_names()


def test_embedding_model_names_are_empty_when_the_registry_is_unreadable(monkeypatch):
    """读不到注册表 = 无法判定（空元组），校验据此放行，而不是把所有模型判死。"""
    _use(monkeypatch, boom=True)

    assert model_resolver.embedding_model_names() == ()


def test_unknown_embedding_name_warns_with_the_fallback_endpoint(monkeypatch, caplog):
    """C：embedding 未命中注册表时必须是**警告**，且写明回落到了哪个地址。"""
    _use(monkeypatch, [_embedding()])

    with caplog.at_level('WARNING'):
        resolved = model_resolver.resolve('embedding', 'no-such-model')

    assert resolved.origin == 'env'
    message = ' '.join(record.getMessage() for record in caplog.records)
    assert 'no-such-model' in message
    assert 'https://env-embed/v1/embeddings' in message


def test_embedding_model_dimensions_cover_registry_rows_and_the_env_fallback(monkeypatch):
    """维度判据与名字判据同源：注册名、api_model、``.env`` 默认名都要有维度。"""
    _use(monkeypatch, [_embedding(dimension=1024)])

    dimensions = model_resolver.embedding_model_dimensions()

    # 键一律小写：校验侧拿画布上的名字 .lower() 查
    assert dimensions['reg-embed'] == 1024
    assert dimensions['endpoint-name-of-reg-embed'] == 1024
    # .env 的 EMBEDDING_DIMENSION=1024
    assert dimensions['qwen3-embedding-0.6b'] == 1024


def test_embedding_model_dimensions_skip_rows_without_a_dimension(monkeypatch):
    """没填 dimension 的行不能被当成「维度为 0」—— 宁可不出现在判据里。"""
    _use(monkeypatch, [_embedding(dimension=None)])

    dimensions = model_resolver.embedding_model_dimensions()

    assert 'reg-embed' not in dimensions
    assert 'endpoint-name-of-reg-embed' not in dimensions
    assert dimensions.get('qwen3-embedding-0.6b') == 1024


def test_embedding_model_dimensions_are_empty_when_the_registry_is_unreadable(monkeypatch):
    _use(monkeypatch, boom=True)

    assert model_resolver.embedding_model_dimensions() == {}


# ---------------------------------------------------------------------------
# 5. 建库/建图的写入判据
# ---------------------------------------------------------------------------
def test_is_writable_embedding_model_accepts_registry_rows_with_a_dimension(monkeypatch):
    _use(monkeypatch, [_embedding(dimension=1024)])

    assert model_resolver.is_writable_embedding_model('reg-embed') is True
    assert model_resolver.is_writable_embedding_model('endpoint-name-of-reg-embed') is True
    assert model_resolver.is_writable_embedding_model('no-such-model') is False


def test_is_writable_embedding_model_rejects_rows_without_a_dimension(monkeypatch):
    """没维度的行在写路径上会被**静默换成** .env 默认模型 —— 记录与向量就分家了。"""
    _use(monkeypatch, [_embedding(dimension=None)])

    assert model_resolver.is_writable_embedding_model('reg-embed') is False
    # .env 那个名字仍然可写（回落路径确实用它）
    assert model_resolver.is_writable_embedding_model('Qwen3-Embedding-0.6B') is True


def test_is_writable_embedding_model_is_unjudgeable_without_any_configuration(monkeypatch):
    _use(monkeypatch, [])
    monkeypatch.delenv('EMBEDDING_MODEL', raising=False)
    monkeypatch.delenv('EMBEDDING_MODEL_NAME', raising=False)

    assert model_resolver.embedding_model_dimensions() == {}
    assert model_resolver.is_writable_embedding_model('whatever') is None


def test_is_writable_embedding_model_is_unjudgeable_when_the_registry_is_unreadable(monkeypatch):
    _use(monkeypatch, boom=True)

    assert model_resolver.is_writable_embedding_model('whatever') is None
