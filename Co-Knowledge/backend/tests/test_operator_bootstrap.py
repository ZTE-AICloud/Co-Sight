"""内置算子播种测试（不连 DB）。

播种解决的问题：``/operators?module=graph_extract`` 只读 ``operator`` 表，新装库
是空的，「新建知识图谱」页就没有算子可选。必须钉住的性质：

1. 两个内置算子都按内部 id（-6 通用 / -5 专业）播种，``system=true``；
2. 已存在的不重复导入（重启幂等，且只补缺位的那一个）；
3. 导入失败 → 只记日志，不能阻断服务启动。
"""

from __future__ import annotations

import pytest

from operators import bootstrap
from operators.repository import operator_store
from operators.service import operator_service


def _fake_import(calls, *, raise_for=None):
    def fake(filename, content, emp_no, org_id, lang, *, operator_id=None, system=False):
        calls.append({'filename': filename, 'size': len(content), 'id': operator_id,
                      'system': system, 'emp_no': emp_no})
        if raise_for is not None and operator_id == raise_for:
            raise RuntimeError('db down')
        return {'id': operator_id, 'name': filename}

    return fake


def test_seeds_both_builtin_graph_operators(monkeypatch):
    # Arrange
    calls = []
    monkeypatch.setattr(operator_store, 'select_by_id', lambda operator_id: None)
    monkeypatch.setattr(operator_service, 'import_operator', _fake_import(calls))

    # Act
    seeded = bootstrap.ensure_default_operators()

    # Assert
    assert [row['id'] for row in seeded] == [-6, -5]
    assert [call['filename'] for call in calls] == [
        'general-graph-extract.zip', 'professional-graph-extract.zip']
    assert all(call['system'] for call in calls), '内置算子必须 system=true'
    assert all(call['size'] > 0 for call in calls), '导入的必须是真实算子包'
    assert all(call['emp_no'] == bootstrap.SEEDED_BY for call in calls)


def test_skips_operators_that_already_exist(monkeypatch):
    # Arrange
    monkeypatch.setattr(operator_store, 'select_by_id', lambda operator_id: {'id': operator_id})
    monkeypatch.setattr(operator_service, 'import_operator',
                        lambda *args, **kwargs: pytest.fail('must not import existing operators'))

    # Act / Assert
    assert bootstrap.ensure_default_operators() == []


def test_only_the_missing_operator_is_seeded(monkeypatch):
    # Arrange
    calls = []
    monkeypatch.setattr(operator_store, 'select_by_id',
                        lambda operator_id: {'id': -6} if operator_id == -6 else None)
    monkeypatch.setattr(operator_service, 'import_operator', _fake_import(calls))

    # Act
    seeded = bootstrap.ensure_default_operators()

    # Assert
    assert [row['id'] for row in seeded] == [-5]
    assert [call['filename'] for call in calls] == ['professional-graph-extract.zip']


def test_import_failure_is_logged_and_does_not_block_startup(monkeypatch, caplog):
    # Arrange
    calls = []
    monkeypatch.setattr(operator_store, 'select_by_id', lambda operator_id: None)
    monkeypatch.setattr(operator_service, 'import_operator',
                        _fake_import(calls, raise_for=-6))

    # Act
    seeded = bootstrap.ensure_default_operators()

    # Assert：-6 失败不影响 -5
    assert [row['id'] for row in seeded] == [-5]
    assert 'failed to seed default operator' in caplog.text
