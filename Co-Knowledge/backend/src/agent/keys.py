"""Agent API Key 的生成与校验（纯标准库）。

格式：``ragk_<8 位前缀>_<43 位 secret>``
- 前缀用于按索引查表（``key_prefix`` 唯一）；
- 库里只存 ``HMAC-SHA256(pepper, full_key)``，明文只在创建时输出一次；
- secret 是 ``secrets.token_urlsafe(32)``，熵足够高，不需要 bcrypt/argon2 这类慢哈希
  （慢哈希是给低熵口令用的；这里用 HMAC 防止库泄露后被离线比对即可）。

**pepper 缺失时 fail-closed**：``hash_key`` 直接抛 ``ValueError``；
调用方（CLI / auth）必须先检查 ``RKB_AGENT_KEY_PEPPER`` 并给出明确错误，
不允许用空 pepper 静默放行。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Optional

#: 便于人眼识别这是 Knowledge Studio 的 Key
KEY_MARKER = 'ragk'
#: 前缀用 **hex**（8 个字符，不含 ``_``）；secret 用 urlsafe（43 个字符）。
#: 前缀不能用 ``token_urlsafe``：它会产出 ``_``，而解析按 ``_`` 切分，
#: 会把 ``ragk_bJ_S2dCf`` 截成 ``ragk_bJ`` → 查表查不到 → REST/MCP 恒 401。
#: 生成用 hex，解析用**定长**。
PREFIX_TOKEN_BYTES = 4
PREFIX_TOKEN_LENGTH = PREFIX_TOKEN_BYTES * 2
SECRET_TOKEN_BYTES = 32


def generate_key() -> tuple[str, str]:
    """返回 ``(full_key, key_prefix)``。"""
    prefix = f'{KEY_MARKER}_{secrets.token_hex(PREFIX_TOKEN_BYTES)}'
    secret = secrets.token_urlsafe(SECRET_TOKEN_BYTES)
    return f'{prefix}_{secret}', prefix


def key_prefix(full_key: str) -> Optional[str]:
    """从完整 Key 解析出查表前缀；格式不对返回 ``None``。

    前缀是**定长**的：``ragk_`` + 8 个字符。用定长切片而不是 ``split('_')``，
    这样 secret 里的 ``_`` 不会影响结果。
    """
    value = (full_key or '').strip()
    marker = KEY_MARKER + '_'
    if not value.startswith(marker):
        return None
    prefix_end = len(marker) + PREFIX_TOKEN_LENGTH
    if len(value) <= prefix_end + 1:
        return None
    if value[prefix_end] != '_':
        return None
    return value[:prefix_end]


_KEY_PREFIX_PATTERN = re.compile(r'^ragk_[0-9a-f]{8}$')


def is_key_prefix(value: str) -> bool:
    """``value`` 是否是合法的前缀（``ragk_`` + 8 位 hex）。"""
    return bool(value and _KEY_PREFIX_PATTERN.fullmatch(value))


def hash_key(full_key: str, pepper: str) -> str:
    """``HMAC-SHA256(pepper, full_key)`` 的小写十六进制。"""
    if not pepper:
        raise ValueError('RKB_AGENT_KEY_PEPPER is required')
    return hmac.new(pepper.encode('utf-8'), full_key.encode('utf-8'),
                    hashlib.sha256).hexdigest()


def verify_key(full_key: str, expected_hash: str, pepper: str) -> bool:
    """常量时间比较；格式/pepper 问题一律返回 ``False``（由调用方给 401/503）。"""
    try:
        actual = hash_key(full_key, pepper)
    except ValueError:
        return False
    return hmac.compare_digest(actual, (expected_hash or '').strip().lower())
