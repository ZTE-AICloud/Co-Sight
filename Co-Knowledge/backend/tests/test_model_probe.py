"""生成端点「可用模型」探测的单测（不碰网络：HTTP 由构造参数注入）。

重点钉住两件事：

1. **失败一律返回 ``None``，绝不抛错**。这个返回值接的是 publish 的硬门槛，
   抛错或误判会把用户挡在发布之外 —— 比漏判严重。
2. **失败不写缓存**。否则一次网络抖动会持续影响一整个 TTL。
"""

import pytest
import requests

from model.probe import (
    CACHE_TTL_SECONDS,
    DEFAULT_MODELS_PATH,
    ModelProbe,
    probe_available_models,
)

GATEWAY = 'http://gen.local:4000/v1'


class FakeResponse:
    def __init__(self, status_code=200, payload=None, invalid_json=False):
        self.status_code = status_code
        self._payload = payload
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError('Expecting value: line 1 column 1 (char 0)')
        return self._payload


def make_get(response=None, error=None, recorder=None):
    """造一个假的 ``requests.get``（记录最后一次调用参数）。"""
    calls = recorder if recorder is not None else []

    def _get(url, headers=None, timeout=None):
        calls.append({'url': url, 'headers': dict(headers or {}), 'timeout': timeout})
        if error is not None:
            raise error
        return response

    _get.calls = calls
    return _get


def openai_models(*ids):
    return {'object': 'list', 'data': [{'id': i, 'object': 'model'} for i in ids]}


# ----------------------------------------------------------------------
# 正常路径
# ----------------------------------------------------------------------

def test_returns_model_ids_from_openai_shaped_payload():
    http_get = make_get(FakeResponse(payload=openai_models('deepseek-chat', 'qwen3-32b')))
    result = probe_available_models(GATEWAY, 'secret', http_get=http_get)
    assert result == frozenset({'deepseek-chat', 'qwen3-32b'})


def test_tolerates_plain_string_data():
    """少数实现直接给字符串数组。"""
    http_get = make_get(FakeResponse(payload={'data': ['a', 'b']}))
    assert probe_available_models(GATEWAY, http_get=http_get) == frozenset({'a', 'b'})


def test_joins_url_without_doubling_or_dropping_slash():
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    # base 带尾斜杠 + path 不带前导斜杠 → 任一种写法都拼成同一个 URL
    probe_available_models('http://gen.local:4000/v1/', 'k', 'models', http_get=http_get)
    assert http_get.calls[-1]['url'] == 'http://gen.local:4000/v1/models'


def test_path_is_configurable_because_implementations_differ():
    """Infinity 的 base 不带 /v1，LiteLLM 的带 —— 路径必须可配（实测两种都碰到过）。"""
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    probe_available_models('http://model-gateway:8000', 'k', '/models', http_get=http_get)
    assert http_get.calls[-1]['url'] == 'http://model-gateway:8000/models'
    # 缺省路径
    probe_available_models(GATEWAY, 'k', http_get=http_get)
    assert http_get.calls[-1]['url'] == GATEWAY + DEFAULT_MODELS_PATH


def test_sends_bearer_only_when_key_present():
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    probe_available_models(GATEWAY, 'secret', http_get=http_get)
    assert http_get.calls[-1]['headers'].get('Authorization') == 'Bearer secret'

    probe_available_models(GATEWAY, '', http_get=http_get)
    assert 'Authorization' not in http_get.calls[-1]['headers']


# ----------------------------------------------------------------------
# 失败路径：全部返回 None，一个都不许抛
# ----------------------------------------------------------------------

@pytest.mark.parametrize('response', [
    FakeResponse(status_code=401, payload={'error': {'message': 'No api key passed in.'}}),
    FakeResponse(status_code=404),
    FakeResponse(status_code=500),
    FakeResponse(status_code=200, invalid_json=True),
    FakeResponse(status_code=200, payload={'data': 'not-a-list'}),
    FakeResponse(status_code=200, payload={'nope': []}),
    FakeResponse(status_code=200, payload=['not', 'a', 'dict']),
])
def test_indeterminate_results_return_none(response):
    http_get = make_get(response)
    assert probe_available_models(GATEWAY, 'k', http_get=http_get) is None


@pytest.mark.parametrize('error', [
    requests.ConnectionError('connection refused'),
    requests.Timeout('read timeout'),
    RuntimeError('代理接走后返回 HTML，requests 抛的可能是别的'),
])
def test_transport_errors_return_none(error):
    http_get = make_get(error=error)
    assert probe_available_models(GATEWAY, 'k', http_get=http_get) is None


def test_empty_gateway_returns_none_without_any_call():
    """没配端点 = 本部署没有生成能力，不是「模型不可用」—— 但也不该去发请求。"""
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    assert probe_available_models('', 'k', http_get=http_get) is None
    assert probe_available_models('   ', 'k', http_get=http_get) is None
    assert http_get.calls == []


# ----------------------------------------------------------------------
# TTL 缓存
# ----------------------------------------------------------------------

def test_reuses_result_within_ttl_and_refreshes_after():
    now = [1000.0]
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    probe = ModelProbe(GATEWAY, 'k', ttl=60, clock=lambda: now[0], http_get=http_get)

    assert probe.available() == frozenset({'m'})
    probe.available()
    assert len(http_get.calls) == 1, 'TTL 内不该重复打端点（preCheck 是用户同步请求）'

    now[0] += CACHE_TTL_SECONDS + 1
    probe.available()
    assert len(http_get.calls) == 2, 'TTL 过期后要重新探测，否则新上线的模型永远看不见'


def test_failure_is_not_cached():
    """失败不缓存 —— 否则一次抖动会持续影响一整个 TTL。"""
    now = [1000.0]
    responses = [FakeResponse(status_code=503), FakeResponse(payload=openai_models('m'))]
    calls = []

    def http_get(url, headers=None, timeout=None):
        calls.append(url)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    probe = ModelProbe(GATEWAY, 'k', ttl=60, clock=lambda: now[0], http_get=http_get)
    assert probe.available() is None
    # TTL 内立刻重试：应当真的再打一次（而不是把 None 当结果缓存住）
    assert probe.available() == frozenset({'m'})
    assert len(calls) == 2


def test_clear_cache_forces_reprobe():
    now = [1000.0]
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    probe = ModelProbe(GATEWAY, 'k', ttl=60, clock=lambda: now[0], http_get=http_get)
    probe.available()
    probe.clear_cache()
    probe.available()
    assert len(http_get.calls) == 2


def test_probe_reads_configuration_from_injected_env():
    """env 注入只为单测 —— 生产走 os.environ。"""
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    probe = ModelProbe(env={
        'GENERATION_GATEWAY_URL': GATEWAY,
        'GENERATION_API_KEY': 'from-env',
        'GENERATION_MODELS_PATH': '/custom/models',
    }, http_get=http_get)
    probe.available()
    assert http_get.calls[-1]['url'] == GATEWAY + '/custom/models'
    assert http_get.calls[-1]['headers']['Authorization'] == 'Bearer from-env'


def test_probe_defaults_path_when_env_absent():
    http_get = make_get(FakeResponse(payload=openai_models('m')))
    probe = ModelProbe(env={'GENERATION_GATEWAY_URL': GATEWAY}, http_get=http_get)
    probe.available()
    assert http_get.calls[-1]['url'] == GATEWAY + DEFAULT_MODELS_PATH
