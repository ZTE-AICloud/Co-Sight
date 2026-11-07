"""登录会话的 token、Cookie 与请求来源工具（不 import FastAPI）。

会话 token 是 32 字节高熵随机串（``secrets.token_urlsafe(32)``），库里只存
SHA-256 十六进制。高熵值不需要 HMAC/pepper：即使库泄露，也无法从哈希反推 token；
不用慢哈希是因为每次请求都要校验，慢哈希会把 API 拖垮。
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Mapping, Optional
from urllib.parse import urlsplit

COOKIE_NAME = 'ragstudio_session'
DEFAULT_TTL_SECONDS = 12 * 60 * 60
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 30 * 24 * 60 * 60

_TRUE = {'1', 'true', 'yes', 'on'}
_FALSE = {'0', 'false', 'no', 'off'}


def session_ttl_seconds() -> int:
    """``RKB_AUTH_SESSION_TTL_SECONDS``，越界钳制到 [60s, 30d]。"""
    raw = (os.environ.get('RKB_AUTH_SESSION_TTL_SECONDS') or '').strip()
    try:
        value = int(raw) if raw else DEFAULT_TTL_SECONDS
    except ValueError:
        value = DEFAULT_TTL_SECONDS
    return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, value))


def new_session_token() -> tuple[str, str]:
    """返回 ``(plain_token, sha256_hex)``；明文只出现在 Set-Cookie 里。"""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()


def cookie_secure_override() -> Optional[bool]:
    """``RKB_AUTH_COOKIE_SECURE=auto|true|false``；无法识别时按 auto。"""
    raw = (os.environ.get('RKB_AUTH_COOKIE_SECURE') or 'auto').strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


def is_secure_request(scheme: str, forwarded_proto: str = '',
                      override: Optional[bool] = None) -> bool:
    """决定 Cookie 是否加 ``Secure``。

    ``X-Forwarded-Proto`` 由 nginx 用 ``$scheme`` 覆盖写（不是追加），可取首值。
    HTTP 部署误设 ``Secure`` 会让浏览器直接丢弃 Cookie → 登录循环，所以默认 auto。
    """
    if override is not None:
        return override
    if (scheme or '').lower() == 'https':
        return True
    first = (forwarded_proto or '').split(',')[0].strip().lower()
    return first == 'https'


def build_session_cookie(token: str, max_age: int, secure: bool) -> str:
    parts = [
        f'{COOKIE_NAME}={token}',
        'Path=/',
        'HttpOnly',
        'SameSite=Lax',
        f'Max-Age={max(0, int(max_age))}',
    ]
    if secure:
        parts.append('Secure')
    return '; '.join(parts)


def clear_session_cookie(secure: bool) -> str:
    parts = [
        f'{COOKIE_NAME}=',
        'Path=/',
        'HttpOnly',
        'SameSite=Lax',
        'Max-Age=0',
    ]
    if secure:
        parts.append('Secure')
    return '; '.join(parts)


def extract_session_token(cookies: Mapping[str, str]) -> str:
    return str((cookies or {}).get(COOKIE_NAME) or '').strip()


def client_ip(headers: Mapping[str, str], fallback: str = '') -> str:
    """真实客户端 IP。

    nginx 用 ``proxy_set_header X-Real-IP $remote_addr`` 覆盖写；``X-Forwarded-For``
    是 ``$proxy_add_x_forwarded_for`` **追加**，首个值可能是客户端伪造的，不能用。
    """
    real = str((headers or {}).get('x-real-ip') or '').split(',')[0].strip()
    value = real or (fallback or '').strip()
    return value[:64]


def _request_host(headers: Mapping[str, str]) -> str:
    forwarded = str((headers or {}).get('x-forwarded-host') or '').split(',')[0].strip()
    return (forwarded or str((headers or {}).get('host') or '')).lower()


def origin_allowed(headers: Mapping[str, str], *, required: bool) -> bool:
    """CSRF 纵深：``Origin`` / ``Referer`` 的 host 必须等于当前 ``Host``。

    - 两者都没有：``required=True`` 时拒绝（已带会话 Cookie 的 unsafe 请求），
      ``required=False`` 时放行（登录前没有 Cookie；curl/脚本可登录）；
    - 有值但 host 对不上（含 ``Origin: null``）：一律拒绝；
    - 只比较 host:port，不比较 scheme —— 反向代理终止 TLS 时，后端看到的
      scheme 与浏览器不一致是常态。
    """
    expected = _request_host(headers)
    origin = str((headers or {}).get('origin') or '').strip()
    referer = str((headers or {}).get('referer') or '').strip()
    if origin:
        if origin.lower() == 'null':
            return False
        try:
            actual = urlsplit(origin).netloc.lower()
        except ValueError:
            return False
        return bool(expected) and actual == expected
    if referer:
        try:
            actual = urlsplit(referer).netloc.lower()
        except ValueError:
            return False
        return bool(expected) and actual == expected
    return not required
