"""`external_model_reranker` 三个纯函数/近纯方法的直测。

⚠️ 本文件**只加测试、不改代码** —— `external_model_reranker.py` 的行为属于对外契约。

钉住的语义：
  * `_remove_overlap` —— 相邻 chunk 去重核心：只在「order 连续」时被调用，
    从最长重叠往回退（先匹配长重叠），探查上限 `MAX_OVERLAP_LENGTH=200`；
  * `_extract_text_content` —— 剥 `expand_format` 壳。**必须被钉住的假设**：
    没有壳的文本会被吃掉首尾各 10 个字符（所有入参都先经 `_to_nodes` 包壳）；
  * `_merge_chunk_texts` —— 合并文本 + order 转 int 后才判连续
    （字符串 "1"/"2" 也算连续；转不了则不判重叠）。
"""


from engine.primitives.models import TextNode

from engine.common import const
from engine.post_retriever.external_model_reranker import (
    MAX_OVERLAP_LENGTH,
    ExternalModelReranker,
    _extract_text_content,
    _remove_overlap,
)
from engine.retriever import RagNodeWithScore


def _node(text, source='', base_name='kb'):
    return RagNodeWithScore(node=TextNode(text=text, metadata={'source': source}),
                            score=1.0, base_name=base_name)


def _reranker():
    return ExternalModelReranker(config_info={'top_n': 3})



# ---------------------------------------------------------------------------
# _remove_overlap
# ---------------------------------------------------------------------------

def test_remove_overlap_trims_shared_span():
    assert _remove_overlap('abcdef', 'defghi') == 'ghi'


def test_remove_overlap_without_shared_span_is_identity():
    assert _remove_overlap('abcdef', 'xyz') == 'xyz'


def test_remove_overlap_empty_inputs():
    """任一侧为空：不做任何事，返回 next。"""
    assert _remove_overlap('', 'abc') == 'abc'
    assert _remove_overlap('abc', '') == ''
    assert _remove_overlap('', '') == ''


def test_remove_overlap_prefers_the_longest_match():
    """从最长候选往回退：`ababa` 整体是 prev 的后缀 → next 全被吃掉。"""
    assert _remove_overlap('ababa', 'ababa') == ''
    # i=5: 'abcab' 不是 'xyabc' 的后缀；i=3: 'abc' 是 → 剥掉 3 个字符
    assert _remove_overlap('xyabc', 'abcabc') == 'abc'


def test_remove_overlap_scan_is_capped_at_max_overlap():
    """探查长度上限 200（MAX_OVERLAP_LENGTH）：300 字符的重叠只会被剥掉 200。"""
    over = 'x' * (MAX_OVERLAP_LENGTH + 100)

    assert _remove_overlap(over, over) == 'x' * 100
    # 放宽上限后，同样的输入被完整剥离 —— 证明 100 个残留就是"上限"造成的
    assert _remove_overlap(over, over, max_overlap=len(over)) == ''


# ---------------------------------------------------------------------------
# _extract_text_content
# ---------------------------------------------------------------------------

def test_extract_text_content_strips_expand_wrapper():
    wrapped = f'{const.expand_format}正文内容{const.expand_format}'

    assert _extract_text_content(_node(wrapped)) == '正文内容'


def test_extract_text_content_assumes_wrapper_is_present():
    """没有壳的文本会被吃掉首尾各 len(expand_format) 个字符 —— 这是已知行为，
    不是缺陷防御点：所有进入该函数的 text 都必须先被 `knowledge_base_client._to_nodes`
    包过壳。这里把假设钉死，避免有人把裸文本喂进来还期待原样返回。"""
    raw = 'X' * 25
    assert _extract_text_content(_node(raw)) == 'X' * (25 - 2 * len(const.expand_format))
    # 比壳还短的裸文本直接变空串（而不是抛异常）
    assert _extract_text_content(_node('short')) == ''


def test_extract_text_content_reads_node_text_not_metadata():
    """取的是 `node.text`（NodeWithScore 的 text 属性），不是 metadata 里的任何键。"""
    node = _node(f'{const.expand_format}正文{const.expand_format}', source='doc.txt')
    assert _extract_text_content(node) == '正文'


# ---------------------------------------------------------------------------
# ExternalModelReranker._merge_chunk_texts
# ---------------------------------------------------------------------------

def test_merge_single_chunk_is_passthrough():
    texts = _reranker()._merge_chunk_texts([{'text': 'abc', 'order': 1}])

    assert texts == ['abc']


def test_merge_consecutive_orders_removes_overlap():
    texts = _reranker()._merge_chunk_texts([
        {'text': 'abcdef', 'order': 1},
        {'text': 'defghi', 'order': 2},
    ])

    assert texts == ['abcdef', 'ghi']


def test_merge_non_consecutive_orders_keeps_text_verbatim():
    """order 跳号（1→3）说明中间有别的 chunk 被截断，不期望重叠 → 原样保留。"""
    texts = _reranker()._merge_chunk_texts([
        {'text': 'abcdef', 'order': 1},
        {'text': 'defghi', 'order': 3},
    ])

    assert texts == ['abcdef', 'defghi']


def test_merge_equal_or_reversed_orders_do_not_dedup():
    """只有 `curr == prev + 1` 才去重；相等/回退（跨来源拼接）原样保留。"""
    texts = _reranker()._merge_chunk_texts([
        {'text': 'abcdef', 'order': 2},
        {'text': 'defghi', 'order': 2},
    ])
    assert texts == ['abcdef', 'defghi']

    texts = _reranker()._merge_chunk_texts([
        {'text': 'abcdef', 'order': 5},
        {'text': 'defghi', 'order': 1},
    ])
    assert texts == ['abcdef', 'defghi']


def test_merge_string_orders_are_coerced_before_consecutive_check():
    """API 可能返回字符串 order（"1"/"2"）：先转 int 再判连续，仍然去重。"""
    texts = _reranker()._merge_chunk_texts([
        {'text': 'abcdef', 'order': '1'},
        {'text': 'defghi', 'order': '2'},
    ])

    assert texts == ['abcdef', 'ghi']


def test_merge_unparseable_orders_skip_dedup_but_keep_text():
    """None / 非数字字符串：转 int 失败 → 不判重叠，但文本照收（不能丢内容）。"""
    texts = _reranker()._merge_chunk_texts([
        {'text': 'abcdef', 'order': None},
        {'text': 'defghi', 'order': 'not-a-number'},
    ])

    assert texts == ['abcdef', 'defghi']


# ---------------------------------------------------------------------------
# _invoke_rerank：画布显式选的模型优先（空值 = 跟随部署默认）
# ---------------------------------------------------------------------------

def _capture_invoke(monkeypatch):
    from engine.post_retriever import external_model_reranker as module

    calls = []

    def fake(model, question, texts, score, **kwargs):
        calls.append({'model': model, 'question': question, 'texts': texts,
                      'score': score, **kwargs})
        return list(texts)

    monkeypatch.setattr(module, 'invoke_rerank_client', fake)
    return calls


def test_invoke_rerank_uses_the_model_selected_on_the_canvas(monkeypatch):
    calls = _capture_invoke(monkeypatch)
    reranker = ExternalModelReranker(config_info={'model': 'Qwen3-Reranker-4B', 'top_n': 3})

    assert reranker._invoke_rerank('q', ['a']) == ['a']
    assert calls[0]['model'] == 'Qwen3-Reranker-4B'
    assert calls[0]['strict_model'] is True, '显式选的模型必须按「选不到就报错」解析'


def test_invoke_rerank_falls_back_to_the_deployment_default(monkeypatch):
    from engine.post_retriever import external_model_reranker as module

    calls = _capture_invoke(monkeypatch)
    monkeypatch.setattr(module, 'query_rerank_model', lambda username: 'Qwen3-Reranker-4B')
    reranker = ExternalModelReranker(config_info={'top_n': 3})

    reranker._invoke_rerank('q', ['a'])
    assert calls[0]['model'] == 'Qwen3-Reranker-4B'
    assert calls[0]['strict_model'] is False, '没选模型时保持原有回落语义'


def test_invoke_rerank_treats_blank_model_as_follow_default(monkeypatch):
    """老画布 / 前端清空下拉：空串或空白都等于「跟随部署默认」。"""
    from engine.post_retriever import external_model_reranker as module

    calls = _capture_invoke(monkeypatch)
    monkeypatch.setattr(module, 'query_rerank_model', lambda username: 'default-rerank')
    reranker = ExternalModelReranker(config_info={'model': '   ', 'top_n': 3})

    reranker._invoke_rerank('q', ['a'])
    assert calls[0]['model'] == 'default-rerank'
    assert calls[0]['strict_model'] is False
