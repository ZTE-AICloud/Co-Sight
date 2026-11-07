"""抽图算子的模型调用：显式端点（``llmConfig``）与确定性失败的快速失败。

背景：模型管理页可以给注册模型配独立 ``base_url``（注册名 ``deepseek-chat-1`` →
``api_model=deepseek-chat``）。抽图链路若把**注册名**打到
``MODEL_GATEWAY_URL``，404 后会重试多轮才落库「生成失败」，而真因只是一句 404。

这里钉住两件事：

1. 给了 ``endpoint`` 就按它的 url / 真实模型名 / 鉴权 / 思考片段发；**没给则固定
   走 ``MODEL_GATEWAY_*`` 环境变量决定的端点**（见 ``model/operator_client.py`` 的模块注释）。
2. 4xx（除 408/429）**不重试**，立即上抛，消息里带模型名与地址。

跑法（服务目录下）::

    python -m pytest tests/test_operator_client_endpoint.py -q
"""

import pytest

from infrastructure.http import egress
from model import operator_client


class _Response:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload if payload is not None else {
            'choices': [{'message': {'content': 'ok'}}]}
        self.text = text

    def json(self):
        return self._payload


def _capture_post(monkeypatch, responses):
    """按顺序返回预置响应；记录每次调用的 (url, body, headers, timeout)。"""
    calls = []
    queue = list(responses)

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({'url': url, 'body': json, 'headers': headers, 'timeout': timeout})
        return queue.pop(0) if queue else _Response(200)

    monkeypatch.setattr(egress, 'post', fake_post)
    return calls


def test_endpoint_overrides_url_model_and_auth(monkeypatch):
    """``llmConfig`` 里的地址与 ``api_model`` 必须覆盖环境变量与注册名。"""
    calls = _capture_post(monkeypatch, [_Response(200)])

    content = operator_client.invoke_llm(
        [{'role': 'user', 'content': 'hi'}],
        model='deepseek-chat-1',
        endpoint={
            'url': 'http://10.0.0.50:30804/codebase-deepseek-chat-0731/v1/v1/chat/completions',
            'model': 'deepseek-chat',
            'api_key': 'sk-candidate',
            'timeout': 120,
        })

    assert content == 'ok'
    assert len(calls) == 1
    call = calls[0]
    assert call['url'] == ('http://10.0.0.50:30804/codebase-deepseek-chat-0731'
                           '/v1/v1/chat/completions')
    assert call['body']['model'] == 'deepseek-chat'
    assert call['headers']['Authorization'] == 'Bearer sk-candidate'
    assert call['timeout'] == 120


def test_endpoint_thinking_payload_is_merged_into_body(monkeypatch):
    """注册表行的思考片段以它为准（抽图必须能关掉思考）。"""
    calls = _capture_post(monkeypatch, [_Response(200)])

    operator_client.invoke_llm(
        [{'role': 'user', 'content': 'hi'}], model='m',
        endpoint={'url': 'http://10.0.0.1/v1/chat/completions', 'model': 'api-m',
                  'thinking_payload': {'chat_template_kwargs': {'enable_thinking': False}}})

    assert calls[0]['body']['chat_template_kwargs'] == {'enable_thinking': False}


def test_without_endpoint_the_env_gateway_is_untouched(monkeypatch):
    """不给 ``endpoint``（``.env`` 播种的模型 / 老算子）→ 固定走部署网关。"""
    calls = _capture_post(monkeypatch, [_Response(200)])

    operator_client.invoke_llm([{'role': 'user', 'content': 'hi'}], model='deepseek-chat')

    expected = f'{operator_client.MODEL_GATEWAY_URL}{operator_client.MODEL_GATEWAY_CHAT_PATH}'
    assert calls[0]['url'] == expected
    assert calls[0]['body']['model'] == 'deepseek-chat'
    # 原路径连 headers 都不改（``_request`` 自己补 Content-Type），别在这里加鉴权头。
    assert calls[0]['headers'] is None
    assert calls[0]['timeout'] == 1800


def test_404_is_not_retried(monkeypatch):
    """确定性失败（模型名不存在）→ 只调一次，消息里带状态码、模型名与地址。"""
    calls = _capture_post(monkeypatch, [_Response(404, text='model not found')])

    with pytest.raises(RuntimeError) as error:
        operator_client.invoke_llm(
            [{'role': 'user', 'content': 'hi'}], model='deepseek-chat-1',
            endpoint={'url': 'https://llm.example.com/v1/chat/completions',
                      'model': 'deepseek-chat-1'})

    assert len(calls) == 1
    message = str(error.value)
    assert '404' in message
    assert 'deepseek-chat-1' in message
    assert 'https://llm.example.com/v1/chat/completions' in message


@pytest.mark.parametrize('status', [429, 500, 503])
def test_transient_errors_are_still_retried(monkeypatch, status):
    """限流/服务端错误仍是暂时性的：重试到成功，别把重试机制一起删掉。"""
    monkeypatch.setattr(operator_client.time, 'sleep', lambda _seconds: None)
    calls = _capture_post(monkeypatch, [_Response(status), _Response(200)])

    content = operator_client.invoke_llm([{'role': 'user', 'content': 'hi'}], model='m')

    assert content == 'ok'
    assert len(calls) == 2
