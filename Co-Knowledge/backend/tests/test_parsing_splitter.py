"""句子切分器：中文拼接不补空格、硬切优先落在边界、长度不越界。"""

from parsing.splitter import (
    SentenceChunkSplitter,
    hard_split_text,
    join_parts,
    separator_length,
)


def test_cjk_sentences_join_without_space():
    text = '第一句。第二句。第三句。'

    chunks = SentenceChunkSplitter(max_word_count=512, overlap=0).split(text)

    assert chunks == ['第一句。第二句。第三句。']


def test_english_sentences_keep_space():
    text = 'First sentence. Second sentence. Third sentence.'

    chunks = SentenceChunkSplitter(max_word_count=512, overlap=0).split(text)

    assert chunks == [text]


def test_mixed_join_keeps_english_spacing():
    assert join_parts(['使用 Python 编程', '很简单']) == '使用 Python 编程很简单'
    assert join_parts(['Hello', 'World']) == 'Hello World'
    assert separator_length('。', '这') == 0
    assert separator_length('a', 'B') == 1


def test_hard_split_prefers_whitespace_boundary():
    text = 'word ' * 100

    pieces = hard_split_text(text, 50, 0)

    assert all(len(piece) <= 50 for piece in pieces)
    assert all(piece.endswith(' ') for piece in pieces[:-1])
    assert ''.join(pieces) == text


def test_hard_split_terminates_when_overlap_not_smaller_than_size():
    pieces = hard_split_text('x' * 100, 10, 50)

    assert len(pieces) > 1
    assert ''.join(pieces) == 'x' * 100


def test_chunks_never_exceed_limit():
    text = '中文句子用于测试长度上限。' * 100

    chunks = SentenceChunkSplitter(max_word_count=64, overlap=16).split(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= 64 for chunk in chunks)


def test_long_unpunctuated_text_is_split_without_loss():
    text = 'A' * 500 + '。' + 'B' * 500

    chunks = SentenceChunkSplitter(max_word_count=128, overlap=32).split(text)

    assert all(len(chunk) <= 128 for chunk in chunks)
    assert 'A' * 500 in ''.join(chunks)
    assert 'B' * 500 in ''.join(chunks)
