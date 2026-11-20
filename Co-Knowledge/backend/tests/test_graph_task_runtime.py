"""图谱两条任务链路的车道接线。

只验证「提交走统一引擎、两条车道各自独立」，不重复测引擎本身的行为
（那部分在 ``test_task_engine.py``）。
"""

from __future__ import annotations

from graph import task_runtime


def test_graph_lanes_are_registered_separately():
    stats = task_runtime.stats()

    assert set(stats) == {'graph_extract', 'graph_import'}
    assert stats['graph_extract'].workers == 5
    assert stats['graph_import'].workers == 5


def test_submit_extract_delegates_to_engine(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_runtime._ENGINE, 'submit',
        lambda kind, payload, **kwargs: calls.append((kind, payload, kwargs)) or 'task-1')

    task_id = task_runtime.submit_extract({'tmpDir': '/tmp/x'}, task_id='task-1')

    assert task_id == 'task-1'
    assert calls[0][0] == 'graph_extract'
    assert calls[0][1] == {'tmpDir': '/tmp/x'}
    assert calls[0][2]['create_row'] is False


def test_submit_import_delegates_to_engine(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_runtime._ENGINE, 'submit',
        lambda kind, payload, **kwargs: calls.append((kind, payload, kwargs)) or 'task-2')

    task_id = task_runtime.submit_import({'zipPath': '/tmp/x.zip'}, task_id='task-2')

    assert task_id == 'task-2'
    assert calls[0][0] == 'graph_import'
    assert calls[0][1] == {'zipPath': '/tmp/x.zip'}
    assert calls[0][2]['create_row'] is False
