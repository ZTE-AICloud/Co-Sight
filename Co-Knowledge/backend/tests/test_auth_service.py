"""认证服务单测（repo 全部 monkeypatch，不连 DB）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from auth import passwords, repository as repo, service, sessions
from auth.errors import AuthError
from auth.models import AuthUser

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'local')
    service.reset_rate_limiter()
    yield
    service.reset_rate_limiter()


@pytest.fixture(scope='module')
def secret_hash():
    return passwords.hash_password('secret123')


def _row(secret_hash, **overrides):
    row = {
        'id': 1,
        'username': 'alice',
        'email': 'alice@example.com',
        'display_name': 'Alice',
        'password_hash': secret_hash,
        'role': 'user',
        'enabled': True,
        'must_change_password': False,
        'last_login_at': None,
    }
    row.update(overrides)
    return row


def _session_row(secret_hash, token, **overrides):
    row = {
        **_row(secret_hash),
        'session_id': 10,
        'token_hash': sessions.hash_token(token),
        'expires_at': T0 + timedelta(hours=1),
        'revoked_at': None,
    }
    row.update(overrides)
    return row


def _patch_login_repo(monkeypatch, row):
    calls = {'touched': [], 'sessions': [], 'cleanup': []}
    monkeypatch.setattr(repo, 'find_user_by_login', lambda login: row)
    monkeypatch.setattr(repo, 'touch_last_login', lambda user_id: calls['touched'].append(user_id))
    monkeypatch.setattr(repo, 'create_session', lambda **kwargs: calls['sessions'].append(kwargs) or 1)
    monkeypatch.setattr(repo, 'delete_expired_sessions', lambda before: calls['cleanup'].append(before))
    return calls


def test_login_success_issues_a_new_session(monkeypatch, secret_hash):
    row = _row(secret_hash)
    calls = _patch_login_repo(monkeypatch, row)

    result = service.login('Alice', 'secret123', ip='10.0.0.7',
                           user_agent='pytest', now=T0)

    assert result.user.username == 'alice'
    assert result.expires_at == T0 + timedelta(seconds=sessions.session_ttl_seconds())
    assert calls['touched'] == [1]
    created = calls['sessions'][0]
    assert created['user_id'] == 1
    assert created['token_hash'] == sessions.hash_token(result.token)
    assert created['ip'] == '10.0.0.7'
    assert created['expires_at'] == result.expires_at


def test_login_unknown_user_runs_dummy_verify(monkeypatch):
    seen = []
    monkeypatch.setattr(repo, 'find_user_by_login', lambda login: None)
    monkeypatch.setattr(passwords, 'verify_password',
                        lambda password, stored: seen.append(stored) or False)

    with pytest.raises(AuthError) as exc:
        service.login('nobody', 'whatever', ip='1.1.1.1')

    assert exc.value.problem_code == 'invalid_credentials'
    assert seen == [passwords.DUMMY_HASH]


def test_login_bad_password_is_rate_limited_after_five_failures(monkeypatch, secret_hash):
    _patch_login_repo(monkeypatch, _row(secret_hash))

    for _ in range(5):
        with pytest.raises(AuthError) as exc:
            service.login('alice', 'wrong-password', ip='1.1.1.1')
        assert exc.value.problem_code == 'invalid_credentials'

    with pytest.raises(AuthError) as exc:
        service.login('alice', 'wrong-password', ip='1.1.1.1')
    assert exc.value.problem_code == 'login_rate_limited'
    assert exc.value.retry_after > 0


def test_login_disabled_account_requires_correct_password_first(monkeypatch, secret_hash):
    _patch_login_repo(monkeypatch, _row(secret_hash, enabled=False))

    with pytest.raises(AuthError) as exc:
        service.login('alice', 'wrong-password', ip='1.1.1.1')
    assert exc.value.problem_code == 'invalid_credentials'

    with pytest.raises(AuthError) as exc:
        service.login('alice', 'secret123', ip='1.1.1.1')
    assert exc.value.problem_code == 'account_disabled'


def test_login_rejects_non_local_mode(monkeypatch, secret_hash):
    monkeypatch.setenv('AUTH_MODE', 'none')
    with pytest.raises(AuthError) as exc:
        service.login('alice', 'secret123')
    assert exc.value.problem_code == 'auth_not_enabled'


def test_validate_session_success_and_throttled_touch(monkeypatch, secret_hash):
    token, _ = sessions.new_session_token()
    touches = []
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: _session_row(secret_hash, token))
    monkeypatch.setattr(repo, 'touch_session', lambda session_id: touches.append(session_id))

    user = service.validate_session(token, now=T0)
    service.validate_session(token, now=T0 + timedelta(seconds=60))

    assert user.username == 'alice'
    assert touches == [10]

    service.validate_session(token, now=T0 + timedelta(seconds=service.TOUCH_INTERVAL_SECONDS + 1))
    assert touches == [10, 10]


def test_validate_session_expired_revokes(monkeypatch, secret_hash):
    token, _ = sessions.new_session_token()
    revoked = []
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: _session_row(
        secret_hash, token, expires_at=T0 - timedelta(seconds=1)))
    monkeypatch.setattr(repo, 'revoke_session', lambda token_hash: revoked.append(token_hash) or 1)

    with pytest.raises(AuthError) as exc:
        service.validate_session(token, now=T0)

    assert exc.value.problem_code == 'session_expired'
    assert revoked == [sessions.hash_token(token)]


def test_validate_session_revoked_is_expired(monkeypatch, secret_hash):
    token, _ = sessions.new_session_token()
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: _session_row(
        secret_hash, token, revoked_at=T0))

    with pytest.raises(AuthError) as exc:
        service.validate_session(token, now=T0)
    assert exc.value.problem_code == 'session_expired'


def test_validate_session_disabled_user_revokes_all_sessions(monkeypatch, secret_hash):
    token, _ = sessions.new_session_token()
    revoked = []
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: _session_row(
        secret_hash, token, enabled=False))
    monkeypatch.setattr(repo, 'revoke_user_sessions',
                        lambda user_id, **kwargs: revoked.append(user_id) or 1)

    with pytest.raises(AuthError) as exc:
        service.validate_session(token, now=T0)

    assert exc.value.problem_code == 'account_disabled'
    assert revoked == [1]


def test_validate_session_unknown_token(monkeypatch):
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: None)

    with pytest.raises(AuthError) as exc:
        service.validate_session('nope', now=T0)
    assert exc.value.problem_code == 'unauthorized'


def test_current_user_or_none_swallows_auth_errors(monkeypatch, secret_hash):
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: None)
    assert service.current_user_or_none('nope', now=T0) is None

    token, _ = sessions.new_session_token()
    monkeypatch.setattr(repo, 'find_session', lambda token_hash: _session_row(secret_hash, token))
    assert service.current_user_or_none(token, now=T0).username == 'alice'


def test_logout_revokes_the_session(monkeypatch):
    revoked = []
    monkeypatch.setattr(repo, 'revoke_session', lambda token_hash: revoked.append(token_hash) or 1)

    service.logout('token-value')
    service.logout('')

    assert revoked == [sessions.hash_token('token-value')]


def test_change_password_rejects_wrong_current_password(monkeypatch, secret_hash):
    monkeypatch.setattr(repo, 'get_user', lambda user_id: _row(secret_hash))
    user = AuthUser.from_row(_row(secret_hash))

    with pytest.raises(AuthError) as exc:
        service.change_password(user, 'wrong', 'new-password-123', now=T0)
    assert exc.value.problem_code == 'invalid_current_password'


def test_change_password_success_revokes_other_sessions(monkeypatch, secret_hash):
    row = _row(secret_hash)
    updated = {}
    revoked = []
    monkeypatch.setattr(repo, 'get_user', lambda user_id: row)
    monkeypatch.setattr(repo, 'update_password',
                        lambda user_id, password_hash, **kwargs: updated.update(
                            user_id=user_id, password_hash=password_hash, **kwargs) or 1)
    monkeypatch.setattr(repo, 'revoke_user_sessions',
                        lambda user_id, **kwargs: revoked.append((user_id, kwargs)) or 1)
    monkeypatch.setattr(service, '_remove_bootstrap_password_file', lambda: None)

    service.change_password(AuthUser.from_row(row), 'secret123', 'new-password-123',
                            current_token='current-token', now=T0)

    assert updated['user_id'] == 1
    assert updated['must_change_password'] is False
    assert passwords.verify_password('new-password-123', updated['password_hash'])
    assert revoked[0][0] == 1
    assert revoked[0][1]['except_token_hash'] == sessions.hash_token('current-token')


def test_change_password_enforces_policy(monkeypatch, secret_hash):
    monkeypatch.setattr(repo, 'get_user', lambda user_id: _row(secret_hash))
    monkeypatch.setattr(service, '_remove_bootstrap_password_file', lambda: None)

    user = AuthUser.from_row(_row(secret_hash))
    with pytest.raises(AuthError) as exc:
        service.change_password(user, 'secret123', 'short', now=T0)
    assert exc.value.problem_code == 'password_policy'

    with pytest.raises(AuthError) as exc:
        service.change_password(user, 'secret123', 'secret123', now=T0)
    assert exc.value.problem_code == 'password_policy'


def test_create_user_validates_and_persists(monkeypatch, secret_hash):
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return _row(kwargs['password_hash'], username=kwargs['username'],
                    display_name=kwargs.get('display_name') or '')

    monkeypatch.setattr(repo, 'create_user', _create)

    user = service.create_user('bob', 'password-123', display_name='Bob',
                               email='bob@example.com', role='admin',
                               must_change_password=True)

    assert user.username == 'bob'
    assert captured['username'] == 'bob'
    assert captured['role'] == 'admin'
    assert captured['email'] == 'bob@example.com'
    assert captured['must_change_password'] is True
    assert passwords.verify_password('password-123', captured['password_hash'])


def test_create_user_rejects_invalid_email(monkeypatch):
    monkeypatch.setattr(repo, 'create_user', lambda **kwargs: pytest.fail('must not insert'))

    with pytest.raises(AuthError) as exc:
        service.create_user('bob', 'password-123', email='not-an-email')
    assert exc.value.problem_code == 'invalid_email'


def test_create_user_rejects_weak_password_by_default(monkeypatch):
    monkeypatch.setattr(repo, 'create_user', lambda **kwargs: pytest.fail('must not insert'))

    with pytest.raises(AuthError) as exc:
        service.create_user('bob', 'admin')
    assert exc.value.problem_code == 'password_policy'


def test_create_user_allows_weak_bootstrap_password(monkeypatch):
    captured = {}
    monkeypatch.setattr(repo, 'create_user',
                        lambda **kwargs: captured.update(kwargs) or _row(
                            kwargs['password_hash'], username='bob'))

    user = service.create_user('bob', 'admin', allow_weak_password=True)

    assert user.username == 'bob'
    assert passwords.verify_password('admin', captured['password_hash'])


def test_reset_password_revokes_sessions(monkeypatch, secret_hash):
    revoked = []
    monkeypatch.setattr(repo, 'find_user_by_username', lambda username: _row(secret_hash))
    monkeypatch.setattr(repo, 'update_password', lambda *args, **kwargs: 1)
    monkeypatch.setattr(repo, 'revoke_user_sessions',
                        lambda user_id, **kwargs: revoked.append(user_id) or 1)
    monkeypatch.setattr(service, '_remove_bootstrap_password_file', lambda: None)

    service.reset_password('alice', 'new-password-123')

    assert revoked == [1]


def test_set_enabled_false_revokes_sessions(monkeypatch, secret_hash):
    revoked = []
    row = _row(secret_hash)
    monkeypatch.setattr(repo, 'find_user_by_username', lambda username: row)
    monkeypatch.setattr(repo, 'set_enabled', lambda user_id, enabled: 1)
    monkeypatch.setattr(repo, 'revoke_user_sessions',
                        lambda user_id, **kwargs: revoked.append(user_id) or 1)
    monkeypatch.setattr(repo, 'get_user', lambda user_id: _row(secret_hash, enabled=False))

    user = service.set_enabled('alice', False)

    assert user.enabled is False
    assert revoked == [1]


def test_delete_user(monkeypatch, secret_hash):
    deleted = []
    monkeypatch.setattr(repo, 'find_user_by_username', lambda username: _row(secret_hash))
    monkeypatch.setattr(repo, 'delete_user', lambda user_id: deleted.append(user_id) or 1)

    service.delete_user('alice')
    assert deleted == [1]


def test_auth_mode_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'jwt')
    with pytest.raises(RuntimeError):
        service.auth_mode()


def test_auth_mode_defaults_to_local(monkeypatch):
    """未设置 AUTH_MODE 时必须 fail-closed，而不是静默变成无鉴权。"""
    monkeypatch.delenv('AUTH_MODE', raising=False)
    assert service.auth_mode() == 'local'
