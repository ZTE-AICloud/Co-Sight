"""鉴权、作用域、白名单、限流与 KB 解析的单测（不连 DB）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent import auth, keys, knowledge
from agent.auth import AgentPrincipal
from agent.errors import AgentApiError


@pytest.fixture(autouse=True)
def _reset_limiter():
    auth.reset_rate_limiter()
    yield
    auth.reset_rate_limiter()


def _principal(**overrides):
    values = dict(key_prefix='ragk_test', name='demo',
                  scopes=frozenset({'kb:list', 'kb:search', 'kb:answer'}),
                  kb_ids=(), rate_limit_per_min=60)
    values.update(overrides)
    return AgentPrincipal(**values)


def _row(full_key, pepper, **overrides):
    row = {
        'key_prefix': keys.key_prefix(full_key),
        'name': 'demo',
        'key_hash': keys.hash_key(full_key, pepper),
        'scopes': ['kb:list', 'kb:search'],
        'kb_ids': ['kb-1'],
        'rate_limit_per_min': 60,
        'enabled': True,
        'expires_at': None,
    }
    row.update(overrides)
    return row


def _patch_store(monkeypatch, row):
    monkeypatch.setattr(auth.store_pg, 'find_by_prefix', lambda prefix: row)
    monkeypatch.setattr(auth.store_pg, 'touch_last_used', lambda prefix: True)
    monkeypatch.setattr(auth.store_pg, 'record_usage',
                        lambda prefix, day: True)


def test_authenticate_requires_pepper(monkeypatch):
    monkeypatch.delenv('RKB_AGENT_KEY_PEPPER', raising=False)
    with pytest.raises(AgentApiError) as exc:
        auth.authenticate('Bearer ragk_x_y')
    assert exc.value.http_status == 503
    assert exc.value.code == 'configuration_error'


def test_authenticate_accepts_bearer_and_x_api_key(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    full, _ = keys.generate_key()
    _patch_store(monkeypatch, _row(full, 'pepper'))

    assert auth.authenticate('Bearer ' + full).name == 'demo'
    auth.reset_rate_limiter()
    assert auth.authenticate(None, full).name == 'demo'


def test_authenticate_rejects_bad_tokens(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    full, _ = keys.generate_key()
    _patch_store(monkeypatch, _row(full, 'pepper'))

    for authorization in (None, 'Basic abc', 'Bearer not-a-key', 'Bearer ' + full + 'x'):
        with pytest.raises(AgentApiError) as exc:
            auth.authenticate(authorization)
        assert exc.value.http_status == 401


def test_authenticate_rejects_disabled_and_expired(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    full, _ = keys.generate_key()
    _patch_store(monkeypatch, _row(full, 'pepper', enabled=False))
    with pytest.raises(AgentApiError) as exc:
        auth.authenticate('Bearer ' + full)
    assert exc.value.http_status == 401

    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    _patch_store(monkeypatch, _row(full, 'pepper', expires_at=expired))
    with pytest.raises(AgentApiError) as exc:
        auth.authenticate('Bearer ' + full)
    assert exc.value.http_status == 401


def test_rate_limit_is_per_key_and_returns_retry_after(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    full, _ = keys.generate_key()
    _patch_store(monkeypatch, _row(full, 'pepper', rate_limit_per_min=2))

    assert auth.authenticate('Bearer ' + full, now=100.0)
    assert auth.authenticate('Bearer ' + full, now=101.0)
    with pytest.raises(AgentApiError) as exc:
        auth.authenticate('Bearer ' + full, now=102.0)
    assert exc.value.http_status == 429
    assert exc.value.details['retry_after_seconds'] == 58


def test_principal_scope_and_kb_allowlist():
    principal = _principal(scopes=frozenset({'kb:search'}), kb_ids=('kb-1',))
    assert principal.has_scope('kb:search') is True
    assert principal.has_scope('kb:answer') is False
    assert principal.can_access('kb-1') is True
    assert principal.can_access('kb-2') is False
    assert _principal(kb_ids=()).can_access('anything') is True


def test_agent_context_reconstructs_bearer_header(monkeypatch):
    """HTTPBearer 已剥掉 "Bearer "；agent_context 必须拼回去再交给 authenticate。

    回归：曾把 ``credentials.credentials`` 直接当完整 Authorization 头传入，
    authenticate 里的 scheme 解析拿不到 token → REST 恒 401，而 MCP 正常。
    """
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    full, _ = keys.generate_key()
    _patch_store(monkeypatch, _row(full, 'pepper'))

    app = FastAPI()

    @app.get('/x')
    def x(ctx: auth.AgentContext = Depends(auth.agent_context)):
        return {'key': ctx.principal.key_prefix}

    with TestClient(app) as client:
        response = client.get('/x', headers={'Authorization': 'Bearer ' + full})
        assert response.status_code == 200
        assert response.json()['key'] == keys.key_prefix(full)


def test_require_scope_raises_forbidden():
    with pytest.raises(AgentApiError) as exc:
        auth.require_scope(_principal(scopes=frozenset()), 'kb:search')
    assert exc.value.http_status == 403
    assert exc.value.code == 'forbidden_scope'


def test_error_headers_for_401_and_429():
    from agent.errors import rate_limited, unauthorized

    assert auth.error_headers(unauthorized())['WWW-Authenticate'] == 'Bearer'
    assert auth.error_headers(rate_limited(7))['Retry-After'] == '7'


# ---------------------------------------------------------------------------
# knowledge
# ---------------------------------------------------------------------------

def _kb(kb_id, name, category=1, table=None):
    return {
        'kbase_id': kb_id, 'name': name, 'category': category,
        'description': 'desc', 'type': 'document', 'embedding_model': 'm',
        'status': '7', 'created_at': datetime(2026, 10, 19, 1, 2, 3),
        'table_name': table or f'doc_{kb_id}_vector', 'id': 1,
    }


def test_list_knowledge_bases_filters_category_and_allowlist(monkeypatch):
    rows = [_kb('kb-1', 'one'), _kb('kb-2', 'two'), _kb('graph', 'g', category=10)]
    monkeypatch.setattr(knowledge.kbase_store, 'list_all_kbases', lambda: rows)

    result = knowledge.list_knowledge_bases(_principal(kb_ids=('kb-1', 'kb-2')))
    assert [item['id'] for item in result] == ['kb-1', 'kb-2']
    assert result[0]['created_date'] == '2026-10-19T01:02:03'


def test_resolve_kbases_explicit_access_rules(monkeypatch):
    rows = [_kb('kb-1', 'one'), _kb('kb-2', 'two'), _kb('graph', 'g', category=10)]
    monkeypatch.setattr(knowledge.kbase_store, 'list_all_kbases', lambda: rows)
    principal = _principal(kb_ids=('kb-1',))

    resolved, explicit = knowledge.resolve_kbases(principal, ['kb-1'])
    assert explicit is True and [row['kbase_id'] for row in resolved] == ['kb-1']

    for kb_id, status in (('missing', 404), ('graph', 404), ('kb-2', 403)):
        with pytest.raises(AgentApiError) as exc:
            knowledge.resolve_kbases(principal, [kb_id])
        assert exc.value.http_status == status


def test_resolve_kbases_implicit_caps_and_empty(monkeypatch):
    rows = [_kb('kb-1', 'one'), _kb('kb-2', 'two')]
    monkeypatch.setattr(knowledge.kbase_store, 'list_all_kbases', lambda: rows)
    monkeypatch.setenv('RKB_AGENT_MAX_KBS', '1')

    with pytest.raises(AgentApiError) as exc:
        knowledge.resolve_kbases(_principal(), None)
    assert exc.value.http_status == 400

    monkeypatch.setattr(knowledge.kbase_store, 'list_all_kbases', lambda: [])
    with pytest.raises(AgentApiError) as exc:
        knowledge.resolve_kbases(_principal(), None)
    assert exc.value.code == 'no_accessible_knowledge_bases'
