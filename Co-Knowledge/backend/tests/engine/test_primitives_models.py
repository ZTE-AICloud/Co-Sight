"""自研原语层：数据模型（`engine/primitives/models.py`）。

钉住的是**对齐 llama-index-core 0.10.31 的语义**——任何漂移都会改变
送进模型的 prompt 上下文与融合去重键。
本文件是这些语义的**就近护栏**（单测比跨进程指纹更早红、更快定位）：

  1. `get_content()` 的两种分支：metadata 串为空 → 返回**未 strip** 的原文；
     非空 → `text_template.format(...)` 之后 `.strip()`；
  2. `get_metadata_str()` 按 metadata 的**插入顺序**（不是字母序）拼接，分隔符 `"\\n"`，
     每行 `"{key}: {value}"`；`LLM`/`EMBED` 两种 mode 各剔各的 excluded 键；
  3. `NodeWithScore.text` 的 isinstance 门：非 Node 抛
     `ValueError("Node must be a TextNode to get text.")`（不是 None、不是空串）；
  4. 默认模板字面量与**原库的拼写笔误** `metadata_seperator`。

不发任何网络请求、不 import 任何第三方索引库。
"""
import pytest

from engine.primitives.models import (
    DEFAULT_METADATA_SEPERATOR,
    DEFAULT_METADATA_TEMPLATE,
    DEFAULT_TEXT_TEMPLATE,
    MetadataMode,
    Node,
    NodeWithScore,
    QueryBundle,
    QueryEngineTool,
    RagNodeWithScore,
    Response,
    SelectorResult,
    SingleSelection,
    StreamingResponse,
    TextNode,
)


def _node(**kw):
    return Node(text=kw.pop('text', '正文'), metadata=kw.pop('metadata', None), **kw)


# --------------------------------------------------------------------------
# 默认模板（字面量必须与库一致）
# --------------------------------------------------------------------------
def test_default_literals_match_library():
    assert DEFAULT_TEXT_TEMPLATE == '{metadata_str}\n\n{content}'
    assert DEFAULT_METADATA_TEMPLATE == '{key}: {value}'
    assert DEFAULT_METADATA_SEPERATOR == '\n'  # 拼写沿用原库（seperator）


def test_text_node_alias_points_to_node():
    assert TextNode is Node
    assert TextNode.class_name() == 'TextNode'


# --------------------------------------------------------------------------
# get_content / get_metadata_str
# --------------------------------------------------------------------------
def test_get_content_none_mode_returns_raw_text_without_strip():
    node = _node(text='  带空格的正文  ', metadata={'source': 'a.docx'})
    # NONE 分支：**不 strip**（库的实现是 `return self.text`）
    assert node.get_content(metadata_mode=MetadataMode.NONE) == '  带空格的正文  '
    assert node.get_text() == '  带空格的正文  '


def test_get_content_llm_prepends_metadata_in_insertion_order():
    node = _node(metadata={'source': 'a.docx', 'chunk_index': '1', 'knowledge_name': 'kb'})
    content = node.get_content(metadata_mode=MetadataMode.LLM)
    assert content == (
        'source: a.docx\nchunk_index: 1\nknowledge_name: kb\n\n正文'
    )


def test_get_content_strips_the_assembled_result():
    node = _node(metadata={'k': 'v'})
    # 组装后 strip：模板是 '{metadata_str}\n\n{content}'，正文两侧空白会被去掉
    assert node.get_content(metadata_mode=MetadataMode.LLM) == 'k: v\n\n正文'


def test_get_content_empty_metadata_falls_back_to_text():
    node = _node(metadata={})
    assert node.get_content(metadata_mode=MetadataMode.LLM) == '正文'
    assert node.get_content(metadata_mode=MetadataMode.ALL) == '正文'


def test_get_metadata_str_mode_none_is_empty():
    node = _node(metadata={'k': 'v'})
    assert node.get_metadata_str(mode=MetadataMode.NONE) == ''


def test_metadata_values_are_stringified():
    node = _node(metadata={'n': 3, 'b': True, 'none': None})
    # 库用 str(value)（None → 'None'），不做 json 化
    assert node.get_metadata_str(mode=MetadataMode.ALL) == 'n: 3\nb: True\nnone: None'


def test_excluded_keys_are_mode_specific():
    node = _node(
        metadata={'a': '1', 'b': '2'},
        excluded_llm_metadata_keys=['a'],
        excluded_embed_metadata_keys=['b'],
    )
    assert node.get_metadata_str(mode=MetadataMode.LLM) == 'b: 2'
    assert node.get_metadata_str(mode=MetadataMode.EMBED) == 'a: 1'
    assert node.get_metadata_str(mode=MetadataMode.ALL) == 'a: 1\nb: 2'


# --------------------------------------------------------------------------
# 序列化
# --------------------------------------------------------------------------
def test_node_from_dict_ignores_class_name_and_unknown_keys():
    node = Node.from_dict({
        'class_name': 'TextNode',
        'text': '正文',
        'metadata': {'source': 'a.docx'},
        'id_': 'fixed-id',
        'relationships': {},
        'embedding': None,
        'start_char_idx': 0,
        'end_char_idx': 10,
        'text_template': '{metadata_str}\n\n{content}',
        'metadata_template': '{key}: {value}',
        'metadata_seperator': '\n',
        'excluded_llm_metadata_keys': [],
        'excluded_embed_metadata_keys': [],
        # 未知键：原库走 pydantic（Extra.ignore），必须被静默忽略
        '_node_type': 'TextNode',
        'unknown_future_key': {'x': 1},
    })
    assert node.id_ == 'fixed-id'
    assert node.text == '正文'
    assert node.metadata == {'source': 'a.docx'}
    assert node.start_char_idx == 0 and node.end_char_idx == 10


def test_node_from_dict_defaults_when_keys_missing():
    node = Node.from_dict({'text': '正文', 'relationships': {}, 'metadata': {'k': 'v'}})
    assert node.id_  # 自动生成 uuid
    assert node.text_template == DEFAULT_TEXT_TEMPLATE
    assert node.metadata_seperator == DEFAULT_METADATA_SEPERATOR
    assert node.excluded_llm_metadata_keys == []


def test_node_from_json_round_trip():
    import json
    payload = json.dumps({'text': '正文', 'metadata': {'k': 'v'}})
    node = Node.from_json(payload)
    assert node.get_content(metadata_mode=MetadataMode.LLM) == 'k: v\n\n正文'


# --------------------------------------------------------------------------
# NodeWithScore 透传与 isinstance 门
# --------------------------------------------------------------------------
def test_node_with_score_passthrough_properties():
    node = _node(metadata={'source': 'a.docx'})
    nws = NodeWithScore(node=node, score=0.5)
    assert nws.text == '正文'
    assert nws.metadata is node.metadata
    assert nws.id_ == node.id_
    assert nws.node_id == node.node_id
    assert nws.get_score() == 0.5


def test_node_with_score_score_none_returns_zero_or_raises():
    nws = NodeWithScore(node=_node(), score=None)
    assert nws.get_score() == 0.0
    with pytest.raises(ValueError, match='Score not set.'):
        nws.get_score(raise_error=True)


def test_node_with_score_text_requires_text_node():
    class _NotANode:
        pass

    nws = NodeWithScore(node=_NotANode())
    # 错误信息必须精确匹配（调用方靠它区分"节点类型不对"与"内容为空"）
    with pytest.raises(ValueError, match='Node must be a TextNode to get text.'):
        _ = nws.text


def test_rag_node_with_score_carries_base_name():
    nws = RagNodeWithScore(node=_node(), score=1.0, base_name='doc_x')
    assert nws.base_name == 'doc_x'
    assert isinstance(nws, NodeWithScore)


# --------------------------------------------------------------------------
# 其余模型
# --------------------------------------------------------------------------
def test_query_bundle_query_str_is_mutable():
    qb = QueryBundle(query_str='原问题')
    qb.query_str = '改写后'  # 改写算子原地改写（query_rewrite.py:44）
    assert qb.query_str == '改写后'


def test_response_and_streaming_response_shape():
    resp = Response('答案', source_nodes=[], metadata=None)
    assert resp.response == '答案'
    assert not hasattr(resp, 'response_gen')  # app._check_response 靠这个判别流式

    gen = iter(['帧1', '[DONE]'])
    sresp = StreamingResponse(response_gen=gen)
    assert hasattr(sresp, 'response_gen')
    assert list(sresp.response_gen) == ['帧1', '[DONE]']


def test_selector_result_ind_inds_reason():
    multi = SelectorResult(selections=[SingleSelection(index=1, reason='理由')])
    assert multi.ind == 1 and multi.inds == [1]
    assert multi.reason == '理由' and multi.reasons == ['理由']

    multi2 = SelectorResult(selections=[SingleSelection(index=0, reason='r0'),
                                        SingleSelection(index=2, reason='r2')])
    assert multi2.inds == [0, 2]
    with pytest.raises(ValueError, match='please use .inds'):
        _ = multi2.ind


def test_query_engine_tool_from_defaults_uses_library_defaults():
    from engine.primitives.prompts import DEFAULT_DESCRIPTION, DEFAULT_NAME
    tool = QueryEngineTool.from_defaults(query_engine=object())
    # 条件路由的候选描述恒为这两段（retriever.get_description() 恒 None）
    assert tool.metadata.name == DEFAULT_NAME == 'query_engine_tool'
    assert tool.metadata.description == DEFAULT_DESCRIPTION
    assert tool.metadata.description.startswith('Useful for running a natural language query')
