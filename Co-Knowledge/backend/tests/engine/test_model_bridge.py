"""编排侧的端点来源：**注册表驱动运行期**，并用 ``.env`` 兜住导入不到注册表的情形。

这是本次改造里「不停机换模型」在编排一侧的落点，钉三件事：

1. 注册表可用时，``model_bridge`` 解析出来的端点/模型名**真的来自注册表**
   （画布选中的模型名 → 对应端点，不是永远打 ``GENERATION_GATEWAY_URL``）；
2. 注册表不可用（只加载 ``engine`` 依赖时，见
   ``tests/test_config_adjudications.py`` 的子进程探针）→ **回落 Config**，
   也就是默认行为；
3. 回落端点的**形状**与注册表端点的形状一致（调用方不需要分叉）。

跑法::

    python -m pytest backend/tests/engine/test_model_bridge.py -q
"""

import sys
from pathlib import Path

import pytest

# 本文件在 ``backend/tests/engine/`` 下，``parents[2]`` 是服务根（``backend/``），
# 下面才是 import 根 ``src/``。
SRC_DIR = Path(__file__).resolve().parents[2] / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from model.models import ModelRecord, new_model_id  # noqa: E402
from model.repository import InMemoryModelStore  # noqa: E402
from model import resolver as model_resolver  # noqa: E402
from engine.settings import Config  # noqa: E402
from engine.gateways import model_bridge  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setenv('GENERATION_GATEWAY_URL', 'http://env-gw:4000/v1')
    monkeypatch.setenv('GENERATION_MODEL', 'env-default')
    monkeypatch.setenv('GENERATION_API_KEY', 'sk-env')
    monkeypatch.delenv('RERANK_URL', raising=False)
    monkeypatch.delenv('RERANK_MODEL', raising=False)
    monkeypatch.delenv('GENERATION_CHAT_TEMPLATE_KWARGS', raising=False)
    model_resolver.invalidate()
    yield
    model_resolver.invalidate()


def _use_registry(monkeypatch, records):
    store = InMemoryModelStore(records)
    monkeypatch.setattr(model_resolver, '_make_store', lambda: store)
    monkeypatch.setattr(model_bridge, 'REGISTRY_AVAILABLE', True)
    return store


def _llm(model_name, **kwargs):
    base = dict(model_id=new_model_id(), model_kind='llm', model_name=model_name,
                api_model='served-as-' + model_name, base_url='http://reg-gw:5000/v1',
                api_key='sk-reg', max_tokens=4096, temperature=0.2, timeout=90,
                is_default=kwargs.pop('is_default', False))
    base.update(kwargs)
    return ModelRecord(**base)


def test_registry_supplies_the_endpoint_and_the_served_model_name(monkeypatch):
    _use_registry(monkeypatch, [_llm('canvas-model', thinking_mode='custom',
                                      thinking_payload={'chat_template_kwargs': {'thinking': False}})])

    endpoint = model_bridge.resolve_llm('canvas-model')
    assert endpoint.url == 'http://reg-gw:5000/v1/chat/completions'
    assert endpoint.api_model == 'served-as-canvas-model'
    assert endpoint.api_key == 'sk-reg'
    assert endpoint.headers()['Authorization'] == 'Bearer sk-reg'
    assert (endpoint.max_tokens, endpoint.temperature, endpoint.timeout) == (4096, 0.2, 90)
    assert endpoint.thinking_mode == 'custom'
    assert model_bridge.effective_generation_overrides(endpoint) == {
        'chat_template_kwargs': {'thinking': False}}


def test_a_model_registered_later_is_usable_without_restarting(monkeypatch):
    """同进程内：加一行 → 失效缓存 → 立刻解析得到（就是「不停机」那句主张）。"""
    store = _use_registry(monkeypatch, [])
    assert model_bridge.resolve_llm('brand-new').url == 'http://env-gw:4000/v1/chat/completions'

    store.insert(_llm('brand-new'))
    model_resolver.invalidate()

    assert model_bridge.resolve_llm('brand-new').url == 'http://reg-gw:5000/v1/chat/completions'


def test_default_llm_model_follows_the_registry(monkeypatch):
    _use_registry(monkeypatch, [_llm('reg-default', is_default=True), _llm('zzz')])
    assert model_bridge.default_llm_model() == 'served-as-reg-default'


def test_registry_rerank_endpoint_replaces_the_env_one(monkeypatch):
    _use_registry(monkeypatch, [ModelRecord(
        model_id=new_model_id(), model_kind='rerank', model_name='my-reranker',
        api_model='bge-reranker-large', base_url='https://reg-rerank/v1',
        is_default=True)])
    monkeypatch.setenv('RERANK_URL', 'https://env-rerank/rerank')

    endpoint = model_bridge.resolve_rerank('my-reranker')
    assert endpoint.url == 'https://reg-rerank/v1/rerank'
    assert model_bridge.rerank_model_name() == 'bge-reranker-large'


def test_no_rerank_anywhere_still_yields_an_empty_url(monkeypatch):
    """空 URL 是「本部署没有重排能力」的信号，调用方据此显式抛错 —— 不能被填成默认值。"""
    _use_registry(monkeypatch, [])
    assert model_bridge.resolve_rerank('bge-reranker-large').url == ''
    assert model_bridge.rerank_model_name() == 'bge-reranker-large'


# ---------------------------------------------------------------------------
# 回落（engine/ 被单独导入时）
# ---------------------------------------------------------------------------
def test_without_the_registry_layer_it_falls_back_to_config(monkeypatch):
    """回落读的是 ``engine.settings.Config``（import 期快照）。

    ⚠️ 所以这里打的是 **Config**、不是环境变量 —— 快照在 import 时就定格了，
    运行期改 env 它看不见。这个「改了不生效」正是注册表路线要解决的问题：
    注册表由解析层**按调用**读取并缓存、写后失效，画布换了模型不用重启。
    """
    monkeypatch.setattr(model_bridge, 'REGISTRY_AVAILABLE', False)
    monkeypatch.setitem(Config, 'generation_base_url', 'http://env-gw:4000/v1')
    monkeypatch.setitem(Config, 'generation_model', 'env-default')
    monkeypatch.setitem(Config, 'generation_api_key', 'sk-env')

    endpoint = model_bridge.resolve_llm('canvas-model')
    assert endpoint.url == 'http://env-gw:4000/v1/chat/completions'
    assert endpoint.api_model == 'canvas-model', '回落时仍尊重调用方点名的模型'
    assert endpoint.api_key == 'sk-env'
    assert endpoint.origin == 'env'


def test_fallback_endpoint_has_the_same_shape_as_the_registry_one(monkeypatch):
    """形状一致 —— 调用方（`openai_llm`）不需要为两条来源分叉。"""
    _use_registry(monkeypatch, [_llm('m')])
    from_registry = model_bridge.resolve_llm('m')
    monkeypatch.setattr(model_bridge, 'REGISTRY_AVAILABLE', False)
    from_config = model_bridge.resolve_llm('m')

    for attribute in ('url', 'api_model', 'api_key', 'timeout', 'max_tokens',
                      'temperature', 'thinking_payload', 'origin'):
        assert hasattr(from_config, attribute), attribute
        assert hasattr(from_registry, attribute), attribute
    assert from_config.headers()['Content-Type'] == from_registry.headers()['Content-Type']


def test_fallback_rerank_uses_the_config_url(monkeypatch):
    monkeypatch.setattr(model_bridge, 'REGISTRY_AVAILABLE', False)
    monkeypatch.setitem(Config, 'rerank_url', 'https://env-rerank/rerank')

    assert model_bridge.resolve_rerank('bge').url == 'https://env-rerank/rerank'


def test_standalone_fallback_parses_the_global_thinking_switch(monkeypatch):
    """注册表层导入不到时，env 解析仍要工作（这份重复是刻意的）。"""
    monkeypatch.setattr(model_bridge, 'REGISTRY_AVAILABLE', False)
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": false}')

    endpoint = model_bridge.resolve_llm('canvas-model')
    assert model_bridge.effective_generation_overrides(endpoint) == {
        'chat_template_kwargs': {'thinking': False}}


def test_bridge_exposes_registry_generic_overrides(monkeypatch):
    _use_registry(monkeypatch, [_llm('deepseek-chat', thinking_mode='auto')])

    endpoint = model_bridge.resolve_llm('deepseek-chat')
    assert model_bridge.effective_generation_overrides(endpoint) == {
        'chat_template_kwargs': {'thinking': False}}


def test_standalone_fallback_ignores_invalid_global_switch(monkeypatch):
    monkeypatch.setattr(model_bridge, 'REGISTRY_AVAILABLE', False)
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{not-json')

    endpoint = model_bridge.resolve_llm('canvas-model')
    assert model_bridge.effective_generation_overrides(endpoint) is None
