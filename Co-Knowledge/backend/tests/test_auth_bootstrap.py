"""首次启动 admin 播种测试（不连 DB）。"""

from __future__ import annotations

import os

import pytest

from auth import bootstrap, repository as repo, service
from auth.errors import AuthStoreUnavailable
from auth.models import AuthUser

USER = AuthUser(id=1, username='admin', email='', display_name='Administrator',
                role='admin', enabled=True, must_change_password=True)


@pytest.fixture(autouse=True)
def _local(monkeypatch, tmp_path):
    monkeypatch.setenv('AUTH_MODE', 'local')
    monkeypatch.setenv('RKB_ADMIN_PASSWORD_FILE', str(tmp_path / 'initial-admin'))
    monkeypatch.setenv('RKB_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('RKB_ADMIN_PASSWORD', 'configured-password-123')
    monkeypatch.delenv('RKB_ADMIN_MUST_CHANGE', raising=False)
    yield


def _patch_state(monkeypatch, *, exists=True, users=0):
    monkeypatch.setattr(repo, 'table_exists', lambda: exists)
    monkeypatch.setattr(repo, 'count_users', lambda: users)


def test_skips_when_not_local(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'none')
    monkeypatch.setattr(repo, 'table_exists',
                        lambda: pytest.fail('must not query in none mode'))

    assert bootstrap.ensure_initial_admin() is False


def test_skips_when_table_missing(monkeypatch):
    _patch_state(monkeypatch, exists=False)

    assert bootstrap.ensure_initial_admin() is False


def test_skips_when_users_already_exist(monkeypatch):
    _patch_state(monkeypatch, users=3)
    monkeypatch.setattr(service, 'create_user',
                        lambda *args, **kwargs: pytest.fail('must not create'))

    assert bootstrap.ensure_initial_admin() is False


def test_creates_admin_and_writes_0600_password_file(monkeypatch):
    _patch_state(monkeypatch, users=0)
    captured = {}
    monkeypatch.setattr(service, 'create_user',
                        lambda username, password, **kwargs: captured.update(
                            username=username, password=password, **kwargs) or USER)

    assert bootstrap.ensure_initial_admin() is True

    assert captured['username'] == 'admin'
    assert captured['password'] == 'configured-password-123'
    assert captured['role'] == 'admin'
    assert captured['must_change_password'] is True
    assert captured['allow_weak_password'] is True
    path = os.environ['RKB_ADMIN_PASSWORD_FILE']
    assert open(path, encoding='utf-8').read().strip() == 'configured-password-123'
    assert (os.stat(path).st_mode & 0o777) == 0o600


def test_must_change_can_be_disabled(monkeypatch):
    _patch_state(monkeypatch, users=0)
    monkeypatch.setenv('RKB_ADMIN_MUST_CHANGE', 'false')
    captured = {}
    monkeypatch.setattr(service, 'create_user',
                        lambda username, password, **kwargs: captured.update(kwargs) or USER)

    assert bootstrap.ensure_initial_admin() is True
    assert captured['must_change_password'] is False


def test_generates_a_random_password_when_env_is_empty(monkeypatch):
    _patch_state(monkeypatch, users=0)
    monkeypatch.setenv('RKB_ADMIN_PASSWORD', '')
    captured = {}
    monkeypatch.setattr(service, 'create_user',
                        lambda username, password, **kwargs: captured.update(
                            password=password, **kwargs) or USER)

    assert bootstrap.ensure_initial_admin() is True

    password = captured['password']
    assert len(password) >= 20
    assert captured['allow_weak_password'] is False
    path = os.environ['RKB_ADMIN_PASSWORD_FILE']
    assert open(path, encoding='utf-8').read().strip() == password


def test_create_failure_is_swallowed(monkeypatch):
    _patch_state(monkeypatch, users=0)

    def _raise(*args, **kwargs):
        raise RuntimeError('db gone')

    monkeypatch.setattr(service, 'create_user', _raise)

    assert bootstrap.ensure_initial_admin() is False


def test_store_unavailable_is_swallowed(monkeypatch):
    def _raise():
        raise AuthStoreUnavailable()

    monkeypatch.setattr(repo, 'table_exists', _raise)

    assert bootstrap.ensure_initial_admin() is False
