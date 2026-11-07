"""检索指标单测：每个函数用手算值钉死，避免「指标实现对了但口径漂了」。"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics import (  # noqa: E402
    dcg_at_k,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    normalize_groups,
    precision_at_k,
    precision_at_retrieved,
    recall_at_k,
    score_query,
)


def test_normalize_groups_dedupes_and_keeps_groups():
    assert normalize_groups(['b', 'a', ('c', 'd'), 'a']) == [('b',), ('a',), ('c', 'd')]
    assert normalize_groups(['a', ('a', 'b')]) == [('a',), ('b',)]


def test_hit_and_recall_basic():
    ranked = ['a', 'b', 'c']
    gold = {'b': 1}
    assert hit_at_k(ranked, gold, 1) == 0.0
    assert hit_at_k(ranked, gold, 2) == 1.0
    assert recall_at_k(ranked, gold, 2) == 1.0
    assert recall_at_k(['a', 'b'], {'b', 'c'}, 2) == 0.5


def test_precision_denominator_k_and_retrieved():
    ranked = ['a', 'b']
    gold = {'b': 1}
    assert precision_at_k(ranked, gold, 2) == 0.5
    assert precision_at_k(ranked, gold, 4) == 0.25
    assert precision_at_retrieved(ranked, gold, 4) == 0.5
    assert precision_at_retrieved([], gold, 4) == 0.0


def test_mrr_first_relevant_rank():
    assert mrr_at_k(['a', 'b', 'c'], {'b': 1}, 3) == 0.5
    assert mrr_at_k(['a', 'b', 'c'], {'c': 1}, 2) == 0.0
    assert mrr_at_k(['a', 'b', 'c'], {'a': 1}, 1) == 1.0


def test_ndcg_hand_computed():
    assert ndcg_at_k(['a', 'b'], {'b': 1}, 2) == pytest.approx(1 / math.log2(3))
    expected = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(['x', 'a', 'b'], {'a': 1, 'b': 1}, 3) == pytest.approx(expected)
    assert ndcg_at_k(['a', 'b'], {'a': 1, 'b': 3}, 2) == pytest.approx(
        (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3))
    )


def test_dcg_matches_ndcg_without_normalization():
    assert dcg_at_k(['a', 'b'], {'b': 1}, 2) == pytest.approx(1 / math.log2(3))


def test_group_counts_as_one_position_but_covers_all_gold():
    ranked = [('a', 'b'), 'c']
    gold = {'b': 1, 'c': 1}
    # 第 1 位就覆盖 b；第 2 位覆盖 c
    assert hit_at_k(ranked, gold, 1) == 1.0
    assert recall_at_k(ranked, gold, 1) == 0.5
    assert recall_at_k(ranked, gold, 2) == 1.0
    # 两个位置都命中，precision@2 = 1；组只占一个位置，不会把 c 挤到第 3 位
    assert precision_at_k(ranked, gold, 2) == 1.0
    assert mrr_at_k(ranked, gold, 2) == 1.0
    assert ndcg_at_k(ranked, gold, 2) == pytest.approx(1.0)


def test_group_gain_takes_max_not_sum():
    # 第 1 位组内相关度是 1 和 3，增益取 max=3；若错误求和会得到 4。
    # IDCG@1 取全局最高相关度 10，所以 NDCG=3/10（求和会得到 4/10）。
    ranked = [('a', 'b')]
    gold = {'a': 1, 'b': 3, 'c': 10}
    assert ndcg_at_k(ranked, gold, 1) == pytest.approx(3 / 10)


def test_duplicate_positions_do_not_double_count():
    assert recall_at_k(['a', 'a'], {'a': 1}, 2) == 1.0
    assert ndcg_at_k(['a', 'a'], {'a': 1}, 2) == 1.0


def test_no_gold_returns_none_not_zero():
    assert hit_at_k(['a'], {}, 1) is None
    assert recall_at_k(['a'], {}, 1) is None
    assert precision_at_k(['a'], {}, 1) is None
    assert mrr_at_k(['a'], {}, 1) is None
    assert ndcg_at_k(['a'], {}, 1) is None


def test_score_query_emits_metric_at_k_keys_only_for_present_gold():
    scores = score_query(['a', 'b'], {'b': 1}, ks=[1, 2])
    assert scores['hit@1'] == 0.0
    assert scores['hit@2'] == 1.0
    assert scores['recall@2'] == 1.0
    assert scores['mrr@2'] == 0.5
    assert score_query(['a'], {}, ks=[1]) == {}
