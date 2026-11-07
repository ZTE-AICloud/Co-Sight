"""导入/映射层的单测：passage 切子片与「检索结果 → pid」两条路。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from import_corpus import MAX_PART_CHARS, split_parts  # noqa: E402
from repair_parts import part_of  # noqa: E402
from run_retrieval_metrics import build_text_index, doc_pids  # noqa: E402


def test_split_parts_keeps_short_text_whole():
    assert split_parts('短文本') == ['短文本']


def test_split_parts_splits_long_text_at_fixed_size():
    text = '甲' * (MAX_PART_CHARS + 10)
    parts = split_parts(text)
    assert [len(part) for part in parts] == [MAX_PART_CHARS, 10]
    assert ''.join(parts) == text


def test_doc_pids_prefers_marker():
    index, normalized = build_text_index(pd.DataFrame(
        {'id': ['a' * 32], 'text': ['正文内容']}))
    doc = {'content': f'【DURET-{"a" * 32}】\n正文内容'}
    assert doc_pids(doc, (index, normalized)) == ['a' * 32]


def test_doc_pids_exact_text_fallback_for_keyword_path():
    index, normalized = build_text_index(pd.DataFrame(
        {'id': ['b' * 32], 'text': ['关键词路径正文']}))
    doc = {'content': '关键词路径正文'}
    assert doc_pids(doc, (index, normalized)) == ['b' * 32]


def test_doc_pids_whitespace_normalized_fallback():
    index, normalized = build_text_index(pd.DataFrame(
        {'id': ['c' * 32], 'text': ['第一段\n第二段']}))
    doc = {'content': '第一段  第二段'}
    assert doc_pids(doc, (index, normalized)) == ['c' * 32]


def test_doc_pids_unmapped_returns_empty():
    index, normalized = build_text_index(pd.DataFrame(
        {'id': ['d' * 32], 'text': ['语料正文']}))
    assert doc_pids({'content': '容器文件自己的正文'}, (index, normalized)) == []


def test_part_of_new_style_and_old_style_rows():
    pid = 'a' * 32
    assert part_of({'content': '正文', 'supplement': f'【DURET-{pid}】\n正文'}) == (pid, '正文')
    assert part_of({'content': f'【DURET-{pid}】\n正文', 'supplement': ''}) == (pid, '正文')
    assert part_of({'content': '正文', 'supplement': f'【DURET-{pid}】'}) == (pid, '正文')
    assert part_of({'content': '容器正文', 'supplement': ''}) is None


def test_doc_pids_maps_ambiguous_text_to_all_pids():
    index, normalized = build_text_index(pd.DataFrame(
        {'id': ['e' * 32, 'f' * 32], 'text': ['同一段正文', '同一段正文']}))
    assert sorted(doc_pids({'content': '同一段正文'}, (index, normalized))) == sorted(
        ['e' * 32, 'f' * 32])
