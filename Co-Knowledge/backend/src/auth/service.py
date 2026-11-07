"""认证领域服务：登录、会话校验、改密、账号维护。

**不 import FastAPI**：HTTP 层（``api.py``）与 CLI（``cli.py``）共用这一份逻辑。
所有失败用 ``AuthError``（状态码 + 机器码）表达，由最外层决定响应形状。

单副本约束：登录限流是**进程内**的（与 ``agent/auth.py`` 的 Key 限流同一前提）。
RKB 本来就只能单副本（多轮会话缓存在进程内），部署多副本时这里要换成共享存储。
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from auth import passwords, repository as repo, sessions
from auth.errors import (AuthError, AuthStoreUnavailable, account_disabled,
                         auth_not_enabled, invalid_credentials,
                         invalid_current_password, invalid_email,
                         login_rate_limited, password_policy, session_expired,
                         unauthorized, user_not_found)
from auth.models import AuthUser

log = logging.getLogger(__name__)

KNOWN_AUTH_MODES = ('none', 'local', 'gateway')
DEFAULT_LOGIN_WINDOW_SECONDS = 15 * 60
DEFAULT_LOGIN_MAX_FAILURES = 5
DEFAULT_IP_MAX_FAILURES = 20
TOUCH_INTERVAL_SECONDS = 5 * 60
EXPIRED_SESSION_RETENTION = timedelta(days=7)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def auth_mode() -> str:
    """当前 ``AUTH_MODE``；未知取值直接抛错（启动期会先校验，见 ``validate_auth_mode``）。

    未显式设置时按 ``local`` 处理：直接 ``uvicorn`` / ``docker run`` 起的部署
    也必须先登录，不能静默变成无鉴权。需要关闭鉴权的场景必须显式写 ``AUTH_MODE=none``。
    """
    mode = (os.environ.get('AUTH_MODE') or 'local').strip().lower()
    if mode not in KNOWN_AUTH_MODES:
        raise RuntimeError(
            f'unknown AUTH_MODE={mode!r}; expected one of {KNOWN_AUTH_MODES}')
    return mode


def validate_auth_mode() -> str:
    """启动期校验；未知取值应当阻止服务启动，而不是静默变成无鉴权。"""
    return auth_mode()


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = (os.environ.get(name) or '').strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def login_window_seconds() -> int:
    return _int_env('RKB_AUTH_LOGIN_WINDOW_SECONDS',
                    DEFAULT_LOGIN_WINDOW_SECONDS, 60, 24 * 60 * 60)


def login_max_failures() -> int:
    return _int_env('RKB_AUTH_LOGIN_MAX_FAILURES',
                    DEFAULT_LOGIN_MAX_FAILURES, 1, 100)


def ip_max_failures() -> int:
    return _int_env('RKB_AUTH_LOGIN_IP_MAX_FAILURES',
                    DEFAULT_IP_MAX_FAILURES, 1, 1000)


# ---------------------------------------------------------------------------
# 进程内失败计数（滑动窗口）
# ---------------------------------------------------------------------------

class _SlidingWindowLimiter:
    """按 key 记录失败时间戳；只保留窗口内的事件。"""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _prune(events: deque[float], window: int, now: float) -> None:
        cutoff = now - window
        while events and events[0] <= cutoff:
            events.popleft()

    def retry_after(self, key: str, limit: int, window: int,
                    now: Optional[float] = None) -> int:
        """0 = 允许；>0 = 还需等待的秒数。"""
        current = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.setdefault(key, deque())
            self._prune(events, window, current)
            if len(events) < limit:
                return 0
            return max(1, int(math.ceil(events[0] + window - current)))

    def record_failure(self, key: str, window: int,
                       now: Optional[float] = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.setdefault(key, deque())
            self._prune(events, window, current)
            events.append(current)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        """测试用。"""
        with self._lock:
            self._events.clear()


_LIMITER = _SlidingWindowLimiter()

#: token_hash -> monotonic 时间，节流 last_seen_at 写入。
_touch_lock = threading.Lock()
_last_touch: dict[str, float] = {}


def reset_rate_limiter() -> None:
    """测试用：清空失败计数与 last_seen 节流状态。"""
    _LIMITER.clear()
    with _touch_lock:
        _last_touch.clear()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _now(value: Optional[datetime] = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current


def _login_key(login: str, ip: str) -> str:
    return f'login:{login.strip().lower()}:{ip}'


def _ip_key(ip: str) -> str:
    return f'login-ip:{ip}'


def _password_key(user_id: int) -> str:
    return f'password:{user_id}'


def _check_limit(key: str, limit: int, window: int) -> None:
    retry = _LIMITER.retry_after(key, limit, window)
    if retry:
        raise login_rate_limited(retry)


def _record_failure(login: str, ip: str, reason: str = 'bad_credentials') -> None:
    """记一次失败并写审计日志（**不记录口令**）。"""
    window = login_window_seconds()
    _LIMITER.record_failure(_login_key(login, ip), window)
    _LIMITER.record_failure(_ip_key(ip), window)
    log.warning('auth login failed user=%s ip=%s reason=%s',
                login or '<empty>', ip or '-', reason)


def _validate_email(email: Optional[str]) -> Optional[str]:
    value = (email or '').strip()
    if not value:
        return None
    if len(value) > 255 or '@' not in value or any(char.isspace() for char in value):
        raise invalid_email()
    return value


def _optional_user(token: str, now: Optional[datetime] = None) -> Optional[AuthUser]:
    """宽松版会话查询：任何失败都返回 None（给 ``/auth/status`` 用）。"""
    if not token:
        return None
    try:
        return validate_session(token, now=now, touch=False)
    except AuthError:
        return None
    except AuthStoreUnavailable:
        raise


# ---------------------------------------------------------------------------
# 登录 / 登出
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoginResult:
    user: AuthUser
    token: str
    expires_at: datetime


def login(username: str, password: str, *, ip: str = '',
          user_agent: str = '', now: Optional[datetime] = None) -> LoginResult:
    """校验口令并签发新会话。

    校验顺序：**先验密码、再看 enabled**。密码错误一律 ``invalid_credentials``，
    不泄露账号是否存在/被禁用；密码正确但禁用才 ``account_disabled``。
    """
    if auth_mode() != 'local':
        raise auth_not_enabled()

    current = _now(now)
    login_name = (username or '').strip()
    secret = password or ''

    window = login_window_seconds()
    max_failures = login_max_failures()
    max_ip_failures = ip_max_failures()

    _check_limit(_login_key(login_name, ip), max_failures, window)
    _check_limit(_ip_key(ip), max_ip_failures, window)

    if not login_name or not secret:
        passwords.verify_password(secret, passwords.DUMMY_HASH)
        _record_failure(login_name, ip, 'missing_credentials')
        raise invalid_credentials()

    row = repo.find_user_by_login(login_name)
    if row is None:
        passwords.verify_password(secret, passwords.DUMMY_HASH)
        _record_failure(login_name, ip, 'unknown_user')
        raise invalid_credentials()

    if not passwords.verify_password(secret, row.get('password_hash') or ''):
        _record_failure(login_name, ip, 'bad_password')
        raise invalid_credentials()

    if not row.get('enabled'):
        log.warning('auth login failed user=%s ip=%s reason=disabled',
                    row.get('username'), ip or '-')
        raise account_disabled()

    _LIMITER.reset(_login_key(login_name, ip))

    # 参数升级时顺手重哈希（best effort；失败不影响登录）。
    if passwords.needs_rehash(row.get('password_hash') or ''):
        try:
            repo.update_password(row['id'], passwords.hash_password(secret),
                                 must_change_password=bool(
                                     row.get('must_change_password')))
        except Exception:                                          # noqa: BLE001
            log.warning('auth rehash failed user=%s', row.get('username'))

    repo.touch_last_login(row['id'])

    token, token_hash = sessions.new_session_token()
    expires_at = current + timedelta(seconds=sessions.session_ttl_seconds())
    repo.create_session(
        user_id=row['id'], token_hash=token_hash, expires_at=expires_at,
        ip=ip, user_agent=user_agent,
    )

    try:
        repo.delete_expired_sessions(current - EXPIRED_SESSION_RETENTION)
    except Exception:                                              # noqa: BLE001
        log.warning('auth cleanup of expired sessions failed')

    user = AuthUser.from_row(row)
    log.info('auth login ok user=%s ip=%s', user.username, ip)
    return LoginResult(user=user, token=token, expires_at=expires_at)


def logout(token: str) -> None:
    """撤销会话；无 token / 表不可用都按成功处理（客户端仍会清 Cookie）。"""
    if not token:
        return
    try:
        repo.revoke_session(sessions.hash_token(token))
    except AuthStoreUnavailable:
        log.warning('auth logout with missing session table')
    except Exception:                                              # noqa: BLE001
        log.warning('auth logout failed')


# ---------------------------------------------------------------------------
# 会话校验
# ---------------------------------------------------------------------------

def validate_session(token: str, *, now: Optional[datetime] = None,
                     touch: bool = True) -> AuthUser:
    """校验会话并返回用户。失败抛 ``AuthError``。

    - 无 token / 查不到 → ``unauthorized``（401）
    - 已撤销 / 已过期 → ``session_expired``（401）
    - 用户被禁用 → 撤销该用户全部会话后 ``account_disabled``（403）
    """
    if not token:
        raise unauthorized()
    token_hash = sessions.hash_token(token)
    row = repo.find_session(token_hash)
    if row is None:
        raise unauthorized()

    current = _now(now)
    if row.get('revoked_at') is not None:
        raise session_expired()
    expires_at = row.get('expires_at')
    if expires_at is None:
        raise session_expired()
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if current >= expires_at:
        try:
            repo.revoke_session(token_hash)
        except Exception:                                          # noqa: BLE001
            pass
        raise session_expired()

    if not row.get('enabled'):
        try:
            repo.revoke_user_sessions(int(row['id']))
        except Exception:                                          # noqa: BLE001
            pass
        raise account_disabled()

    if touch:
        _maybe_touch(token_hash, int(row['session_id']), current)

    return AuthUser.from_row(row)


def _maybe_touch(token_hash: str, session_id: int, current: datetime) -> None:
    """按 token 节流更新 ``last_seen_at``（每 5 分钟最多一次，失败忽略）。"""
    stamp = current.timestamp()
    with _touch_lock:
        last = _last_touch.get(token_hash, 0.0)
        if stamp - last < TOUCH_INTERVAL_SECONDS:
            return
        _last_touch[token_hash] = stamp
    try:
        repo.touch_session(session_id)
    except Exception:                                              # noqa: BLE001
        pass


def current_user_or_none(token: str, *, now: Optional[datetime] = None,
                         touch: bool = False) -> Optional[AuthUser]:
    return _optional_user(token, now=now)


# ---------------------------------------------------------------------------
# 修改口令
# ---------------------------------------------------------------------------

def change_password(user: AuthUser, current_password: str, new_password: str, *,
                    current_token: str = '',
                    now: Optional[datetime] = None) -> None:
    """校验当前口令并更新；撤销该用户**其它**会话。"""
    if auth_mode() != 'local':
        raise auth_not_enabled()

    window = login_window_seconds()
    max_failures = login_max_failures()
    _check_limit(_password_key(user.id), max_failures, window)

    row = repo.get_user(user.id)
    if row is None:
        raise unauthorized()

    if not passwords.verify_password(current_password or '',
                                     row.get('password_hash') or ''):
        _LIMITER.record_failure(_password_key(user.id), window)
        raise invalid_current_password()

    if current_password and new_password == current_password:
        raise password_policy()

    try:
        passwords.validate_password(new_password or '')
    except passwords.PasswordPolicyError as error:
        raise password_policy() from error

    repo.update_password(user.id, passwords.hash_password(new_password),
                         must_change_password=False)

    keep = sessions.hash_token(current_token) if current_token else None
    try:
        repo.revoke_user_sessions(user.id, except_token_hash=keep)
    except Exception:                                              # noqa: BLE001
        log.warning('auth revoke other sessions failed user=%s', user.username)

    _LIMITER.reset(_password_key(user.id))
    _remove_bootstrap_password_file()
    log.info('auth password changed user=%s', user.username)


def _remove_bootstrap_password_file() -> None:
    """首次 admin 改密后删掉初始密码文件（best effort）。"""
    path = (os.environ.get('RKB_ADMIN_PASSWORD_FILE')
            or '/data/rkb/initial-admin-password')
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        log.warning('auth could not remove bootstrap password file: %s', path)


# ---------------------------------------------------------------------------
# 账号维护（CLI / bootstrap 共用）
# ---------------------------------------------------------------------------

def create_user(username: str, password: str, *,
                display_name: Optional[str] = None,
                email: Optional[str] = None,
                role: str = 'user',
                must_change_password: bool = False,
                allow_weak_password: bool = False) -> AuthUser:
    """建号。``allow_weak_password`` 只给 bootstrap 的运维引导口令用。

    常规建号（CLI / API）必须满足 8–128 位策略；bootstrap 在
    ``RKB_ADMIN_PASSWORD`` 显式设置时允许短口令（仍拒绝空/超长/控制字符），
    并在日志里给出 warning。这样运维可以用一个临时的 ``admin/admin`` 首次登录，
    再由 ``must_change_password`` 或 ``auth.cli reset-password`` 换成合规口令。
    """
    try:
        name = passwords.validate_username(username)
        if allow_weak_password:
            if (not isinstance(password, str) or not password.strip()
                    or len(password) > passwords.MAX_PASSWORD_LENGTH
                    or any(ord(char) < 0x20 for char in password)):
                raise passwords.PasswordPolicyError('invalid bootstrap password')
        else:
            passwords.validate_password(password)
    except passwords.PasswordPolicyError as error:
        raise password_policy() from error
    normalized_email = _validate_email(email)
    normalized_role = (role or 'user').strip().lower()
    if normalized_role not in {'user', 'admin'}:
        raise password_policy()

    row = repo.create_user(
        username=name, password_hash=passwords.hash_password(password),
        email=normalized_email,
        display_name=(display_name or '').strip() or None,
        role=normalized_role,
        must_change_password=must_change_password,
    )
    return AuthUser.from_row(row)


def reset_password(username: str, password: str, *,
                   must_change_password: bool = True) -> AuthUser:
    row = repo.find_user_by_username(username)
    if row is None:
        raise user_not_found()
    try:
        passwords.validate_password(password)
    except passwords.PasswordPolicyError as error:
        raise password_policy() from error
    repo.update_password(row['id'], passwords.hash_password(password),
                         must_change_password=must_change_password)
    repo.revoke_user_sessions(row['id'])
    _remove_bootstrap_password_file()
    return AuthUser.from_row(row)


def set_enabled(username: str, enabled: bool) -> AuthUser:
    row = repo.find_user_by_username(username)
    if row is None:
        raise user_not_found()
    repo.set_enabled(row['id'], enabled)
    if not enabled:
        repo.revoke_user_sessions(row['id'])
    updated = repo.get_user(row['id']) or row
    return AuthUser.from_row(updated)


def delete_user(username: str) -> None:
    row = repo.find_user_by_username(username)
    if row is None:
        raise user_not_found()
    repo.delete_user(row['id'])
