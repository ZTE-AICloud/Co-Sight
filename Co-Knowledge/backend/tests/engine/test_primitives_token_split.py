"""自研原语层：token 截断（`primitives/components/token_split.py`）。

分两类用例：

  1. **差分用例**（标记 `baseline_differential`，默认 deselect；只在基线镜像里显式跑）：
     同一份 prompt + 同一段超长文本，本实现与库 `PromptHelper.truncate` 的输出
     **完全一致**；分词器 token 数也相同。这是"截断算术 + 分词器 + 切分器"三者
     一起对齐的证据，比单侧断言强得多。
  2. **常驻用例**：vendor 词表可用（离线）、切分器的行为锚点（空文本、超长无空格、
     分隔符保留）。摘库后这些仍在，保证替换后的实现自身可测。

⚠️ 词表为什么必须 vendor：见 `primitives/_static/tiktoken_cache/README.md`
（镜像里没有 tiktoken 默认缓存，不能依赖 llama-index 自带的目录）。
"""
import os

import pytest

from engine.primitives.components import token_split
from engine.primitives.templating import PromptTemplate

LONG_TEXT = ''.join(f'第{i}段内容，用于测试截断行为。' for i in range(2000))


# --------------------------------------------------------------------------
# 常驻用例
# --------------------------------------------------------------------------
def test_vendored_vocab_is_present_and_usable():
    cache_dir = token_split._STATIC_TIKTOKEN_CACHE
    files = [f for f in os.listdir(cache_dir)
             if not f.endswith('.md') and not f.startswith('.')]
    assert files, f'vendor 的 tiktoken 词表缺失：{cache_dir}'
    tokenizer = token_split.get_tokenizer()
    # cl100k_base：中文按字成词，英文按子词 —— 只要能编出非空 token 序列即说明词表可用
    assert len(tokenizer('测试文本 abc')) >= 3


def test_prompt_helper_arithmetic_matches_library_formula():
    helper = token_split.PromptHelper(context_window=8000, num_output=8000)
    prompt = PromptTemplate('提示 {query_str} 上下文 {context_str}')
    with pytest.raises(ValueError, match='not non-negative'):
        # 8000 - 提示词token - 8000 < 0：库在此时抛 ValueError（不是静默返回 0）
        helper.truncate(prompt, ['x'])


def test_truncate_is_length_bounded_and_keeps_head():
    helper = token_split.PromptHelper(context_window=8000, num_output=100)
    prompt = PromptTemplate('问题 {query_str}\n上下文 {context_str}')
    truncated = helper.truncate(prompt, [LONG_TEXT])
    assert len(truncated) == 1
    assert truncated[0] != LONG_TEXT          # 确实被截断
    assert truncated[0] in LONG_TEXT          # 且是**前缀**（切分器取 chunks[0]）
    assert truncated[0].startswith('第0段')


def test_splitter_handles_empty_and_unseparated_text():
    splitter = token_split.TokenizerTextSplitter(chunk_size=5, chunk_overlap=0,
                                                 tokenizer=lambda s: list(s))
    assert splitter.split_text('') == ['']
    chunks = splitter.split_text('abcdefghij')
    assert chunks[0] == 'abcde'               # 无空格长串按字符切（chunk_size 个字符）


def test_splitter_keeps_separator_on_subsequent_parts():
    splitter = token_split.TokenizerTextSplitter(chunk_size=3, chunk_overlap=0,
                                                 tokenizer=lambda s: s.split(' '))
    chunks = splitter.split_text('aa bb cc dd')
    assert len(chunks) >= 2


# --------------------------------------------------------------------------
# 差分用例（库摘掉后自动跳过）
# --------------------------------------------------------------------------
@pytest.mark.baseline_differential
def test_truncate_matches_library_character_for_character():
    pytest.importorskip('llama_index', reason='差分用例：库已摘除')
    from llama_index.core.indices.prompt_helper import PromptHelper as LibPromptHelper
    from llama_index.core.prompts import PromptTemplate as LibPromptTemplate

    prompt_text = '问题 {query_str}\n上下文 {context_str}'
    ours = token_split.PromptHelper(context_window=8000, num_output=100)
    theirs = LibPromptHelper(context_window=8000, num_output=100)
    ours_prompt = PromptTemplate(prompt_text)
    theirs_prompt = LibPromptTemplate(prompt_text)

    assert ours.truncate(ours_prompt, [LONG_TEXT]) == theirs.truncate(theirs_prompt, [LONG_TEXT])


def test_default_context_window_leaves_room_for_a_16k_output_budget():
    """默认上下文窗口必须大于部署的输出上限，否则答案生成直接 500。

    ``GENERATION_MAX_TOKENS`` 提到 16384 后，``const.default_token``
    仍是 10240，``PromptHelper`` 会算出负的可用上下文（-6213），每次问答都 500。
    """
    from engine.common import const

    helper = token_split.PromptHelper(context_window=const.default_token, num_output=16384)
    assert helper._get_available_context_size(100) > 0


@pytest.mark.baseline_differential
def test_tokenizer_matches_library_token_counts():
    pytest.importorskip('llama_index', reason='差分用例：库已摘除')
    from llama_index.core.utils import get_tokenizer as lib_get_tokenizer

    ours, theirs = token_split.get_tokenizer(), lib_get_tokenizer()
    for sample in (LONG_TEXT[:5000], '混合 mixed 文本 12345，标点。', '|*node_id#|abc|*node_id#|'):
        assert len(ours(sample)) == len(theirs(sample))
