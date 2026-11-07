"""实体提及匹配纯函数：词边界、最长优先、大小写/空白、中文。"""
from graph.service.entity_mention import build_mention_trie, find_mentions


def test_finds_entity_name_in_question():
    trie = build_mention_trie([('E1', 'Tom McLoughlin')])
    assert find_mentions('what did Tom McLoughlin direct', trie) == ['E1']


def test_case_and_whitespace_are_normalized():
    trie = build_mention_trie([('E1', 'Catch  Me If You Can')])
    assert find_mentions('the film catch me if you can were', trie) == ['E1']


def test_ascii_word_boundary_blocks_substring_false_positive():
    trie = build_mention_trie([('E1', 'She')])
    assert find_mentions('what did Sherlock direct', trie) == []
    assert find_mentions('what did She direct', trie) == ['E1']


def test_longest_match_wins_and_overlap_is_dropped():
    trie = build_mention_trie([('NEW', 'New York'), ('YORK', 'York')])
    assert find_mentions('films set in New York', trie) == ['NEW']


def test_chinese_names_do_not_require_ascii_boundaries():
    trie = build_mention_trie([('Z1', '张三')])
    assert find_mentions('张三主演了哪些电影', trie) == ['Z1']


def test_short_ascii_names_are_ignored():
    trie = build_mention_trie([('E1', 'AI')])
    assert find_mentions('what is AI', trie) == []


def test_max_mentions_caps_results():
    trie = build_mention_trie([(f'E{i}', f'Entity Number {i}') for i in range(5)])
    assert len(find_mentions(
        'Entity Number 0 Entity Number 1 Entity Number 2 Entity Number 3',
        trie, max_mentions=2)) == 2


def test_empty_inputs():
    assert find_mentions('', build_mention_trie([('E1', 'Name')])) == []
    assert find_mentions('Name', {}) == []


def test_common_lowercase_words_dropped_when_proper_name_present():
    trie = build_mention_trie([
        ('TOPIC', 'The Sweet Hereafter'), ('GEN1', 'film'), ('GEN2', 'director')])
    assert find_mentions(
        'the film directed by the director of The Sweet Hereafter', trie) == ['TOPIC']


def test_lowercase_mentions_kept_when_no_proper_name():
    trie = build_mention_trie([('GEN', 'film')])
    assert find_mentions('what is a film', trie) == ['GEN']
