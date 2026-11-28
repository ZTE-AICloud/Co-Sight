"""``model_registry.api_key`` 的静态加密（AES-256-GCM）。

实现与密钥来源统一在 :mod:`infrastructure.secrets.box`；本模块只把 AAD 绑定到
``model_registry.api_key``，并保留原有公开函数（``PREFIX`` / ``SecretDecryptError``
/ ``reset_cache`` / ``encrypt`` / ``decrypt``）供既有调用方使用。
"""

from __future__ import annotations

from infrastructure.secrets import box

PREFIX = box.PREFIX
SecretDecryptError = box.SecretDecryptError

_AAD = b'model_registry.api_key.v1'
_LABEL = 'model_registry.api_key'


def reset_cache() -> None:
    """清空进程内密钥缓存（测试/密钥轮换用）。"""
    box.reset_cache()


def is_encrypted(value: str | None) -> bool:
    return box.is_encrypted(value)


def encrypt(value: str | None) -> str:
    """明文 → ``enc:v1:...``；空值与已加密值原样返回（幂等）。"""
    return box.encrypt(value, _AAD, label=_LABEL)


def decrypt(value: str | None) -> str:
    """``enc:v1:...`` → 明文；空值返回空串，无前缀的值视为非法密文。"""
    return box.decrypt(value, _AAD, label=_LABEL)
