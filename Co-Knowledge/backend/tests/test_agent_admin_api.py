"""``agent_api.admin_rest`` 的 HTTP 层单测（不连 DB / 不启 MCP）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import admin_rest, keys, repository_pg as store_pg
from agent.errors import AgentKeyStoreUnavailable
from shared.prefixes import AGENT_ADMIN_PREFIX

PREFIX = 'ragk_1a2b3c4d'
PLAINTEXT = 'ragk_1a2b3c4d_secretsecret'


def _row(**overrides):
    values = {
        'key_prefix': PREFIX,
        'name': 'demo',
        'description': 'demo purpose',
        'scopes': ['kb:list', 'kb:search'],
        'kb_ids': [],
        'rate_limit_per_min': 60,
        'enabled': True,
        'expires_at': None,
        'last_used_at': None,
        'created_at': None,
        'created_by': 'admin',
    }
    values.update(overrides)
    return values


def _app():
    app = FastAPI()
    app.include_router(admin_rest.build_admin_router())
    return app


def _body(response):
    return response.json()


def _code(response):
    assert response.status_code >= 400, response.text
    body = _body(response)
    assert response.headers['content-type'].startswith('application/problem+json')
    return body['code'], body['detail']


def _bo(response):
    assert 200 <= response.status_code < 300, response.text
    return _body(response)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    monkeypatch.setenv('RKB_AGENT_KEY_ADMIN_ENABLED', 'true')
    monkeypatch.setenv('AUTH_MODE', 'none')
    monkeypatch.setattr(store_pg, 'ping', lambda: True)
    with TestClient(_app()) as test_client:
        yield test_client


def test_status_reports_paths_and_flags(client, monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'gateway')
    data = _bo(client.get(AGENT_ADMIN_PREFIX + '/status'))

    assert data['adminEnabled'] is True
    assert data['pepperConfigured'] is True
    assert data['keyStoreAvailable'] is True
    assert data['restBasePath'].endswith('/api/co-knowledge/v1/agent')
    assert data['mcpPath'].endswith('/api/co-knowledge/v1/mcp')
    assert data['authMode'] == 'gateway'
    assert data['defaultScopes'] == ['kb:list', 'kb:search']


def test_list_shape_and_no_secret(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'list_keys', lambda: [
        _row(key_hash='a' * 64),
        _row(key_prefix='ragk_deadbeef', name='other'),
    ])

    data = _bo(client.get(AGENT_ADMIN_PREFIX))

    assert data['total'] == 2
    assert data['items'][0]['keyPrefix'] == PREFIX
    assert data['items'][0]['name'] == 'demo'
    assert data['items'][0]['description'] == 'demo purpose'
    assert 'keyHash' not in data['items'][0]
    assert 'key_hash' not in data['items'][0]
    assert 'a' * 64 not in str(data)


def test_list_keyword_and_pagination(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'list_keys', lambda: [
        _row(key_prefix='ragk_aaaaaaaa', name='alpha'),
        _row(key_prefix='ragk_bbbbbbbb', name='beta'),
    ])

    data = _bo(client.get(AGENT_ADMIN_PREFIX,
                          params={'keyword': 'beta', 'currentPage': 1,
                                  'pageSize': 50}))
    assert data['total'] == 1
    assert data['items'][0]['name'] == 'beta'


def test_create_returns_plaintext_once_and_stores_hash(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(keys, 'generate_key', lambda: (PLAINTEXT, PREFIX))
    monkeypatch.setattr(store_pg, 'insert_key',
                        lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(store_pg, 'get_key', lambda prefix: _row())

    response = client.post(
        AGENT_ADMIN_PREFIX,
        headers={'X-Emp-No': 'alice'},
        json={'name': 'demo', 'description': 'for dify', 'scopes': ['kb:list'],
              'kbIds': [], 'rateLimitPerMin': 60, 'expiresAt': None},
    )
    body = _body(response)
    assert response.status_code == 201
    assert body['plaintextKey'] == PLAINTEXT
    assert body['key']['keyPrefix'] == PREFIX
    assert response.headers['Cache-Control'] == 'no-store'

    assert captured['key_prefix'] == PREFIX
    assert captured['key_hash'] == keys.hash_key(PLAINTEXT, 'pepper')
    assert captured['created_by'] == 'alice'
    assert captured['scopes'] == ['kb:list']
    assert captured['description'] == 'for dify'


@pytest.mark.parametrize('payload, expected', [
    ({}, '请填写名称'),
    ({'name': 'x' * 129}, '名称不能超过'),
    ({'name': 'demo', 'description': 'x' * 201, 'scopes': ['kb:list']},
     '用途说明不能超过'),
    ({'name': 'demo', 'description': 1, 'scopes': ['kb:list']},
     '用途说明必须是文本'),
    ({'name': 'demo', 'scopes': []}, '请至少选择一个权限'),
    ({'name': 'demo', 'scopes': ['nope']}, '未知权限'),
    ({'name': 'demo', 'scopes': ['kb:list'], 'rateLimitPerMin': True},
     '每分钟请求上限'),
    ({'name': 'demo', 'scopes': ['kb:list'], 'rateLimitPerMin': -1},
     '每分钟请求上限'),
    ({'name': 'demo', 'scopes': ['kb:list'], 'expiresAt': 'not-a-date'},
     '过期时间无法解析'),
    ({'name': 'demo', 'scopes': ['kb:list'], 'expiresAt': '2000-01-01'},
     '过期时间必须晚于当前时间'),
    ({'name': 'demo', 'scopes': ['kb:list'], 'unexpected': 1}, '未知字段'),
])
def test_create_validation(client, payload, expected):
    code, message = _code(client.post(
        AGENT_ADMIN_PREFIX, json=payload,
        headers={'Accept-Language': 'zh-CN'}))
    assert code == 'validation_failed'
    assert expected in message


def test_create_malformed_json_is_0004(client):
    response = client.post(AGENT_ADMIN_PREFIX, content=b'{',
                           headers={'Content-Type': 'application/json'})
    assert _code(response)[0] == 'malformed_request'


def test_create_requires_pepper(client, monkeypatch):
    monkeypatch.delenv('RKB_AGENT_KEY_PEPPER', raising=False)
    monkeypatch.setattr(store_pg, 'insert_key',
                        lambda **_kwargs: pytest.fail('must not insert'))
    code, message = _code(client.post(
        AGENT_ADMIN_PREFIX,
        json={'name': 'demo', 'scopes': ['kb:list']},
    ))
    assert code == 'service_unavailable'
    assert 'RKB_AGENT_KEY_PEPPER' in message


def test_patch_updates_and_toggles(client, monkeypatch):
    captured = {}

    def fake_update(prefix, **changes):
        captured['prefix'] = prefix
        captured['changes'] = changes
        return _row(name=changes.get('name', 'demo'),
                    enabled=changes.get('enabled', True))

    monkeypatch.setattr(store_pg, 'update_key', fake_update)

    data = _bo(client.patch(AGENT_ADMIN_PREFIX + '/' + PREFIX,
                            json={'enabled': False, 'name': 'renamed',
                                  'description': 'new purpose'}))
    assert data['enabled'] is False
    assert captured['changes'] == {
        'enabled': False, 'name': 'renamed', 'description': 'new purpose'}


def test_patch_empty_and_unknown_fields(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'update_key',
                        lambda prefix, **changes: pytest.fail('must not update'))
    assert _code(client.patch(AGENT_ADMIN_PREFIX + '/' + PREFIX, json={}))[0] == 'validation_failed'
    assert _code(client.patch(AGENT_ADMIN_PREFIX + '/' + PREFIX,
                              json={'nope': 1}))[0] == 'validation_failed'


def test_patch_not_found(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'update_key', lambda prefix, **changes: None)
    code, message = _code(client.patch(
        AGENT_ADMIN_PREFIX + '/' + PREFIX, json={'name': 'x'},
        headers={'Accept-Language': 'zh-CN'}))
    assert code == 'api_key_not_found'
    assert '不存在' in message


def test_delete_round_trip_and_not_found(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'delete_key', lambda prefix: 1)
    assert _bo(client.delete(AGENT_ADMIN_PREFIX + '/' + PREFIX)) == {
        'keyPrefix': PREFIX}

    monkeypatch.setattr(store_pg, 'delete_key', lambda prefix: 0)
    assert _code(client.delete(AGENT_ADMIN_PREFIX + '/' + PREFIX))[0] == 'api_key_not_found'


def test_store_unavailable_maps_to_0001_but_status_stays_0000(client, monkeypatch):
    def boom():
        raise AgentKeyStoreUnavailable()

    monkeypatch.setattr(store_pg, 'list_keys', boom)
    assert _code(client.get(AGENT_ADMIN_PREFIX))[0] == 'service_unavailable'

    monkeypatch.setattr(store_pg, 'ping', boom)
    status = _bo(client.get(AGENT_ADMIN_PREFIX + '/status'))
    assert status['keyStoreAvailable'] is False


def test_kill_switch_keeps_status_readable(client, monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_ADMIN_ENABLED', 'false')
    assert _bo(client.get(AGENT_ADMIN_PREFIX + '/status'))['adminEnabled'] is False
    code, message = _code(client.get(
        AGENT_ADMIN_PREFIX, headers={'Accept-Language': 'zh-CN'}))
    assert code == 'permission_denied'
    assert '未启用' in message


def test_error_messages_follow_accept_language(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'delete_key', lambda prefix: 0)
    zh = _code(client.delete(AGENT_ADMIN_PREFIX + '/' + PREFIX,
                             headers={'Accept-Language': 'zh-CN'}))[1]
    en = _code(client.delete(AGENT_ADMIN_PREFIX + '/' + PREFIX,
                             headers={'Accept-Language': 'en-US'}))[1]
    assert zh != en
    assert '不存在' in zh
    assert 'not found' in en.lower()


def test_admin_router_paths_are_registered_before_kb_catch_all():
    from app import app
    from shared.prefixes import RKB_PREFIX

    from route_helpers import route_paths

    paths = route_paths(app)
    catch_all = paths.index(RKB_PREFIX + '/{unknown_path:path}')
    assert paths.index(AGENT_ADMIN_PREFIX) < catch_all
    assert AGENT_ADMIN_PREFIX + '/status' in paths


def test_list_enabled_filter_and_sort_uses_server_side_order(client, monkeypatch):
    monkeypatch.setattr(store_pg, 'list_keys', lambda: [
        _row(key_prefix='ragk_aaaaaaaa', name='zeta', enabled=False),
        _row(key_prefix='ragk_bbbbbbbb', name='alpha', enabled=True),
        _row(key_prefix='ragk_cccccccc', name='missing-expiry', enabled=True, expires_at=None),
    ])

    data = _bo(client.get(AGENT_ADMIN_PREFIX, params={
        'enabled': 'true', 'sortBy': 'name', 'sortOrder': 'asc'}))
    assert [item['name'] for item in data['items']] == ['alpha', 'missing-expiry']
    assert data['total'] == 2

    data = _bo(client.get(AGENT_ADMIN_PREFIX, params={'sortBy': 'expiresAt', 'sortOrder': 'desc'}))
    # 空值不参与排序，且始终排在最后
    assert [item['name'] for item in data['items']][-1] == 'missing-expiry'
