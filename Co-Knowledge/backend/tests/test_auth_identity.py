"""``current_user`` 的会话身份优先与防伪造测试。"""

from __future__ import annotations

import logging

from starlette.requests import Request

from auth.models import AuthUser
from infrastructure.http.identity import current_user

USER = AuthUser(id=1, username='alice', email='', display_name='Alice',
                role='user', enabled=True, must_change_password=False)


def _request(headers: dict | None = None, state: dict | None = None) -> Request:
    raw_headers = [
        (str(key).lower().encode('latin-1'), str(value).encode('latin-1'))
        for key, value in (headers or {}).items()
    ]
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/api/co-knowledge/v1/knowledge-bases',
        'raw_path': b'/api/co-knowledge/v1/knowledge-bases',
        'query_string': b'',
        'scheme': 'http',
        'server': ('testserver', 80),
        'root_path': '',
        'headers': raw_headers,
        'state': state or {},
    }
    return Request(scope)


def test_local_mode_prefers_the_session_user(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'local')
    request = _request({'X-Emp-No': 'spoofed'}, {'auth_user': USER})

    assert current_user(request) == 'alice'


def test_local_mode_never_falls_back_to_spoofable_headers(monkeypatch, caplog):
    monkeypatch.setenv('AUTH_MODE', 'local')
    request = _request({'X-Emp-No': 'spoofed', 'username': 'also-spoofed'})

    with caplog.at_level(logging.WARNING):
        assert current_user(request) == ''
    assert any('without a local session' in record.message
               for record in caplog.records)


def test_none_mode_keeps_the_legacy_header_contract(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'none')

    assert current_user(_request({'X-Emp-No': 'bob'})) == 'bob'
    assert current_user(_request({'username': 'carol'})) == 'carol'
    assert current_user(_request({})) == 'admin'


def test_none_mode_uses_auth_default_user(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'none')
    monkeypatch.setenv('AUTH_DEFAULT_USER', 'operator')

    assert current_user(_request({})) == 'operator'


def test_gateway_mode_keeps_the_legacy_header_contract(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'gateway')

    assert current_user(_request({'X-Emp-No': 'dave'})) == 'dave'
