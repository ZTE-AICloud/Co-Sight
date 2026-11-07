"""会话 token / Cookie / 请求来源工具单测（不连 DB）。"""

from __future__ import annotations

import pytest

from auth import sessions


def test_new_session_token_is_high_entropy_and_hashable():
    first, first_hash = sessions.new_session_token()
    second, second_hash = sessions.new_session_token()

    assert first != second
    assert len(first) >= 40
    assert len(first_hash) == 64
    assert first_hash == sessions.hash_token(first)
    assert second_hash == sessions.hash_token(second)


def test_hash_token_is_stable_and_empty_safe():
    assert sessions.hash_token('abc') == sessions.hash_token('abc')
    assert sessions.hash_token('') == sessions.hash_token('')


def test_session_ttl_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv('RKB_AUTH_SESSION_TTL_SECONDS', raising=False)
    assert sessions.session_ttl_seconds() == 12 * 60 * 60

    monkeypatch.setenv('RKB_AUTH_SESSION_TTL_SECONDS', '3600')
    assert sessions.session_ttl_seconds() == 3600

    monkeypatch.setenv('RKB_AUTH_SESSION_TTL_SECONDS', '1')
    assert sessions.session_ttl_seconds() == 60

    monkeypatch.setenv('RKB_AUTH_SESSION_TTL_SECONDS', '999999999')
    assert sessions.session_ttl_seconds() == 30 * 24 * 60 * 60

    monkeypatch.setenv('RKB_AUTH_SESSION_TTL_SECONDS', 'not-a-number')
    assert sessions.session_ttl_seconds() == 12 * 60 * 60


def test_cookie_secure_override(monkeypatch):
    monkeypatch.delenv('RKB_AUTH_COOKIE_SECURE', raising=False)
    assert sessions.cookie_secure_override() is None

    for value in ('true', '1', 'yes', 'on'):
        monkeypatch.setenv('RKB_AUTH_COOKIE_SECURE', value)
        assert sessions.cookie_secure_override() is True

    for value in ('false', '0', 'no', 'off'):
        monkeypatch.setenv('RKB_AUTH_COOKIE_SECURE', value)
        assert sessions.cookie_secure_override() is False

    monkeypatch.setenv('RKB_AUTH_COOKIE_SECURE', 'auto')
    assert sessions.cookie_secure_override() is None


@pytest.mark.parametrize(('scheme', 'forwarded', 'override', 'expected'), [
    ('https', '', None, True),
    ('http', '', None, False),
    ('http', 'https', None, True),
    ('http', 'https,http', None, True),
    ('http', 'http', None, False),
    ('http', 'https', False, False),
    ('http', '', True, True),
])
def test_is_secure_request(scheme, forwarded, override, expected):
    assert sessions.is_secure_request(scheme, forwarded, override) is expected


def test_build_and_clear_cookie_attributes():
    cookie = sessions.build_session_cookie('token-value', 3600, secure=True)

    assert cookie.startswith('ragstudio_session=token-value')
    for part in ('Path=/', 'HttpOnly', 'SameSite=Lax', 'Max-Age=3600', 'Secure'):
        assert part in cookie

    cleared = sessions.clear_session_cookie(secure=False)
    assert 'Max-Age=0' in cleared
    assert 'Secure' not in cleared


def test_extract_session_token():
    assert sessions.extract_session_token({'ragstudio_session': ' abc '}) == 'abc'
    assert sessions.extract_session_token({}) == ''
    assert sessions.extract_session_token(None) == ''


def test_client_ip_prefers_x_real_ip_and_ignores_spoofed_xff():
    headers = {
        'x-real-ip': '10.0.0.7',
        'x-forwarded-for': '1.2.3.4, 10.0.0.7',
    }
    assert sessions.client_ip(headers, '172.17.0.1') == '10.0.0.7'

    assert sessions.client_ip({'x-forwarded-for': '1.2.3.4'}, '172.17.0.1') == '172.17.0.1'
    assert sessions.client_ip({}, '172.17.0.1') == '172.17.0.1'
    assert sessions.client_ip({'x-real-ip': 'x' * 100}, '') == 'x' * 64


def test_origin_allowed_matches_host_and_forwarded_host():
    assert sessions.origin_allowed(
        {'origin': 'http://example.com', 'host': 'example.com'}, required=True)
    assert sessions.origin_allowed(
        {'origin': 'https://example.com:8443', 'host': 'example.com:8443'},
        required=True)
    assert sessions.origin_allowed(
        {'origin': 'https://public.example.com', 'host': 'rkb:8091',
         'x-forwarded-host': 'public.example.com'}, required=True)
    assert sessions.origin_allowed(
        {'referer': 'https://example.com/page?a=1', 'host': 'example.com'},
        required=True)


def test_origin_allowed_rejects_mismatch_and_null():
    for headers in (
        {'origin': 'https://evil.example.com', 'host': 'example.com'},
        {'origin': 'null', 'host': 'example.com'},
        {'referer': 'https://evil.example.com/x', 'host': 'example.com'},
        {'origin': 'not a url', 'host': 'example.com'},
    ):
        assert sessions.origin_allowed(headers, required=True) is False


def test_origin_allowed_missing_headers_depends_on_required():
    assert sessions.origin_allowed({'host': 'example.com'}, required=True) is False
    assert sessions.origin_allowed({'host': 'example.com'}, required=False) is True
