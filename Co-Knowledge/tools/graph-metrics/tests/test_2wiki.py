"""2Wiki 端到端脚本的单测：抽样、语料去重、答案口径与证据召回。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analyze_2wiki_graph  # noqa: E402
import prepare_2wiki  # noqa: E402
import run_2wiki_e2e  # noqa: E402


def _row(qid, type_name='compositional', answer='Paris'):
    return {
        '_id': qid, 'type': type_name, 'question': f'q-{qid}', 'answer': answer,
        'context': [['A', ['A is a place.']], ['B', ['B is a film.']]],
        'supporting_facts': [['A', 0]],
        'evidences': [],
    }


def test_sample_is_stratified_and_deterministic():
    rows = [_row(f'{type_name}-{index}', type_name)
            for type_name in prepare_2wiki.TYPES for index in range(5)]
    first = prepare_2wiki.sample(rows, per_type=2, seed=7)
    second = prepare_2wiki.sample(rows, per_type=2, seed=7)
    assert [row['_id'] for row in first] == [row['_id'] for row in second]
    assert len(first) == len(prepare_2wiki.TYPES) * 2
    assert {row['type'] for row in first} == set(prepare_2wiki.TYPES)


def test_sample_zero_means_all_rows_per_type():
    rows = [_row(f'{type_name}-{index}', type_name)
            for type_name in prepare_2wiki.TYPES for index in range(5)]

    picked = prepare_2wiki.sample(rows, per_type=0, seed=7)

    assert len(picked) == len(rows)


def test_build_articles_dedupes_and_keeps_longer_sentences():
    rows = [
        {**_row('1'), 'context': [['A', ['short']]]},
        {**_row('2'), 'context': [['A', ['a much longer sentence']]]},
    ]
    articles, title_to_aid = prepare_2wiki.build_articles(rows)
    assert len(articles) == 1
    assert articles[0]['text'].startswith('A\n')
    assert 'a much longer sentence' in articles[0]['text']
    assert title_to_aid['A'] == articles[0]['aid']


def test_graph_upload_groups_respect_limit(tmp_path):
    articles = [{'aid': f'a-{i}', 'title': f'T{i}', 'text': f'T{i}\nbody {i}'}
                for i in range(5)]
    groups = prepare_2wiki.write_graph_upload(tmp_path, articles, group_size=2)
    assert [group['file'] for group in groups] == [
        'graph-001.txt', 'graph-002.txt', 'graph-003.txt']
    assert len(groups[-1]['titles']) == 1
    assert '## T0' in (tmp_path / 'graph_upload/graph-001.txt').read_text()
    lines = (tmp_path / 'groups.jsonl').read_text().splitlines()
    assert json.loads(lines[0])['titles'] == ['T0', 'T1']


def test_score_answer_exact_contains_and_multi_gold():
    assert run_2wiki_e2e.score_answer('Paris', 'Paris')['em'] == 1.0
    partial = run_2wiki_e2e.score_answer(
        'Kismet was directed by William Dieterle.', 'William Dieterle')
    assert partial['em'] == 0.0
    assert partial['contains'] == 1.0
    multi = run_2wiki_e2e.score_answer('Baz', 'Foo | Baz')
    assert multi['em'] == 1.0
    assert run_2wiki_e2e.score_answer('yesterday', 'yes')['contains'] == 0.0


def test_normalized_em_accepts_answer_variants_but_not_wrong_entities():
    positives = [
        ('Grammy Award', 'Grammy'),
        ('Nürtingen, Württemberg', 'Nürtingen'),
        ('Port of Spain', 'Saint James, Port of Spain'),
        ('27 August 1439', '1439'),
        ('King Gustaf VI Adolf of Sweden', 'Gustaf VI Adolf of Sweden'),
        ('Herod', 'Herod the Great'),
        ('Maharaja Jitendra Narayan', 'Jitendra Narayan'),
    ]
    for prediction, gold in positives:
        scored = run_2wiki_e2e.score_answer(prediction, gold)
        assert scored['em'] == 0.0, (prediction, gold)
        assert scored['em_normalized'] == 1.0, (prediction, gold)

    negatives = [
        ('France', 'Paris'),
        ('France', 'Paris, France'),
        ('John Holles, Earl of Clare', 'John Holles, 1st Duke of Newcastle'),
        ('Karthika (film)', "Everything's Ducky"),
    ]
    for prediction, gold in negatives:
        assert run_2wiki_e2e.score_answer(prediction, gold)['em_normalized'] == 0.0, (
            prediction, gold)


def test_country_key_normalizes_demonyms_and_historical_states():
    assert analyze_2wiki_graph.country_key('American') == 'united states'
    assert analyze_2wiki_graph.country_key('U.S.') == 'united states'
    assert analyze_2wiki_graph.country_key('East Germany') == 'germany'
    assert analyze_2wiki_graph.country_key('British') == 'united kingdom'
    assert analyze_2wiki_graph.country_key('Kenya') == 'kenya'


def test_strip_answer_removes_thinking_block():
    assert run_2wiki_e2e.strip_answer(
        '<think>reasoning</think>  Paris. ') == 'Paris.'
    assert run_2wiki_e2e.strip_answer('"Paris"') == 'Paris'


def test_evidence_hit_counts_gold_titles():
    text = '## Kismet\nKismet is a film.\n## Vertigo\nVertigo is a film.'
    assert run_2wiki_e2e.evidence_hit(text, ['Kismet', 'Vertigo']) == 1.0
    assert run_2wiki_e2e.evidence_hit(text, ['Kismet', 'Missing']) == 0.5
