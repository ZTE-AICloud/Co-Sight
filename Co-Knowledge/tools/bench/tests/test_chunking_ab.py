"""切分 A/B harness 的纯函数单测（不访问产品/网关）。"""

# ruff: noqa: E402  —— 先把 tools/bench 塞进 sys.path，再导入同级模块
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

from run_chunking_ab import (build_questions, compare_results,  # noqa: E402
                             normalize_for_match, questions_from_docx, score_ranks)

docx = pytest.importorskip('docx')


def _make_docx(path: Path, rows, heading='第一章 总则', body='这是正文，长度足够用来出题。'):
    document = docx.Document()
    if heading:
        document.add_heading(heading, level=1)
    if body:
        document.add_paragraph(body)
    if rows:
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.cell(i, j).text = value
    document.save(str(path))


def test_questions_from_table(tmp_path):
    path = tmp_path / 'a.docx'
    _make_docx(path, [
        ['设备名称', '设备维护IP'],
        ['DEVICE-001', '192.0.2.10'],
    ])

    questions = questions_from_docx(str(path))

    assert {'kind': 'table', 'q': 'DEVICE-001 的设备维护IP是什么？',
            'a': '192.0.2.10'} in questions


def test_questions_from_heading(tmp_path):
    path = tmp_path / 'a.docx'
    _make_docx(path, None, heading='故障处理流程',
               body='先抑制再根除，恢复业务优先，查找故障原因不得延迟业务恢复。')

    questions = questions_from_docx(str(path))

    assert any(item['kind'] == 'section' and item['q'].startswith('故障处理流程') for item in questions)
    assert all(len(item['a']) <= 24 for item in questions)


def test_ragged_rows_are_skipped(tmp_path):
    """行宽与表头不一致时不造题 —— 否则答案会对到错的列上。"""
    path = tmp_path / 'a.docx'
    _make_docx(path, [['设备名称', '设备维护IP'], ['只有一格']])

    assert not [item for item in questions_from_docx(str(path)) if item['kind'] == 'table']


def test_build_questions_is_deterministic_and_capped(tmp_path):
    path = tmp_path / 'a.docx'
    rows = [['名称'] + [f'列{i}' for i in range(1, 6)]]
    rows += [[f'设备{n}'] + [f'值{n}-{i}' for i in range(1, 6)] for n in range(1, 21)]
    _make_docx(path, rows)

    first = build_questions([str(path)], limit=10)
    second = build_questions([str(path)], limit=10)

    assert first == second
    assert len(first) == 10


def test_normalize_for_match_handles_whitespace_and_punctuation():
    """源文档「两段单元格」与产品「换行并空格、。改；」的差异不该算丢内容。"""
    source = '所有单板状态为normal，单板没有重启现象。 贝尔所有单板状态为UP。'
    product = '所有单板状态为normal，单板没有重启现象；贝尔所有单板状态为UP；'

    assert normalize_for_match(source) in normalize_for_match(product)


def test_normalize_for_match_keeps_double_space_equal():
    assert normalize_for_match('power off  slot 槽位号') == normalize_for_match('power off slot 槽位号')


def test_score_ranks():
    metrics = score_ranks([1, 2, None, 11])

    assert metrics['hit@1'] == pytest.approx(0.25)
    assert metrics['hit@5'] == pytest.approx(0.50)
    assert metrics['hit@10'] == pytest.approx(0.50)
    assert metrics['mrr@10'] == pytest.approx((1 + 0.5) / 4)
    assert metrics['miss'] == pytest.approx(0.50)


def test_compare_results_reports_deltas():
    old = {
        'docs': ['a.docx'], 'chunks': 88, 'questions': 2, 'coverage': 2, 'contaminated': 39,
        'metrics': {'vector': {'hit@1': 0.5, 'hit@5': 1.0, 'hit@10': 1.0, 'mrr@10': 0.75}},
        'details': {'vector': [{'q': 'q1', 'rank': 2}, {'q': 'q2', 'rank': 1}]},
    }
    new = {
        'docs': ['a.docx'], 'chunks': 151, 'questions': 2, 'coverage': 2, 'contaminated': 0,
        'metrics': {'vector': {'hit@1': 1.0, 'hit@5': 1.0, 'hit@10': 1.0, 'mrr@10': 1.0}},
        'details': {'vector': [{'q': 'q1', 'rank': 1}, {'q': 'q2', 'rank': 1}]},
    }

    text = '\n'.join(compare_results(old, new))

    assert '切片数: 旧 88 → 新 151' in text
    assert '含哨兵切片: 旧 39 → 新 0' in text
    assert '+50.00 pp' in text
    assert '排名更好 1、更差 0、持平 1' in text
