"""`llm_proxy_client` 的直测 —— 这是全仓风险最高的模块之一。

要钉住的是两组**策略相反**的失败处理与两条易漂移的判定：

  * `invoke_rerank_client`
      - 没配端点（`RERANK_URL` 为空）→ **抛错**。这是部署配置缺失，不是临时抖动；
        退化成「按原顺序返回」会让用户以为重排生效了（阶段1 发布环节也会拦这种画布）。
      - 配了但调用失败 / 响应形状不可用 → **退回原顺序**（可用性优先）。
      - ≤1 条候选不碰网络；score 阈值过滤（严格大于）；按分数倒序；index 越界丢弃。
  * `check_exec_result`：只有 `code == '-1'` 算失败（字符串与数字两种形态都要算）。
  * `query_rerank_model` / `invoke_query_llm_info`：Config 键缺席 / 为空时的回落
    （`rerank_model` 默认 ''，键缺席与默认值等价；环境变量接线由
    tests/test_config_adjudications.py 另钉）。

全程 monkeypatch `requests.post` 与 `config.Config`，**不打真网络**。
"""

import pytest


import engine.settings as config
from engine.common.exception.rag_exception import RagException
from engine.gateways import llm_proxy_client

RERANK_URL = 'http://rerank.test/v1/rerank'


class _FakeResponse:
    """requests.post 的最小替身。"""

    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _BrokenJsonResponse(_FakeResponse):
    """endpoint 活着但响应不是 JSON（网关错误页/HTML）。"""

    def json(self):
        raise ValueError('Expecting value: line 1 column 1 (char 0)')


def _install_fake_post(monkeypatch, response=None, error=None):
    calls = []

    def fake_post(url, json=None, timeout=None, **kwargs):
        calls.append({'url': url, 'body': json, 'timeout': timeout})
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(llm_proxy_client.egress, 'post', fake_post)
    return calls


@pytest.fixture(autouse=True)
def _rerank_endpoint_configured(monkeypatch):
    """默认部署形态：配了 rerank 端点；个别用例自己覆盖成未配置。"""
    monkeypatch.setenv('RERANK_URL', RERANK_URL)


@pytest.fixture()
def empty_registry(monkeypatch):
    """注册表为空（不是「读不到」）：让 `resolve_rerank` 走 `.env` 回落。

    用例里要断言「显式选的模型不在注册表」时必须先钉住这一点 —— 否则本机
    真有一份注册表时，结果会随环境漂移。
    """
    from model.repository import InMemoryModelStore
    from model import resolver as model_resolver

    monkeypatch.setattr(model_resolver, '_make_store',
                        lambda: InMemoryModelStore([]))
    model_resolver.invalidate()
    yield
    model_resolver.invalidate()


# ---------------------------------------------------------------------------
# invoke_rerank_client
# ---------------------------------------------------------------------------

def test_missing_endpoint_raises_and_never_calls_network(monkeypatch):
    """没配端点是**硬错误**（与「配了但失败」的静默回落相反）。"""
    monkeypatch.setenv('RERANK_URL', '')
    calls = _install_fake_post(monkeypatch, response=_FakeResponse({'results': []}))

    with pytest.raises(RagException) as excinfo:
        llm_proxy_client.invoke_rerank_client('bge-reranker-large', '问题', ['a', 'b'], 0)

    assert excinfo.value.get_error_code() == -2
    assert excinfo.value.get_error_tag() == 'rerank-endpoint-not-configured'
    assert calls == [], '没配端点还去请求网络 = 走错分支'


def test_strict_model_rejects_a_name_the_registry_does_not_serve(monkeypatch, empty_registry):
    """画布显式选了模型：注册表查不到就不能静默退到 `.env` 的另一个模型。"""
    monkeypatch.delenv('RERANK_MODEL', raising=False)
    calls = _install_fake_post(monkeypatch, response=_FakeResponse({'results': []}))

    with pytest.raises(RagException) as excinfo:
        llm_proxy_client.invoke_rerank_client(
            'Qwen3-Reranker-4B', 'q', ['a', 'b'], 0, strict_model=True)

    assert excinfo.value.get_error_code() == -2
    assert excinfo.value.get_error_tag() == 'rerank-model-not-configured'
    assert excinfo.value.get_args() == ('Qwen3-Reranker-4B',)
    assert calls == [], '模型没解析成功就不该发请求'


def test_strict_model_accepts_the_env_default_model(monkeypatch, empty_registry):
    """注册表没有行时，显式选的正好是 `.env` 的默认模型 → 正常放行。"""
    monkeypatch.setenv('RERANK_MODEL', 'Qwen3-Reranker-4B')
    calls = _install_fake_post(monkeypatch, response=_FakeResponse(
        {'results': [{'index': 0, 'relevance_score': 0.9}]}))

    out = llm_proxy_client.invoke_rerank_client(
        'Qwen3-Reranker-4B', 'q', ['a', 'b'], 0, strict_model=True)

    assert out == ['a']
    assert calls[0]['body']['model'] == 'Qwen3-Reranker-4B'


def test_default_path_keeps_the_legacy_env_fallback(monkeypatch, empty_registry):
    """没显式选模型（部署默认路径）时保持原语义：名字对不上也不报错。"""
    monkeypatch.delenv('RERANK_MODEL', raising=False)
    calls = _install_fake_post(monkeypatch, response=_FakeResponse(
        {'results': [{'index': 0, 'relevance_score': 0.9}]}))

    out = llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0)

    assert out == ['a']
    assert calls[0]['body']['model'] == 'bge-reranker-large'


def test_single_or_empty_candidates_short_circuit_without_network(monkeypatch):
    """≤1 条候选不需要重排：**先于端点检查**成立 ——
    这里把端点清空也不会报错，且不该发任何请求。"""
    monkeypatch.setenv('RERANK_URL', '')
    calls = _install_fake_post(monkeypatch)

    assert llm_proxy_client.invoke_rerank_client('bge-reranker-large', 'q', [], 0) == []
    assert llm_proxy_client.invoke_rerank_client('bge-reranker-large', 'q', ['only'], 0) == ['only']
    assert calls == []


def test_success_filters_by_threshold_sorts_and_maps_back(monkeypatch):
    payload = {'results': [
        {'index': 2, 'relevance_score': 0.1},   # 低于阈值 → 丢
        {'index': 1, 'relevance_score': 0.9},   # 最高分 → 最先
        {'index': 0, 'relevance_score': 0.5},
    ]}
    calls = _install_fake_post(monkeypatch, response=_FakeResponse(payload))

    out = llm_proxy_client.invoke_rerank_client('bge-reranker-large', 'q', ['doc0', 'doc1', 'doc2'], 0.2)

    assert out == ['doc1', 'doc0']
    assert calls[0]['url'] == RERANK_URL
    assert calls[0]['body'] == {'model': 'bge-reranker-large', 'query': 'q',
                                'documents': ['doc0', 'doc1', 'doc2']}


def test_threshold_is_strictly_greater_than(monkeypatch):
    """`s > score`（不是 >=）：与阈值打平的候选被丢弃。"""
    payload = {'results': [
        {'index': 0, 'relevance_score': 0.5},       # == 阈值 → 丢
        {'index': 1, 'relevance_score': 0.500001},  # > 阈值 → 留
    ]}
    _install_fake_post(monkeypatch, response=_FakeResponse(payload))

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['doc0', 'doc1'], 0.5) == ['doc1']


def test_all_candidates_filtered_keeps_original_order(monkeypatch):
    payload = {'results': [{'index': 0, 'relevance_score': 0.1}]}
    _install_fake_post(monkeypatch, response=_FakeResponse(payload))

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0.5) == ['a', 'b']


def test_out_of_range_index_is_dropped_not_crashed(monkeypatch):
    payload = {'results': [
        {'index': 5, 'relevance_score': 0.9},   # 越界 → 丢（不 IndexError）
        {'index': -1, 'relevance_score': 0.8},  # 负数 → 丢
        {'index': 1, 'relevance_score': 0.5},
    ]}
    _install_fake_post(monkeypatch, response=_FakeResponse(payload))

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0.2) == ['b']


def test_index_or_score_missing_is_dropped(monkeypatch):
    payload = {'results': [
        {'relevance_score': 0.9},           # 无 index → 丢
        {'index': 1},                       # 无 score → 丢
        {'index': 0, 'relevance_score': 0.5},
    ]}
    _install_fake_post(monkeypatch, response=_FakeResponse(payload))

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0.2) == ['a']


def test_accepts_openai_style_data_key(monkeypatch):
    """响应既可能是 {'results': [...]}（模型适配器形状），也可能是 {'data': [...]}。"""
    payload = {'data': [{'index': 1, 'relevance_score': 0.9}]}
    _install_fake_post(monkeypatch, response=_FakeResponse(payload))

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0.5) == ['b']


@pytest.mark.parametrize('payload', [
    {'results': 'not-a-list'},          # 形状不对
    {'message': 'oops'},                # 两个键都没有
    {'results': None},
    {'results': ['garbage']},           # 元素没有 .get → AttributeError → 回落
    {'results': []},                    # 空列表 → falsy → 落入「无可用结果」
])
def test_unusable_response_shape_falls_back_to_original_order(monkeypatch, payload):
    _install_fake_post(monkeypatch, response=_FakeResponse(payload))

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0) == ['a', 'b']


@pytest.mark.parametrize('status_code', [400, 404, 500, 502])
def test_configured_but_http_error_raises_bad_status_code(monkeypatch, status_code):
    """端点配了但 HTTP 错误：**这里不回落**，抛 bad-status-code，
    由上层（app.py 错误映射）统一变成业务错误码。"""
    _install_fake_post(monkeypatch, response=_FakeResponse({}, status_code=status_code))

    with pytest.raises(RagException) as excinfo:
        llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0)

    assert excinfo.value.get_error_code() == -2
    assert excinfo.value.get_error_tag() == 'bad-status-code'
    assert excinfo.value.get_args() == ('rerank',)


def test_non_json_body_falls_back_to_original_order(monkeypatch):
    _install_fake_post(monkeypatch, response=_BrokenJsonResponse())

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0) == ['a', 'b']


def test_network_exception_falls_back_to_original_order(monkeypatch):
    _install_fake_post(monkeypatch, error=RuntimeError('connect timeout'))

    assert llm_proxy_client.invoke_rerank_client('m', 'q', ['a', 'b'], 0) == ['a', 'b']


# ---------------------------------------------------------------------------
# check_exec_result / query_rerank_model / invoke_query_llm_info
# ---------------------------------------------------------------------------

def test_check_exec_result_passes_openai_compatible_shapes():
    """OpenAI 兼容响应没有 `code` 字段 → no-op（生成侧失败判定在 openai_llm 里）。"""
    llm_proxy_client.check_exec_result(None)
    llm_proxy_client.check_exec_result({})
    llm_proxy_client.check_exec_result({'code': '0000'})
    llm_proxy_client.check_exec_result({'code': 0})


@pytest.mark.parametrize('code', ['-1', -1])
def test_check_exec_result_fails_only_on_code_minus_one(code):
    with pytest.raises(RagException) as excinfo:
        llm_proxy_client.check_exec_result({'code': code})

    assert excinfo.value.get_error_code() == -1
    assert excinfo.value.get_error_tag() == 'request-llm-gateway-failed'


def test_rerank_model_falls_back_when_nothing_is_configured(monkeypatch):
    """两级来源都没配时恒定回落常量。

    ⚠️ 「配了什么」的读取点是 ``model_bridge`` → 解析层
    （注册表 → ``os.environ`` 实时读），所以这些用例打**环境变量**。
    生产里两个来源是同一个（compose 注入的 env），
    但只有打 env 才真的走被测代码 —— 打 ``Config`` 只是改了那个 dict。
    """
    monkeypatch.delenv('RERANK_MODEL', raising=False)
    monkeypatch.delitem(config.Config, 'rerank_model', raising=False)

    assert llm_proxy_client.query_rerank_model('user') == 'bge-reranker-large'


@pytest.mark.parametrize('configured,expected', [
    ('custom-rerank-model', 'custom-rerank-model'),  # 配了就用配置值
    ('', 'bge-reranker-large'),                      # 空串 = 未配 → 默认值
])
def test_rerank_model_prefers_configured_value(monkeypatch, configured, expected):
    monkeypatch.setenv('RERANK_MODEL', configured)

    assert llm_proxy_client.query_rerank_model('user') == expected


def test_invoke_query_llm_info_returns_the_default_model(monkeypatch):
    monkeypatch.setenv('GENERATION_MODEL', 'deepseek-chat')

    assert llm_proxy_client.invoke_query_llm_info() == 'deepseek-chat'


def test_invoke_query_llm_info_never_returns_empty_in_a_configured_deployment(monkeypatch):
    """解析层**保证**给一个非空的默认模型名。

    ``no-llm-available`` 那条分支是防御性的：生产的两个来源（注册表 / ``.env`` 的
    ``GENERATION_MODEL``）都带默认值，取不到空串 —— 这里把这个性质钉住，
    免得有人以为它会因为环境变量没配就抛错。
    """
    monkeypatch.delenv('GENERATION_MODEL', raising=False)
    monkeypatch.setitem(config.Config, 'generation_model', '')

    assert llm_proxy_client.invoke_query_llm_info()
