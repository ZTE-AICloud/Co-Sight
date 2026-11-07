"""app.py 的错误分支：入参校验（`_check_rag_request`）与 `RagException` → problem+json。

**不启动 uvicorn、也不用 TestClient**（容器镜像里没有 httpx —— 测试依赖必须和
部署镜像的 requirements 对齐）：直接调 FastAPI 注册的 `chat` 视图函数，
`Request` 用最小 ASGI scope 手搓。

钉住三件事：
  * `question_length_limit` 的三条校验：非 int / 超界 → `parameter_length_limit_illegal`；
    限制值小于问题长度 → `question_length_over_limit`（参数里带 limit 与实际长度）；
  * `RagException` → 真实状态码 + RFC 9457 problem，`detail` 走 i18n 且随
    `language-option` 头变化；
  * 非 RagException → 500 `internal_error`（不泄露堆栈）。
"""
import json

import pytest


import chat.app as app_module
from engine.common import const
from engine.common.beans.rag_request import RagRequest
from engine.common.exception.rag_exception import RagException
from starlette.requests import Request


def _request(language=None):
    headers = [(b'host', b'testserver')]
    if language is not None:
        headers.append((b'language-option', language.encode()))
    scope = {'type': 'http', 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
             'path': '/query', 'raw_path': b'/query', 'query_string': b'',
             'headers': headers, 'server': ('testserver', 80), 'client': ('127.0.0.1', 1234)}
    return Request(scope)


def _rag_request(**kwargs):
    payload = {'question': '问题', 'conversation_id': 'd-app-1'}
    payload.update(kwargs)
    return RagRequest(**payload)


# ---------------------------------------------------------------------------
# _check_rag_request：必填字段
# ---------------------------------------------------------------------------

def test_missing_question_raises_with_original_error_shape():
    with pytest.raises(RagException) as excinfo:
        app_module._check_rag_request(_rag_request(question=''))

    assert excinfo.value.get_error_code() == -1
    assert excinfo.value.get_error_tag() == 'required_param_missing'
    assert excinfo.value.get_args() == ('question',)


def test_missing_conversation_id_raises_with_original_error_shape():
    with pytest.raises(RagException) as excinfo:
        app_module._check_rag_request(_rag_request(conversation_id=''))

    assert excinfo.value.get_error_tag() == 'required_param_missing'
    assert excinfo.value.get_args() == ('conversation_id',)


# ---------------------------------------------------------------------------
# _check_rag_request：question_length_limit 三条校验
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad_limit', [
    '100',                        # 字符串：不是 int
    0,                            # 必须 > 0
    -1,
    2.5,                          # float 不算 int
    None,                         # 显式传 null
    const.question_max_length,    # 必须**小于**上限（取到上限本身不合法）
    const.question_max_length + 1,
])
def test_illegal_question_length_limit_values(bad_limit):
    with pytest.raises(RagException) as excinfo:
        app_module._check_rag_request(
            _rag_request(kwargs={const.question_length_limit: bad_limit}))

    assert excinfo.value.get_error_code() == -1
    assert excinfo.value.get_error_tag() == 'parameter_length_limit_illegal'
    assert excinfo.value.get_args() == (const.question_length_limit, const.question_max_length)


def test_question_longer_than_limit_raises_over_limit():
    with pytest.raises(RagException) as excinfo:
        app_module._check_rag_request(
            _rag_request(question='abcdef', kwargs={const.question_length_limit: 5}))

    assert excinfo.value.get_error_tag() == 'question_length_over_limit'
    assert excinfo.value.get_args() == (5, 6)  # (限制值, 实际长度)


def test_question_exactly_at_limit_is_allowed():
    """边界：limit == len(question) 合法（判定是 `limit < len` 才报错）。"""
    app_module._check_rag_request(
        _rag_request(question='abc', kwargs={const.question_length_limit: 3}))


def test_absent_question_length_limit_is_allowed():
    app_module._check_rag_request(_rag_request(question='任意长度的问题'))


# ---------------------------------------------------------------------------
# RagException → JSON 映射（含语言）
# ---------------------------------------------------------------------------

def _call_chat(monkeypatch, exc, language=None, **request_kwargs):
    def _boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(app_module.rag, 'build_query_engine', _boom)
    return app_module.chat(_rag_request(**request_kwargs), _request(language))


def test_rag_exception_maps_to_business_code_and_chinese_message(monkeypatch):
    response = _call_chat(monkeypatch, RagException(-2, 'bad-status-code', '知识库服务'),
                          language='zh')

    body = json.loads(response.body)
    assert response.status_code == 502
    assert body['code'] == 'upstream_unavailable'
    assert body['detail'] == '请求知识库服务失败，请稍后重试。'


def test_error_message_follows_language_option_header(monkeypatch):
    response = _call_chat(monkeypatch, RagException(-2, 'bad-status-code', '知识库服务'),
                          language='en')

    body = json.loads(response.body)
    assert body['code'] == 'upstream_unavailable'
    assert body['detail'] == 'Request service 知识库服务 failed, please try again.'


def test_error_message_defaults_to_chinese_without_language_header(monkeypatch):
    response = _call_chat(monkeypatch, RagException(-1, 'no-llm-available'))

    body = json.loads(response.body)
    assert response.status_code == 503
    assert body['code'] == 'no_llm_available'
    assert body['detail'] == '当前环境上无可用大模型，请注册大模型。'


def test_unknown_exception_maps_to_generic_error_without_leaking(monkeypatch):
    response = _call_chat(monkeypatch, RuntimeError('internal stack detail'))

    body = json.loads(response.body)
    assert response.status_code == 500
    assert body['code'] == 'internal_error'
    assert body['detail'] == '服务器内部错误，请稍后重试'
    assert 'internal stack detail' not in response.body.decode('utf-8')


def test_validation_short_circuits_before_engine_is_built(monkeypatch):
    """入参校验发生在 build_query_engine 之前：没有 question 时不应触碰下游服务。"""
    def _must_not_be_called(*args, **kwargs):
        raise AssertionError('build_query_engine must not be called for invalid requests')

    monkeypatch.setattr(app_module.rag, 'build_query_engine', _must_not_be_called)
    response = app_module.chat(_rag_request(question=''), _request())

    body = json.loads(response.body)
    assert response.status_code == 422
    assert body['code'] == 'validation_failed'
    assert body['detail'] == '参数非法：question，不能为空或null。'


# 健康检查只有唯一端点 `<prefix>/health`，由 kb_api 提供。
