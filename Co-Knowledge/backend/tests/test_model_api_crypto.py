"""``model_registry.api_key`` 静态加密（AES-256-GCM）。"""

from __future__ import annotations

import base64

import pytest

from model import crypto
from model.repository_pg import _row_to_record, _update_params, _insert_params
from model.models import ModelRecord


@pytest.fixture(autouse=True)
def _fresh_key(monkeypatch):
    monkeypatch.setenv('RKB_SECRET_KEY', 'unit-test-secret')
    monkeypatch.delenv('RKB_SECRET_KEY_FILE', raising=False)
    crypto.reset_cache()
    yield
    crypto.reset_cache()


def test_round_trip_and_prefix():
    value = 'sk-live-123456'
    encrypted = crypto.encrypt(value)

    assert encrypted.startswith(crypto.PREFIX)
    assert value not in encrypted
    assert crypto.decrypt(encrypted) == value


def test_empty_passes_through_and_plaintext_is_rejected():
    assert crypto.encrypt('') == ''
    assert crypto.decrypt('') == ''
    with pytest.raises(crypto.SecretDecryptError):
        crypto.decrypt('not-encrypted')


def test_encrypt_is_idempotent():
    encrypted = crypto.encrypt('sk-1')
    assert crypto.encrypt(encrypted) == encrypted


def test_tampered_ciphertext_raises():
    encrypted = crypto.encrypt('sk-tamper')
    blob = encrypted[len(crypto.PREFIX):]
    raw = bytearray(base64.b64decode(blob))
    raw[-1] ^= 0xFF
    tampered = crypto.PREFIX + base64.b64encode(bytes(raw)).decode()

    with pytest.raises(crypto.SecretDecryptError):
        crypto.decrypt(tampered)


def test_key_file_is_created_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv('RKB_SECRET_KEY', raising=False)
    key_file = tmp_path / 'secret.key'
    monkeypatch.setenv('RKB_SECRET_KEY_FILE', str(key_file))
    crypto.reset_cache()

    encrypted = crypto.encrypt('sk-file')

    assert key_file.exists()
    assert oct(key_file.stat().st_mode & 0o777) == '0o600'
    # 新进程/清缓存后用同一文件能解开
    crypto.reset_cache()
    assert crypto.decrypt(encrypted) == 'sk-file'


def test_store_mapping_decrypts_and_encrypts():
    record = ModelRecord(
        model_id='id-1', model_kind='llm', model_name='m', base_url='http://gw/v1',
        api_key='sk-store')
    row = {
        'model_id': 'id-1', 'model_kind': 'llm', 'model_name': 'm', 'base_url': 'http://gw/v1',
        'api_key': crypto.encrypt('sk-store'), 'source': 'user',
    }
    assert _row_to_record(row).api_key == 'sk-store'
    # 写路径参数里是密文，不能出现明文
    assert 'sk-store' not in _insert_params(record)
    assert 'sk-store' not in _update_params(record)
    assert any(str(value).startswith(crypto.PREFIX) for value in _insert_params(record))
