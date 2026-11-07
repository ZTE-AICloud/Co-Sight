"""``X-Request-Id`` 的分配、校验与同名回显。

覆盖三件事：
1. 客户端带合法值 → 原样回显（请求头/响应头同名）；
2. 不合法（字符集/长度）→ 丢弃并重新生成；
3. 不经过业务 handler 的响应（404）同样带上同一个 id。
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agent import auth as agent_auth
from agent.auth import AgentPrincipal
from infrastructure.http.middleware.request_id import RequestIdMiddleware
from infrastructure.logging import trace

HEADER = 'X-Request-Id'
GENERATED = re.compile(r'^[0-9a-f]{16}$')


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get('/whoami')
    def whoami(request: Request):
        return {'state': request.state.request_id,
                'contextvar': trace.get_trace_id()}

    return app


def test_generates_an_id_when_the_client_sends_none():
    # Arrange
    client = TestClient(_app())

    # Act
    response = client.get('/whoami')

    # Assert
    request_id = response.headers[HEADER]
    assert GENERATED.match(request_id)
    assert response.json() == {'state': request_id, 'contextvar': request_id}


@pytest.mark.parametrize('client_id', ['trace-1', 'A.b_c-9', 'a' * 64])
def test_echoes_a_valid_client_id_unchanged(client_id):
    # Arrange
    client = TestClient(_app())

    # Act
    response = client.get('/whoami', headers={HEADER: client_id})

    # Assert
    assert response.headers[HEADER] == client_id
    assert response.json() == {'state': client_id, 'contextvar': client_id}


@pytest.mark.parametrize('client_id', ['a' * 65, 'has space', 'semi;colon',
                                       'quote"x', 'new\nline', 'at@sign'])
def test_discards_an_invalid_client_id(client_id):
    # Arrange
    client = TestClient(_app())

    # Act
    response = client.get('/whoami', headers={HEADER: client_id})

    # Assert
    request_id = response.headers[HEADER]
    assert GENERATED.match(request_id)
    assert response.json() == {'state': request_id, 'contextvar': request_id}


def test_unmatched_routes_still_carry_the_header():
    # Arrange
    client = TestClient(_app())

    # Act
    response = client.get('/no-such-route')

    # Assert
    assert response.status_code == 404
    assert GENERATED.match(response.headers[HEADER])


def test_agent_context_reuses_the_request_id(monkeypatch):
    # Arrange：中间件已把 id 写进 scope.state
    principal = AgentPrincipal('ragk_test', 'demo', frozenset({'kb:read'}), (), 60)
    monkeypatch.setattr(agent_auth, 'authenticate', lambda *args, **kwargs: principal)
    request = Request({'type': 'http', 'method': 'GET', 'path': '/agent/knowledge-bases',
                       'headers': [], 'state': {'request_id': 'trace-abc'}})

    # Act
    ctx = agent_auth.agent_context(request, credentials=None)

    # Assert：审计/用量统计用的 id 与响应头必须是同一个
    assert ctx.trace_id == 'trace-abc'
    assert request.state.trace_id == 'trace-abc'
