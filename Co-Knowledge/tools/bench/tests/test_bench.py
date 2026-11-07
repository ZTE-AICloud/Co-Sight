"""公开基准 harness 的纯函数单测（不访问产品/网关）。"""

# ruff: noqa: E402  —— 先把 tools/bench 塞进 sys.path，再导入同级模块
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

from common import (normalize_answer, safe_pid, sample_rows, score_answer,
                    split_parts, token_f1)
from prepare import _html_to_text
from run_context_qa import build_rgb_docs, rgb_checkanswer


def test_normalize_answer_strips_punctuation_and_articles():
    assert normalize_answer('The Cats, a dog!') == 'cats dog'


def test_token_f1_exact_and_partial():
    assert token_f1('Paris', 'Paris') == pytest.approx(1.0)
    assert token_f1('Paris, France', 'Paris') == pytest.approx(2 / 3)
    assert token_f1('', 'Paris') == 0.0


def test_score_answer_uses_best_gold_and_contains():
    scores = score_answer('It is Paris, France.', ['London', 'Paris'])
    assert scores['contains'] == 1.0
    assert 0.0 < scores['f1'] < 1.0


def test_safe_pid_is_marker_safe_and_deterministic():
    first = safe_pid('a/b c】\nd')
    second = safe_pid('a/b c】\nd')
    assert first == second
    assert '】' not in first
    assert ' ' not in first


def test_split_parts_covers_full_text():
    text = 'x' * 9000
    parts = split_parts(text, max_chars=4000)
    assert len(parts) == 3
    assert ''.join(parts) == text


def test_sample_rows_is_order_independent_and_stable():
    rows = [{'qid': str(i)} for i in range(100)]
    shuffled = list(reversed(rows))
    assert sample_rows(rows, 10) == sample_rows(shuffled, 10)
    assert len(sample_rows(rows, 10)) == 10


def test_html_to_text_strips_tags_and_unescapes():
    text = _html_to_text('<p>Hello&nbsp;world</p><script>x()</script>')
    assert 'Hello' in text and 'world' in text
    assert '<' not in text


def test_rgb_checkanswer_list_requires_any_item():
    assert rgb_checkanswer('答案是1月3日', [['1月3日', '1月12日']]) == [1]
    assert rgb_checkanswer('不知道', ['12人']) == [0]


def test_build_rgb_docs_noise_ratio_and_passage_count():
    row = {
        'type': 'noise',
        'positive': [f'pos{i}' for i in range(5)],
        'negative': [f'neg{i}' for i in range(5)],
    }
    docs = build_rgb_docs(row, noise_rate=0.4, passage_num=5)
    assert len(docs) == 5
    assert sum(doc.startswith('neg') for doc in docs) == 2


def test_build_rgb_docs_negative_rejection_uses_only_noise():
    row = {
        'type': 'noise',
        'positive': ['pos0'],
        'negative': [f'neg{i}' for i in range(5)],
    }
    docs = build_rgb_docs(row, noise_rate=1.0, passage_num=5)
    assert len(docs) == 5
    assert all(doc.startswith('neg') for doc in docs)
