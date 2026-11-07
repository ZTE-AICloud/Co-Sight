"""``/auth/*`` HTTP 契约测试（FastAPI TestClient，不连 DB）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import repository as repo, service, sessions
from auth.api import register_auth_api
from auth.errors import (AuthError, AuthStoreUnavailable, account_disabled,
                         invalid_credentials, login_rate_limited)
from auth.models import AuthUser
from shared.prefixes import AUTH_PREFIX

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
USER = AuthUser(id=1, username='alice', email='alice@example.com',
                display_name='Alice', role='user', enabled=True,
                must_change_password=False)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'local')
    app = FastAPI()
    register_auth_api(app)
    return TestClient(app, raise_server_exceptions=False)


def _auth_error(response) -> tuple[str, str]:
    assert response.headers['content-type'].startswith('application/problem+json')
    body = response.json()
    return body['code'], body['detail']


def test_status_none_mode_never_touches_the_database(client, monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'none')
    monkeypatch.setattr(repo, 'table_exists',
                        lambda: pytest.fail('must not query the DB in none mode'))

    response = client.get(AUTH_PREFIX + '/status')

    assert response.status_code == 200
    assert response.json() == {
        'mode': 'none', 'initialized': True,
        'authenticated': False, 'user': None,
    }
    assert response.headers['cache-control'] == 'no-store'


def test_status_local_reports_uninitialized_when_table_missing(client, monkeypatch):
    monkeypatch.setattr(repo, 'table_exists', lambda: False)

    response = client.get(AUTH_PREFIX + '/status')

    assert response.status_code == 200
    assert response.json()['initialized'] is False
    assert response.json()['authenticated'] is False


def test_status_local_returns_authenticated_user(client, monkeypatch):
    monkeypatch.setattr(repo, 'table_exists', lambda: True)
    monkeypatch.setattr(service, 'current_user_or_none', lambda token: USER)

    response = client.get(AUTH_PREFIX + '/status',
                          cookies={sessions.COOKIE_NAME: 'token'})

    body = response.json()
    assert body['mode'] == 'local'
    assert body['initialized'] is True
    assert body['authenticated'] is True
    assert body['user'] == {
        'username': 'alice', 'displayName': 'Alice',
        'email': 'alice@example.com', 'role': 'user',
        'mustChangePassword': False,
    }
    assert 'passwordHash' not in str(body)
    assert 'password_hash' not in str(body)


def test_login_sets_httponly_cookie_and_returns_public_user(client, monkeypatch):
    monkeypatch.setattr(service, 'login', lambda *args, **kwargs: service.LoginResult(
        user=USER, token='plain-token',
        expires_at=NOW + timedelta(hours=12)))

    response = client.post(AUTH_PREFIX + '/login',
                           json={'username': 'alice', 'password': 'secret123'})

    assert response.status_code == 200
    assert response.json()['user']['username'] == 'alice'
    cookie = response.headers['set-cookie']
    assert cookie.startswith(sessions.COOKIE_NAME + '=plain-token')
    for part in ('HttpOnly', 'SameSite=Lax', 'Path=/', 'Max-Age='):
        assert part in cookie
    assert 'Secure' not in cookie
    assert response.headers['cache-control'] == 'no-store'


def test_login_rejects_cross_origin(client, monkeypatch):
    monkeypatch.setattr(service, 'login', lambda *args, **kwargs: pytest.fail('must not login'))

    response = client.post(
        AUTH_PREFIX + '/login',
        json={'username': 'alice', 'password': 'secret123'},
        headers={'Origin': 'https://evil.example.com', 'Host': 'example.com'})

    assert response.status_code == 403
    assert _auth_error(response)[0] == 'csrf_rejected'


def test_login_invalid_credentials_is_a_problem_with_localized_detail(client, monkeypatch):
    def _raise(*args, **kwargs):
        raise invalid_credentials()

    monkeypatch.setattr(service, 'login', _raise)

    response = client.post(AUTH_PREFIX + '/login',
                           json={'username': 'alice', 'password': 'bad'},
                           headers={'Accept-Language': 'zh-CN'})

    assert response.status_code == 401
    code, detail = _auth_error(response)
    assert code == 'invalid_credentials'
    assert detail == '账号或密码不正确'

    english = client.post(AUTH_PREFIX + '/login',
                          json={'username': 'alice', 'password': 'bad'},
                          headers={'Accept-Language': 'en-US'})
    assert _auth_error(english)[1] == 'Incorrect username or password'


def test_login_rate_limited_sets_retry_after(client, monkeypatch):
    def _raise(*args, **kwargs):
        raise login_rate_limited(42)

    monkeypatch.setattr(service, 'login', _raise)

    response = client.post(AUTH_PREFIX + '/login',
                           json={'username': 'alice', 'password': 'bad'})

    assert response.status_code == 429
    assert response.headers['retry-after'] == '42'
    assert _auth_error(response)[0] == 'login_rate_limited'


def test_login_rejects_oversized_body(client):
    response = client.post(
        AUTH_PREFIX + '/login',
        content=b'{"username":"' + b'a' * 9000 + b'","password":"x"}',
        headers={'Content-Type': 'application/json'})

    assert response.status_code == 413
    assert _auth_error(response)[0] == 'payload_too_large'


def test_login_returns_409_when_auth_is_not_enabled(client, monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'none')

    response = client.post(AUTH_PREFIX + '/login',
                           json={'username': 'alice', 'password': 'secret123'})

    assert response.status_code == 409
    assert _auth_error(response)[0] == 'auth_not_enabled'


def test_logout_is_idempotent_and_clears_cookie(client, monkeypatch):
    monkeypatch.setattr(service, 'logout', lambda token: None)

    response = client.post(AUTH_PREFIX + '/logout')

    assert response.status_code == 204
    assert 'Max-Age=0' in response.headers['set-cookie']


def test_me_requires_a_session(client, monkeypatch):
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: None)

    response = client.get(AUTH_PREFIX + '/me')

    assert response.status_code == 401
    assert _auth_error(response)[0] == 'unauthorized'


def test_me_returns_the_session_user(client, monkeypatch):
    monkeypatch.setattr(service, 'validate_session', lambda token: USER)

    response = client.get(AUTH_PREFIX + '/me',
                          cookies={sessions.COOKIE_NAME: 'token'})

    assert response.status_code == 200
    assert response.json()['user']['username'] == 'alice'


def test_password_change_returns_204(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(service, 'validate_session', lambda token: USER)
    monkeypatch.setattr(service, 'change_password',
                        lambda user, current, new, **kwargs: captured.update(
                            user=user.username, current=current, new=new, **kwargs))

    response = client.post(
        AUTH_PREFIX + '/password',
        json={'currentPassword': 'old-password', 'newPassword': 'new-password-123'},
        cookies={sessions.COOKIE_NAME: 'token'})

    assert response.status_code == 204
    assert captured == {'user': 'alice', 'current': 'old-password',
                        'new': 'new-password-123',
                        'current_token': 'token'}


def test_password_change_maps_policy_error(client, monkeypatch):
    monkeypatch.setattr(service, 'validate_session', lambda token: USER)

    def _raise(*args, **kwargs):
        raise AuthError(422, 'password_policy')

    monkeypatch.setattr(service, 'change_password', _raise)

    response = client.post(
        AUTH_PREFIX + '/password',
        json={'currentPassword': 'old-password', 'newPassword': 'short'},
        cookies={sessions.COOKIE_NAME: 'token'})

    assert response.status_code == 422
    assert _auth_error(response)[0] == 'password_policy'


def test_store_unavailable_becomes_503(client, monkeypatch):
    def _raise():
        raise AuthStoreUnavailable()

    monkeypatch.setattr(repo, 'table_exists', _raise)

    response = client.get(AUTH_PREFIX + '/status')

    assert response.status_code == 200
    assert response.json()['initialized'] is False


def test_login_account_disabled_is_403(client, monkeypatch):
    def _raise(*args, **kwargs):
        raise account_disabled()

    monkeypatch.setattr(service, 'login', _raise)

    response = client.post(AUTH_PREFIX + '/login',
                           json={'username': 'alice', 'password': 'secret123'})

    assert response.status_code == 403
    assert _auth_error(response)[0] == 'account_disabled'
