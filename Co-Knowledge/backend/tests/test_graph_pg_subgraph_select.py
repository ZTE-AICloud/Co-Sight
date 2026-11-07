"""子图边选择：检索场景按 BFS 层级优先，图详情分页仍按 id。"""
from graph.repository.graph_pg import _select_edge_ids


def test_default_keeps_id_order():
    levels = {5: 1, 2: 0, 9: 2}
    assert _select_edge_ids(levels, limit=2, offset=0, cursor_id=None,
                            prioritize_levels=False) == [2, 5]


def test_prioritize_levels_returns_near_seed_edges_first():
    levels = {1: 2, 2: 0, 3: 1, 4: 0}
    # 3 层、limit=3 → 每层先配额 1 条：level0 [2], level1 [3], level2 [1]
    assert _select_edge_ids(levels, limit=3, offset=0, cursor_id=None,
                            prioritize_levels=True) == [2, 3, 1]


def test_prioritize_levels_quota_keeps_deep_edges():
    levels = {i: 0 for i in range(100)}
    levels.update({1001: 1, 1002: 2})
    selected = _select_edge_ids(levels, limit=6, offset=0, cursor_id=None,
                                prioritize_levels=True)
    # 每层配额 2：level0 拿 2 条，level1/level2 各 1 条，余量按层序补
    assert len(selected) == 6
    assert 1001 in selected and 1002 in selected
    assert len([edge_id for edge_id in selected if edge_id < 1000]) == 4


def test_prioritize_levels_respects_offset_and_limit():
    levels = {1: 2, 2: 0, 3: 1, 4: 0}
    assert _select_edge_ids(levels, limit=1, offset=1, cursor_id=None,
                            prioritize_levels=True) == [4]


def test_cursor_pagination_falls_back_to_id_order():
    levels = {1: 2, 2: 0, 3: 1}
    assert _select_edge_ids(levels, limit=10, offset=0, cursor_id=1,
                            prioritize_levels=True) == [2, 3]
