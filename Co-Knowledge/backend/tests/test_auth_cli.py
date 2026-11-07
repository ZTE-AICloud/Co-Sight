"""账号管理 CLI 测试（service/repo 全部 monkeypatch）。"""

from __future__ import annotations

from auth import cli, repository as repo, service
from auth.errors import AuthStoreUnavailable
from auth.models import AuthUser

USER = AuthUser(id=7, username='alice', email='alice@example.com',
                display_name='Alice', role='user', enabled=True,
                must_change_password=True)


def test_create_generates_and_prints_a_password_once(monkeypatch, capsys):
    captured = {}

    def _create(username, password, **kwargs):
        captured.update(username=username, password=password, **kwargs)
        return USER

    monkeypatch.setattr(service, 'create_user', _create)

    assert cli.main(['create', '--username', 'alice', '--generate']) == 0
    out = capsys.readouterr().out

    assert captured['username'] == 'alice'
    assert len(captured['password']) >= 20
    assert captured['must_change_password'] is False
    assert 'created: alice (user)' in out
    assert out.count(captured['password']) == 1


def test_create_with_explicit_password_does_not_echo_it(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(service, 'create_user',
                        lambda username, password, **kwargs: captured.update(
                            password=password) or USER)

    assert cli.main(['create', '--username', 'alice',
                     '--password', 'explicit-password-123']) == 0
    out = capsys.readouterr().out

    assert captured['password'] == 'explicit-password-123'
    assert 'explicit-password-123' not in out


def test_generate_wins_over_password(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(service, 'create_user',
                        lambda username, password, **kwargs: captured.update(
                            password=password) or USER)

    assert cli.main(['create', '--username', 'alice',
                     '--password', 'explicit-password-123',
                     '--generate']) == 0

    assert captured['password'] != 'explicit-password-123'


def test_delete_requires_yes(capsys):
    assert cli.main(['delete', '--username', 'alice']) == 2
    assert '--yes' in capsys.readouterr().err


def test_list_empty(monkeypatch, capsys):
    monkeypatch.setattr(repo, 'list_users', lambda: [])

    assert cli.main(['list']) == 0
    assert '(no accounts)' in capsys.readouterr().out


def test_list_prints_rows(monkeypatch, capsys):
    monkeypatch.setattr(repo, 'list_users', lambda: [{
        'username': 'alice', 'role': 'admin', 'enabled': True,
        'must_change_password': False, 'last_login_at': None,
        'display_name': 'Alice',
    }])

    assert cli.main(['list']) == 0
    out = capsys.readouterr().out
    assert 'alice' in out and 'admin' in out and 'Alice' in out


def test_reset_password_honors_no_must_change(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(service, 'reset_password',
                        lambda username, password, **kwargs: captured.update(
                            username=username, **kwargs) or USER)

    assert cli.main(['reset-password', '--username', 'alice',
                     '--password', 'new-password-123',
                     '--no-must-change']) == 0

    assert captured['username'] == 'alice'
    assert captured['must_change_password'] is False


def test_missing_table_prints_initialization_hint(monkeypatch, capsys):
    def _raise(*args, **kwargs):
        raise AuthStoreUnavailable()

    monkeypatch.setattr(service, 'create_user', _raise)

    assert cli.main(['create', '--username', 'alice', '--generate']) == 1
    assert 'deploy/init/pg/00-schema.sql' in capsys.readouterr().err


def test_auth_error_is_printed(monkeypatch, capsys):
    from auth.errors import password_policy

    def _raise(*args, **kwargs):
        raise password_policy()

    monkeypatch.setattr(service, 'create_user', _raise)

    assert cli.main(['create', '--username', 'alice', '--generate']) == 1
    err = capsys.readouterr().err
    assert 'password_policy' in err


def test_enable_and_disable(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(service, 'set_enabled',
                        lambda username, enabled: calls.append((username, enabled)) or USER)

    assert cli.main(['disable', '--username', 'alice']) == 0
    assert cli.main(['enable', '--username', 'alice']) == 0
    assert calls == [('alice', False), ('alice', True)]
