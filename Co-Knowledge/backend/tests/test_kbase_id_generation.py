"""新库 kbaseId 生成测试。

新库用 16 位十六进制（64 bit），历史库的 32 位 uuid 不迁移；生成时必须查重。
"""

import re

import pytest

from knowledge_base.repository import kbase as kbase_store  # noqa: E402


class _FakeCursor:
    def __init__(self, results):
        self._results = iter(results)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.last_params = params

    def fetchone(self):
        return next(self._results)


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor


def test_candidate_is_16_hex():
    candidate = kbase_store.new_kbase_id_candidate()
    assert len(candidate) == kbase_store.KBASE_ID_HEX_LENGTH == 16
    assert re.fullmatch(rf'[0-9a-f]{{{kbase_store.KBASE_ID_HEX_LENGTH}}}', candidate)


def test_generate_kbase_id_retries_on_collision(monkeypatch):
    candidates = iter(['a' * 16, 'b' * 16])
    monkeypatch.setattr(kbase_store, 'new_kbase_id_candidate', lambda: next(candidates))
    cursor = _FakeCursor([(1,), None])          # 第一个候选撞号，第二个可用
    monkeypatch.setattr(kbase_store, 'connection', lambda: _FakeConnection(cursor))

    assert kbase_store.generate_kbase_id() == 'b' * 16


def test_generate_kbase_id_raises_after_max_attempts(monkeypatch):
    monkeypatch.setattr(kbase_store, 'new_kbase_id_candidate', lambda: 'a' * 16)
    cursor = _FakeCursor([(1,)] * kbase_store._KBASE_ID_MAX_ATTEMPTS)
    monkeypatch.setattr(kbase_store, 'connection', lambda: _FakeConnection(cursor))

    with pytest.raises(RuntimeError):
        kbase_store.generate_kbase_id()
