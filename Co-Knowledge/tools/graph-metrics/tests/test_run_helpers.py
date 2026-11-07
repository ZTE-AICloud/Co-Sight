"""运行器纯函数单测：抽样、深度解析、聚合口径。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_metaqa_metrics import (  # noqa: E402
    group_rows,
    resolve_depths,
    resolve_limits,
    sample_questions,
    summarize,
)


def make_row(hop, qid, answer='A'):
    return {'hop': f'{hop}-hop', 'qid': qid, 'question': f'q {qid}',
            'topic': 'T', 'answers': [answer]}


def test_sample_questions_is_deterministic_per_hop():
    rows = [make_row(1, f'q{index}') for index in range(100)]
    first = sample_questions(rows, hops=[1], limit_per_hop=10, seed=7)
    second = sample_questions(rows, hops=[1], limit_per_hop=10, seed=7)
    assert [row['qid'] for row in first] == [row['qid'] for row in second]
    assert len(first) == 10
    assert first == sorted(first, key=lambda row: row['qid'])


def test_sample_questions_zero_keeps_all():
    rows = [make_row(2, f'q{index}') for index in range(5)]
    assert sample_questions(rows, hops=[2], limit_per_hop=0) == rows


def test_resolve_depths_hop_mode_and_explicit_list():
    assert resolve_depths('hop', [1, 2, 3]) == {1: [1], 2: [2], 3: [3]}
    assert resolve_depths('3,1,2', [1, 3]) == {1: [1, 2, 3], 3: [1, 2, 3]}


def test_resolve_depths_rejects_out_of_range():
    try:
        resolve_depths('11', [1])
    except ValueError as error:
        assert '1-10' in str(error)
    else:
        raise AssertionError('expected ValueError')


def test_summarize_excludes_errors_and_reports_conservative():
    rows = [
        {'topic_hit': 1.0, 'answer_covered': 1.0, 'answer_reachable': 1.0,
         'answer_recall': 1.0, 'answer_reach_recall': 1.0,
         'seed_count': 3, 'truncated': 0.0, 'entity_count': 10,
         'latency_s': 0.2, 'error': ''},
        {'topic_hit': 0.0, 'answer_covered': 0.0, 'answer_reachable': 0.0,
         'answer_recall': 0.5, 'answer_reach_recall': 0.5,
         'seed_count': 0, 'truncated': 1.0, 'entity_count': 1000,
         'latency_s': 0.4, 'error': ''},
        {'hop': '1-hop', 'depth': 1, 'qid': 'q3', 'error': 'boom'},
    ]
    cell = summarize(rows, rounds=100)
    assert cell['attempted'] == 3
    assert cell['ok'] == 2
    assert cell['errors'] == 1
    assert cell['topic_hit']['mean'] == 0.5
    assert cell['topic_hit']['conservative'] == 1 / 3
    assert cell['empty_seed_rate'] == 0.5
    assert cell['truncated_rate'] == 0.5


def test_group_rows_splits_by_hop_and_depth():
    rows = [
        {**make_row(1, 'a'), 'depth': 1},
        {**make_row(1, 'b'), 'depth': 2},
        {**make_row(2, 'c'), 'depth': 2},
    ]
    groups = group_rows(rows, [1, 2], {1: [1, 2], 2: [2]})
    assert [row['qid'] for row in groups[(1, 1)]] == ['a']
    assert [row['qid'] for row in groups[(1, 2)]] == ['b']
    assert [row['qid'] for row in groups[(2, 2)]] == ['c']


def test_resolve_limits_uniform_and_per_hop():
    assert resolve_limits('', [1, 2, 3], 1000) == {1: 1000, 2: 1000, 3: 1000}
    assert resolve_limits('2000', [1, 2, 3], 1000) == {1: 2000, 2: 2000, 3: 2000}
    assert resolve_limits('1000,3000,5000', [1, 2, 3], 1000) == \
        {1: 1000, 2: 3000, 3: 5000}


def test_resolve_limits_rejects_wrong_count():
    try:
        resolve_limits('1000,2000', [1, 2, 3], 1000)
    except ValueError as error:
        assert '--limits' in str(error)
    else:
        raise AssertionError('expected ValueError')
