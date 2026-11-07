"""口令哈希与策略（纯标准库）。

为什么用 ``hashlib.scrypt`` 而不是 bcrypt/argon2：

- 运行环境只保证标准库；``cryptography`` 已在依赖里，但它不做口令 KDF 的便捷封装；
- scrypt 是内存硬的慢哈希，参数可按 OWASP 建议（n=2^14, r=8, p=1）；
- 存成带参数的 PHC 风格串，将来调参/换算法时能按行识别并逐步重哈希。

Agent API Key 用 HMAC 而不是慢哈希（见 ``agent/keys.py``），因为那是 32 字节随机
secret；用户口令是低熵的，必须用慢哈希，两者不要混用。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

#: OWASP 建议的最低档（约 16 MiB 内存、~50ms）。测试与容器内都可用。
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16

#: 防御性上限：即使库里的 hash 串被改坏，也不让一次 verify 吃掉无限 CPU/内存。
_MAX_N = 2 ** 20
_MAX_R = 32
_MAX_P = 16

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 64
USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.@-]+$')


class PasswordPolicyError(ValueError):
    """口令/用户名不符合策略。调用方翻成 422 ``password_policy``。"""


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode('ascii')


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode('ascii'), validate=True)


def hash_password(password: str) -> str:
    """返回 ``scrypt$n$r$p$<b64salt>$<b64dk>``。每次调用生成新盐。"""
    if not isinstance(password, str) or not password:
        raise PasswordPolicyError('password is required')
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode('utf-8'), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_DKLEN, maxmem=SCRYPT_MAXMEM,
    )
    return (f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}'
            f'${_b64encode(salt)}${_b64encode(derived)}')


def _parse(stored: str) -> tuple[int, int, int, bytes, bytes]:
    """解析并校验参数；任何异常都收口为 ``ValueError``。"""
    if not isinstance(stored, str):
        raise ValueError('stored hash must be a string')
    parts = stored.split('$')
    if len(parts) != 6 or parts[0] != 'scrypt':
        raise ValueError('unsupported password hash format')
    n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
    if not (2 <= n <= _MAX_N) or n & (n - 1):
        raise ValueError('invalid scrypt n')
    if not (1 <= r <= _MAX_R) or not (1 <= p <= _MAX_P):
        raise ValueError('invalid scrypt r/p')
    salt = _b64decode(parts[4])
    expected = _b64decode(parts[5])
    if len(salt) < 8 or len(expected) < 16:
        raise ValueError('invalid scrypt salt/dk length')
    return n, r, p, salt, expected


def verify_password(password: str, stored: str) -> bool:
    """常量时间校验；格式非法/参数越界一律 False（不抛异常）。"""
    if not isinstance(password, str) or not password:
        return False
    try:
        n, r, p, salt, expected = _parse(stored)
    except (ValueError, TypeError):
        return False
    try:
        actual = hashlib.scrypt(
            password.encode('utf-8'), salt=salt,
            n=n, r=r, p=p, dklen=len(expected), maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    """当前参数低于默认值时返回 True（登录成功后可按需重哈希）。"""
    try:
        n, r, p, _salt, _expected = _parse(stored)
    except (ValueError, TypeError):
        return True
    return (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)


def validate_username(username: str) -> str:
    """规范化并校验用户名；返回去掉首尾空白的值。"""
    value = (username or '').strip()
    if not (USERNAME_MIN_LENGTH <= len(value) <= USERNAME_MAX_LENGTH):
        raise PasswordPolicyError('username length')
    if not USERNAME_PATTERN.fullmatch(value):
        raise PasswordPolicyError('username characters')
    return value


def validate_password(password: str) -> str:
    """校验口令长度；不强制大小写/符号组合（长度优先，避免无意义的复杂度规则）。"""
    if not isinstance(password, str) or not password.strip():
        raise PasswordPolicyError('password is required')
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError('password too short')
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError('password too long')
    if any(ord(char) < 0x20 for char in password):
        raise PasswordPolicyError('password contains control characters')
    return password


#: 未知用户也跑一次同参数的 verify，避免用响应时间枚举账号。
DUMMY_HASH = hash_password('dummy-password-for-timing-equalization')
