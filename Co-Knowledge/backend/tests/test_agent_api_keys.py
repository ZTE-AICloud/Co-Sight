"""Agent API Key 的生成/解析/哈希/校验单测（无 DB、无网络）。"""

from __future__ import annotations

import re

from agent import keys, schema


def test_generate_key_shape_and_prefix_roundtrip():
    full, prefix = keys.generate_key()

    assert re.fullmatch(r'ragk_[A-Za-z0-9_-]{8}_[A-Za-z0-9_-]{43}', full)
    assert prefix.startswith('ragk_')
    assert keys.key_prefix(full) == prefix


def test_key_prefix_handles_legacy_urlsafe_prefix_with_underscore():
    """回归：历史 token_urlsafe 前缀可能含 '_'，按 split 解析会截断。"""
    legacy = 'ragk_bJ_S2dCf_' + 'x' * 43
    assert keys.key_prefix(legacy) == 'ragk_bJ_S2dCf'


def test_key_prefix_rejects_malformed_keys():
    for value in ('', 'ragk', 'ragk_only', 'nope_abc_def', 'ragk__secret', None):
        assert keys.key_prefix(value) is None


def test_hash_is_hmac_sha256_and_verify_is_constant_time_equivalent():
    full, _ = keys.generate_key()
    digest = keys.hash_key(full, 'pepper-1')

    assert len(digest) == 64
    assert keys.verify_key(full, digest, 'pepper-1') is True
    assert keys.verify_key(full + 'x', digest, 'pepper-1') is False
    assert keys.verify_key(full, digest, 'pepper-2') is False


def test_hash_key_requires_non_empty_pepper():
    full, _ = keys.generate_key()
    try:
        keys.hash_key(full, '')
    except ValueError as error:
        assert 'RKB_AGENT_KEY_PEPPER' in str(error)
    else:  # pragma: no cover - 明确失败比断言消息更重要
        raise AssertionError('empty pepper must be rejected')


def test_schema_declares_table_and_unique_prefix_index():
    ddl = '\n'.join(schema.SCHEMA_STATEMENTS)

    assert 'CREATE TABLE IF NOT EXISTS public.agent_api_key' in ddl
    assert 'key_prefix' in ddl
    assert 'key_hash' in ddl
    assert 'scopes             text[]' in ddl
    assert 'agent_api_key_prefix_uidx' in ddl
