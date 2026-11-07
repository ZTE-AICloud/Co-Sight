"""``model_registry.api_key`` 的静态加密（AES-256-GCM）。

## 为什么

模型注册表里的 ``api_key`` 是真正的凭据。数据库备份、误导出的 dump、只读副本
都不应该直接泄露明文。加密后的格式：

    enc:v1:<base64(nonce(12B) + ciphertext + tag)>

所有写入都带前缀；读侧只接受带前缀的密文。

## 密钥从哪来

优先级：

1. ``RKB_SECRET_KEY`` 环境变量（推荐；多副本部署必须用同一个值）。
   可以给 32 字节的 base64，也可以给任意高熵口令（用 SHA-256 派生）。
2. ``RKB_SECRET_KEY_FILE`` 指向的文件（默认 ``/data/rkb/secret.key``）。
3. 文件不存在时**生成** 32 字节随机密钥并写入该文件（0600）。默认路径在
   ``rkb-storage`` 卷里，容器重建后仍在。

⚠️ 密钥丢失 = 已加密的 api_key 不可恢复。换密钥前先解密回明文，
或用 ``RKB_SECRET_KEY`` 固定密钥；不要把密钥文件提交进仓库。
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = 'enc:v1:'
_NONCE_BYTES = 12
_AAD = b'model_registry.api_key.v1'
_DEFAULT_KEY_FILE = '/data/rkb/secret.key'

_key_cache: bytes | None = None
_lock = threading.Lock()


class SecretDecryptError(RuntimeError):
    """密文无法解密（密钥不匹配 / 数据被篡改）。"""


def reset_cache() -> None:
    """清空进程内密钥缓存（测试/密钥轮换用）。"""
    global _key_cache
    with _lock:
        _key_cache = None


def _derive(raw: str) -> bytes:
    """32 字节 base64 直接用；其余按口令做 SHA-256 派生。"""
    candidate = raw.strip()
    try:
        decoded = base64.b64decode(candidate, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:                                              # noqa: BLE001
        pass
    return hashlib.sha256(candidate.encode('utf-8')).digest()


def _read_or_create_key_file(path: Path) -> bytes:
    if path.exists():
        return _derive(path.read_text(encoding='ascii').strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    try:
        path.write_text(base64.b64encode(key).decode('ascii'), encoding='ascii')
        os.chmod(path, 0o600)
    except OSError as error:
        raise RuntimeError(
            f'无法创建密钥文件 {path}：{error}。'
            '请设置 RKB_SECRET_KEY 或把 RKB_SECRET_KEY_FILE 指到可写路径。') from error
    return key


def _load_key() -> bytes:
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    with _lock:
        if _key_cache is not None:
            return _key_cache
        raw = (os.environ.get('RKB_SECRET_KEY') or '').strip()
        if raw:
            key = _derive(raw)
        else:
            path = Path(os.environ.get('RKB_SECRET_KEY_FILE') or _DEFAULT_KEY_FILE)
            key = _read_or_create_key_file(path)
        _key_cache = key
        return key


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(value: str | None) -> str:
    """明文 → ``enc:v1:...``；空值与已加密值原样返回（幂等）。"""
    if not value or is_encrypted(value):
        return value or ''
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_load_key()).encrypt(nonce, value.encode('utf-8'), _AAD)
    return PREFIX + base64.b64encode(nonce + ciphertext).decode('ascii')


def decrypt(value: str | None) -> str:
    """``enc:v1:...`` → 明文；空值返回空串，无前缀的值视为非法密文。"""
    if not value:
        return ''
    if not is_encrypted(value):
        raise SecretDecryptError('model_registry.api_key 不是 enc:v1 密文')
    try:
        blob = base64.b64decode(value[len(PREFIX):], validate=True)
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not ciphertext:
            raise ValueError('truncated ciphertext')
        return AESGCM(_load_key()).decrypt(nonce, ciphertext, _AAD).decode('utf-8')
    except Exception as error:                                     # noqa: BLE001
        raise SecretDecryptError(
            'model_registry.api_key 解密失败：密钥不匹配或密文被篡改') from error
