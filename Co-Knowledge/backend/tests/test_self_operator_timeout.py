"""算子沙箱超时解析：函数级覆盖只影响目标函数。"""

from ingestion.utility import self_operator


def test_graph_extract_timeout_can_be_raised_without_touching_split(monkeypatch):
    monkeypatch.delenv('OPERATOR_TIMEOUT_SECONDS', raising=False)
    monkeypatch.setenv('OPERATOR_GRAPH_EXTRACT_TIMEOUT_SECONDS', '3600')

    assert self_operator._resolve_timeout('graph_extract', None) == 3600
    # 切分/解析仍走各自默认值，避免把全局超时一起放大。
    assert self_operator._resolve_timeout('file_parse', None) == 600
    assert self_operator._resolve_timeout('file_split', None) == 300


def test_explicit_timeout_wins_over_env(monkeypatch):
    monkeypatch.setenv('OPERATOR_GRAPH_EXTRACT_TIMEOUT_SECONDS', '3600')

    assert self_operator._resolve_timeout('graph_extract', 900) == 900


def test_global_timeout_still_works(monkeypatch):
    monkeypatch.delenv('OPERATOR_GRAPH_EXTRACT_TIMEOUT_SECONDS', raising=False)
    monkeypatch.setenv('OPERATOR_TIMEOUT_SECONDS', '1200')

    assert self_operator._resolve_timeout('graph_extract', None) == 1200
    assert self_operator._resolve_timeout('file_parse', None) == 1200
