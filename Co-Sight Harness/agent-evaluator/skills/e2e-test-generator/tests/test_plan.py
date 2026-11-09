#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_plan.py — S2 纯代码计数逻辑：权重、优先级、GWT 截断、配额分配。"""

import pytest

import config
import plan

TAGS = {
    1: "functional", 2: "functional", 3: "safety", 4: "failure",
    5: "instruction", 6: "functional", 7: "safety",
}


def make_gwts(count=7):
    return [
        {"index": i, "title": f"GWT{i}", "given": f"g{i}", "when": "", "then": ""}
        for i in range(1, count + 1)
    ]


# ============================== 权重与优先级 ==============================

def test_base_weights_unchanged_without_focus():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    assert weights["functional"] == 3
    assert weights["safety"] == 2


def test_focus_adds_bonus_only_to_matched():
    weights = plan.apply_focus(config.DIMENSION_IDS, ["safety", "failure"])
    assert weights["safety"] == 2 + config.FOCUS_WEIGHT_BONUS
    assert weights["failure"] == 2 + config.FOCUS_WEIGHT_BONUS
    assert weights["functional"] == 3          # 未被 focus 命中
    assert weights["boundary"] == 2


def test_priority_is_weight_desc_then_id_asc():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    assert plan.priority_order(weights)[:2] == ["functional", "tool_use"]
    # 权重相同者按 id 字典序
    tail = plan.priority_order(weights)[2:]
    assert tail == sorted(tail)


# ============================== GWT 截断 ==============================

def test_truncate_count5_drops_low_weight_dimension():
    """count=5 时按维度优先级截断：functional(3) 全保，safety 被挤掉。"""
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    kept, dropped = plan.truncate_gwts(make_gwts(), TAGS, 5, weights)

    assert len(kept) == 5
    assert [g["index"] for g in dropped] == [3, 7]
    # 保留顺序 = 维度优先级降序，维度内原序
    assert [g["index"] for g in kept] == [1, 2, 6, 4, 5]


def test_truncate_focus_rescues_dropped_gwts():
    """focus 抬升 safety/failure/instruction 后，③④⑤⑦ 应当被保住。"""
    weights = plan.apply_focus(
        config.DIMENSION_IDS, ["safety", "failure", "instruction"]
    )
    kept, dropped = plan.truncate_gwts(make_gwts(), TAGS, 5, weights)
    kept_indexes = [g["index"] for g in kept]

    assert set([3, 4, 5, 7]).issubset(set(kept_indexes))
    assert len(kept) == 5


def test_truncate_no_drop_when_count_covers_all():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    kept, dropped = plan.truncate_gwts(make_gwts(), TAGS, 10, weights)
    assert len(kept) == 7
    assert dropped == []


def test_truncate_unknown_dimension_falls_back_to_lowest_priority():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    kept, _ = plan.truncate_gwts(make_gwts(1), {}, 5, weights)
    assert kept[0]["dimension"] == plan.priority_order(weights)[-1]


# ============================== 配额分配 ==============================

def test_allocate_budget_ge_dims_gives_one_each_to_top_weighted():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    quota = plan.allocate(6, weights)
    assert all(v == 1 for v in quota.values())
    assert sum(quota.values()) == 6


def test_allocate_budget_lt_dims_takes_top_weighted_only():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    quota = plan.allocate(3, weights)
    assert sum(quota.values()) == 3
    assert quota["functional"] == 1 and quota["tool_use"] == 1
    assert quota["boundary"] == 1
    assert quota["safety"] == 0 and quota["failure"] == 0


def test_allocate_larger_budget_round_robins_by_priority():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    quota = plan.allocate(10, weights)
    assert sum(quota.values()) == 10
    # 高权重维度先拿余数
    assert quota["functional"] >= quota["safety"]


def test_allocate_zero_budget_is_all_zero():
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    assert set(plan.allocate(0, weights).values()) == {0}


@pytest.mark.parametrize("budget", list(range(0, 21)))
def test_allocate_always_sums_to_budget(budget):
    """防 off-by-one：任意预算下 Σquota 必须恰好等于预算。"""
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    assert sum(plan.allocate(budget, weights).values()) == budget


# ============================== 端到端配额不变量 ==============================

@pytest.mark.parametrize("count", [5, 7, 10, 20])
def test_kept_gwt_plus_quota_equals_count(count):
    """核心不变量：GWT 保留数 + Σ生成配额 == count。"""
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    kept, _ = plan.truncate_gwts(make_gwts(), TAGS, count, weights)
    quota = plan.allocate(count - len(kept), weights)
    assert len(kept) + sum(quota.values()) == count


@pytest.mark.parametrize("count", [5, 10, 20])
def test_invariant_holds_with_focus(count):
    weights = plan.apply_focus(
        config.DIMENSION_IDS, ["safety", "failure", "instruction"]
    )
    kept, _ = plan.truncate_gwts(make_gwts(), TAGS, count, weights)
    quota = plan.allocate(count - len(kept), weights)
    assert len(kept) + sum(quota.values()) == count


# ============================== 配额语义（生成目标） ==============================

def test_quota_excludes_gwt_from_budget():
    """GWT 预占 count，但不消耗生成预算：budget = count - |kept_gwt|。"""
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    kept, _ = plan.truncate_gwts(make_gwts(), TAGS, 10, weights)
    assert len(kept) == 7
    assert 10 - len(kept) == 3


def test_zero_budget_when_gwt_fills_count():
    """count <= |GWT| 时预算为 0，全部配额为 0（不应产生任何批次）。"""
    weights = plan.apply_focus(config.DIMENSION_IDS, [])
    kept, _ = plan.truncate_gwts(make_gwts(), TAGS, 6, weights)
    quota = plan.allocate(6 - len(kept), weights)
    assert len(kept) == 6
    assert sum(quota.values()) == 0
