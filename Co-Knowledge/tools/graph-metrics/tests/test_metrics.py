"""指标单测：每个口径用手算值钉死，避免实现对了但口径漂了。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics import (  # noqa: E402
    aggregate,
    bootstrap_ci,
    evaluate_retrieval,
    normalize_entity,
    percentile,
    reachable_entities,
)


def test_normalize_entity_collapses_whitespace_and_case():
    assert normalize_entity('  William   Dieterle ') == 'william dieterle'
    assert normalize_entity(None) == ''


def test_topic_hit_requires_seed_membership():
    result = evaluate_retrieval('Joe Thomas', ['Some Movie'],
                                seed_ids=['joe thomas', 'other'],
                                entity_ids=['Joe Thomas', 'Some Movie'])
    assert result['topic_hit'] == 1.0
    assert result['answer_covered'] == 1.0
    assert result['answer_recall'] == 1.0

    result = evaluate_retrieval('Joe Thomas', ['Some Movie'],
                                seed_ids=['other'],
                                entity_ids=['Joe Thomas'])
    assert result['topic_hit'] == 0.0
    assert result['answer_covered'] == 0.0


def test_multi_answer_recall_counts_partial_coverage():
    result = evaluate_retrieval('Kismet', ['A', 'B', 'C'],
                                seed_ids=['Kismet'], entity_ids=['A', 'C', 'D'])
    assert result['answer_covered'] == 1.0
    assert result['answer_recall'] == 2 / 3
    assert result['answer_hits'] == 2
    assert result['answer_total'] == 3


def test_empty_gold_is_zero_not_one():
    result = evaluate_retrieval('Kismet', [], seed_ids=['Kismet'], entity_ids=['A'])
    assert result['answer_covered'] == 0.0
    assert result['answer_recall'] == 0.0


def test_reachable_entities_is_undirected_and_depth_bounded():
    edges = [
        {'source_id': 'A', 'target_id': 'B'},
        {'source_id': 'B', 'target_id': 'C'},
    ]
    assert reachable_entities('a', edges, 1) == {'a', 'b'}
    assert reachable_entities('a', edges, 2) == {'a', 'b', 'c'}
    assert reachable_entities('C', edges, 1) == {'c', 'b'}
    assert reachable_entities('', edges, 2) == set()


def test_answer_reachable_requires_a_path_from_topic():
    edges = [
        {'source_id': 'Kismet', 'target_id': 'William Dieterle'},
        {'source_id': 'William Dieterle', 'target_id': 'Hollywood'},
    ]
    result = evaluate_retrieval(
        'Kismet', ['Hollywood'], seed_ids=['Kismet'],
        entity_ids=['Kismet', 'William Dieterle', 'Hollywood'],
        edges=edges, depth=1)
    assert result['answer_covered'] == 1.0
    assert result['answer_reachable'] == 0.0

    result = evaluate_retrieval(
        'Kismet', ['Hollywood'], seed_ids=['Kismet'],
        entity_ids=['Kismet', 'William Dieterle', 'Hollywood'],
        edges=edges, depth=2)
    assert result['answer_reachable'] == 1.0
    assert result['answer_reach_recall'] == 1.0


def test_percentile_linear_interpolation():
    assert percentile([0, 10], 0.0) == 0
    assert percentile([0, 10], 1.0) == 10
    assert percentile([0, 10], 0.5) == 5
    assert percentile([], 0.5) == 0


def test_bootstrap_ci_is_deterministic_and_brackets_mean():
    values = [1, 0, 1, 1, 0, 1, 0, 1, 1, 1]
    low, high = bootstrap_ci(values, rounds=500, seed=7)
    assert low <= sum(values) / len(values) <= high
    assert (low, high) == bootstrap_ci(values, rounds=500, seed=7)


def test_aggregate_reports_count_mean_and_interval():
    rows = [{'score': value} for value in [1.0, 0.0, 0.0, 1.0]]
    result = aggregate(rows, metric='score', rounds=200, seed=1)
    assert result['n'] == 4
    assert result['mean'] == 0.5
    assert result['ci_low'] <= 0.5 <= result['ci_high']
