"""``AuthMiddleware`` 的路径决策表测试（不连 DB）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auth import service, sessions
from auth.errors import AuthStoreUnavailable, session_expired, unauthorized
from auth.models import AuthUser
from auth.middleware import AuthMiddleware
from shared.prefixes import AGENT_MCP_PATH, AGENT_PREFIX, AUTH_PREFIX, RKB_PREFIX

USER = AuthUser(id=1, username='alice', email='', display_name='Alice',
                role='user', enabled=True, must_change_password=False)
MUST_CHANGE = AuthUser(id=1, username='alice', email='', display_name='Alice',
                       role='user', enabled=True, must_change_password=True)


def _user_name(request: Request):
    user = getattr(request.state, 'auth_user', None)
    return user.username if user is not None else None


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get(RKB_PREFIX + '/health')
    def health():
        return {'ok': True}

    @app.get(RKB_PREFIX + '/auth/status')
    def status():
        return {'ok': True}

    @app.post(RKB_PREFIX + '/auth/login')
    def login():
        return {'ok': True}

    @app.post(RKB_PREFIX + '/auth/logout')
    def logout():
        return {'ok': True}

    @app.get(RKB_PREFIX + '/auth/me')
    def me(request: Request):
        return {'user': _user_name(request)}

    @app.get(RKB_PREFIX + '/knowledge-bases')
    def kbs(request: Request):
        return {'user': _user_name(request)}

    @app.post(RKB_PREFIX + '/knowledge-bases')
    def create_kb(request: Request):
        return {'user': _user_name(request)}

    @app.get(RKB_PREFIX + '/agent-keys')
    def agent_keys():
        return {'ok': True}

    @app.get(RKB_PREFIX + '/extra/ping')
    def extra_ping():
        return {'ok': True}

    @app.get(AGENT_PREFIX + '/status')
    def agent_status():
        return {'ok': True}

    @app.get(AGENT_MCP_PATH)
    def mcp():
        return {'ok': True}

    @app.get('/outside')
    def outside():
        return {'ok': True}

    return app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'local')

    def _validate(token):
        if token != 'token':
            raise unauthorized()
        return USER

    monkeypatch.setattr(service, 'validate_session', _validate)
    return TestClient(_app(), raise_server_exceptions=False)


def _code(response) -> str:
    assert response.headers['content-type'].startswith('application/problem+json')
    return response.json()['code']


def test_none_mode_passes_everything(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'none')
    client = TestClient(_app(), raise_server_exceptions=False)

    assert client.get(RKB_PREFIX + '/knowledge-bases').status_code == 200
    assert client.get(RKB_PREFIX + '/agent-keys').status_code == 200
    assert client.get('/outside').status_code == 200


def test_public_paths_do_not_require_a_session(client):
    assert client.get(RKB_PREFIX + '/health').status_code == 200
    assert client.get(AUTH_PREFIX + '/status').status_code == 200
    assert client.post(AUTH_PREFIX + '/login').status_code == 200
    assert client.post(AUTH_PREFIX + '/logout').status_code == 200


def test_protected_path_requires_a_session(client):
    response = client.get(RKB_PREFIX + '/knowledge-bases')

    assert response.status_code == 401
    assert _code(response) == 'unauthorized'


def test_valid_cookie_sets_auth_user_on_request_state(client):
    response = client.get(RKB_PREFIX + '/knowledge-bases',
                          cookies={sessions.COOKIE_NAME: 'token'})

    assert response.status_code == 200
    assert response.json() == {'user': 'alice'}


def test_expired_session_returns_401(client, monkeypatch):
    def _raise(token):
        raise session_expired()

    monkeypatch.setattr(service, 'validate_session', _raise)

    response = client.get(RKB_PREFIX + '/knowledge-bases',
                          cookies={sessions.COOKIE_NAME: 'token'})

    assert response.status_code == 401
    assert _code(response) == 'session_expired'


def test_missing_auth_table_returns_503(client, monkeypatch):
    def _raise(token):
        raise AuthStoreUnavailable()

    monkeypatch.setattr(service, 'validate_session', _raise)

    response = client.get(RKB_PREFIX + '/knowledge-bases',
                          cookies={sessions.COOKIE_NAME: 'token'})

    assert response.status_code == 503
    assert _code(response) == 'auth_not_initialized'


def test_agent_and_mcp_bypass_session_auth(client):
    assert client.get(AGENT_PREFIX + '/status').status_code == 200
    assert client.get(AGENT_MCP_PATH).status_code == 200


def test_agent_keys_is_a_ui_path_and_requires_session(client):
    response = client.get(RKB_PREFIX + '/agent-keys')
    assert response.status_code == 401

    response = client.get(RKB_PREFIX + '/agent-keys',
                          cookies={sessions.COOKIE_NAME: 'token'})
    assert response.status_code == 200


def test_unsafe_method_requires_a_matching_origin(client):
    response = client.post(RKB_PREFIX + '/knowledge-bases',
                           cookies={sessions.COOKIE_NAME: 'token'})
    assert response.status_code == 403
    assert _code(response) == 'csrf_rejected'

    response = client.post(RKB_PREFIX + '/knowledge-bases',
                           headers={'Origin': 'http://testserver'},
                           cookies={sessions.COOKIE_NAME: 'token'})
    assert response.status_code == 200


def test_must_change_password_blocks_everything_but_me_and_password(client, monkeypatch):
    monkeypatch.setattr(service, 'validate_session', lambda token: MUST_CHANGE)

    blocked = client.get(RKB_PREFIX + '/knowledge-bases',
                         cookies={sessions.COOKIE_NAME: 'token'})
    assert blocked.status_code == 403
    assert _code(blocked) == 'password_change_required'

    allowed = client.get(AUTH_PREFIX + '/me',
                         cookies={sessions.COOKIE_NAME: 'token'})
    assert allowed.status_code == 200


def test_non_rkb_paths_are_not_gated_in_local_mode(client):
    assert client.get('/outside').status_code == 200


def test_gateway_mode_accepts_any_documented_token_header(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'gateway')
    client = TestClient(_app(), raise_server_exceptions=False)

    assert client.get(RKB_PREFIX + '/health').status_code == 200
    assert client.get(RKB_PREFIX + '/knowledge-bases').status_code == 401

    for headers in (
        {'X-Auth-Value': 'token'},
        {'X-Auth-Token': 'token'},
        {'Authorization': 'Bearer token'},
    ):
        assert client.get(RKB_PREFIX + '/knowledge-bases',
                          headers=headers).status_code == 200


def test_filterfree_extra_prefix_still_works(client, monkeypatch):
    monkeypatch.setattr(AuthMiddleware, 'filterfree', [RKB_PREFIX + '/extra'])

    assert client.get(RKB_PREFIX + '/extra/ping').status_code == 200
