"""At-rest encryption for credentials stored in the application database.

The format is shared by every credential column in this deployment::

    enc:v1:<base64(nonce(12B) + ciphertext + tag)>

``aad`` (associated data) binds a ciphertext to its column.  A value encrypted
for ``model_registry.api_key`` therefore cannot be decrypted as a Text2SQL
datasource credential even though both use the same key.

Key material (first match wins):

1. ``RKB_SECRET_KEY`` — 32-byte base64 or an arbitrary high-entropy passphrase
   (SHA-256 derived).  Multi-replica deployments must share this value.
2. ``RKB_SECRET_KEY_FILE`` — file containing the base64 key
   (default ``/data/rkb/secret.key``); generated with mode 0600 when missing.

Losing the key makes every ciphertext unrecoverable; keep it in the deployment
secret store rather than in the repository.
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
_DEFAULT_KEY_FILE = '/data/rkb/secret.key'

_key_cache: bytes | None = None
_lock = threading.Lock()


class SecretDecryptError(RuntimeError):
    """Ciphertext cannot be decrypted (wrong key or tampered payload)."""


def reset_cache() -> None:
    """Drop the process-local key cache (tests / key rotation)."""
    global _key_cache
    with _lock:
        _key_cache = None


def _derive(raw: str) -> bytes:
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


def encrypt(value: str | None, aad: bytes, *, label: str = 'secret') -> str:
    """Plaintext → ``enc:v1:...``; empty and already-encrypted values pass through."""
    if not value or is_encrypted(value):
        return value or ''
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_load_key()).encrypt(nonce, value.encode('utf-8'), aad)
    return PREFIX + base64.b64encode(nonce + ciphertext).decode('ascii')


def decrypt(value: str | None, aad: bytes, *, label: str = 'secret') -> str:
    """``enc:v1:...`` → plaintext; an unencrypted value is rejected."""
    if not value:
        return ''
    if not is_encrypted(value):
        raise SecretDecryptError(f'{label} 不是 enc:v1 密文')
    try:
        blob = base64.b64decode(value[len(PREFIX):], validate=True)
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not ciphertext:
            raise ValueError('truncated ciphertext')
        return AESGCM(_load_key()).decrypt(nonce, ciphertext, aad).decode('utf-8')
    except Exception as error:                                     # noqa: BLE001
        raise SecretDecryptError(
            f'{label} 解密失败：密钥不匹配或密文被篡改') from error
