"""检索响应适配器测试。

契约两端：
  对外契约检索响应 = {baseName, docs:[{chunkId, content, score, sourceDocId, metadata}]}
  运行时 node      = metadata 里带 content_expand / node_id / source / chunk_index，
                     并被包装上引用标记 |*expand#| |*source#| |*knowledge_name#| |*chunk_index#|

引用标记是前端渲染引用的事实契约，这里逐条钉住。
"""

import pytest


from engine.common import const
from engine.gateways import knowledge_base_client as kb


def kb_response(results):
    return results


@pytest.fixture
def fake_post(monkeypatch):
    captured = {}

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    def _install(payload, status_code=200):
        # 出站调用走进程内 transport（无 URL 可断言），
        # 仍记录 body/headers —— 那是「递过去什么」的契约。
        def _post(body, headers=None):
            captured['body'] = body
            captured['headers'] = headers
            return FakeResponse(payload, status_code)
        from types import SimpleNamespace
        monkeypatch.setattr(kb, '_transport', SimpleNamespace(post_retrieve=_post))
        return captured

    return _install


def test_maps_search_result_to_runtime_node_with_citation_markers(fake_post):
    captured = fake_post(kb_response([{
        'baseName': 'doc_7',
        'docs': [{
            'chunkId': 'chunk-1',
            'content': '切片正文',
            'score': 0.9,
            'sourceDocId': 'file-9',
            'metadata': {'chunk_index': 3, 'source': 'doc.md'},
        }],
    }]))

    nodes = kb.invoke_knowledge_base_client({'Content-Type': 'application/json'},
                                            {'question': 'q', 'type': 0, 'bases': []})

    assert len(nodes) == 1
    node = nodes[0]
    assert node.score == 0.9
    assert node.base_name == 'doc_7'
    metadata = node.node.metadata
    assert metadata['source'] == f"{const.source_format}file-9{const.source_format}"
    assert metadata['node_id'] == f"{const.node_id_format}chunk-1{const.node_id_format}"
    assert metadata['knowledge_name'] == f"{const.base_format}doc_7{const.base_format}"
    assert metadata['chunk_index'] == f"{const.chunk_index_format}3{const.chunk_index_format}"
    # 正文被搬进 text，metadata.content_expand 被清空（防止重复喂给模型）
    assert node.node.text == f"{const.expand_format}切片正文{const.expand_format}"
    assert metadata['content_expand'] == ''
    # 证据面板要展示可读文件名：放在 Node 属性上，不进 metadata、不进提示词。
    # MetadataMode 延迟导入：模块级导入会触发 core.rag 包初始化，与网关形成循环。
    from engine.primitives.models import MetadataMode
    assert node.node.source_name == 'doc.md'
    assert 'source_name' not in metadata
    assert 'doc.md' not in node.node.get_content(metadata_mode=MetadataMode.LLM)
    assert captured['body']['type'] == 0


def test_keyword_response_with_chunk_id_and_type_keeps_unified_metadata(fake_post):
    """ES 补齐 chunk_id/type 后，关键词路与向量路的 metadata 形状一致。"""
    fake_post(kb_response([{
        'baseName': 'doc_7',
        'docs': [{
            'chunkId': '1', 'content': '关键词正文', 'score': 2.5,
            'sourceDocId': 'file-1',
            'metadata': {'chunk_index': '', 'source': 'a.md', 'chunk_id': 1, 'type': 0},
        }],
    }]))

    nodes = kb.invoke_knowledge_base_client({}, {'question': 'q', 'type': 1, 'bases': []})

    metadata = nodes[0].node.metadata
    assert metadata['node_id'] == f"{const.node_id_format}1{const.node_id_format}"
    assert metadata['source'] == f"{const.source_format}file-1{const.source_format}"
    assert metadata['chunk_index'] == f"{const.chunk_index_format}{const.chunk_index_format}"
    assert metadata['chunk_id'] == 1
    assert metadata['type'] == 0


def test_null_chunk_id_and_source_do_not_break_conversion(fake_post):
    """chunkId/sourceDocId 在部分路径本就为 null
    （ES 关键词路没有 chunk_id、向量路没有 file_id）—— 不能因此炸，引用会稀疏而已。"""
    fake_post(kb_response([{
        'baseName': 'doc_7',
        'docs': [{'chunkId': None, 'content': '正文', 'score': 0.5, 'sourceDocId': None, 'metadata': {}}],
    }]))

    nodes = kb.invoke_knowledge_base_client({}, {'question': 'q', 'type': 0, 'bases': []})

    assert len(nodes) == 1
    assert nodes[0].node.metadata['source'] == f"{const.source_format}{const.source_format}"
    assert nodes[0].node.metadata['node_id'] == f"{const.node_id_format}{const.node_id_format}"


def test_bases_without_docs_are_dropped_and_results_sorted_by_score(fake_post):
    fake_post(kb_response([
        {'baseName': 'empty-base', 'docs': []},
        {'baseName': 'low', 'docs': [{'chunkId': 'a', 'content': '低分', 'score': 0.1, 'metadata': {}}]},
        {'baseName': 'high', 'docs': [{'chunkId': 'b', 'content': '高分', 'score': 0.8, 'metadata': {}}]},
    ]))

    nodes = kb.invoke_knowledge_base_client({}, {'question': 'q', 'type': 0, 'bases': []})

    assert [n.base_name for n in nodes] == ['high', 'low']


def test_duplicate_chunk_text_is_kept_once(fake_post):
    """按 text 去重（同一个切片被两个库命中时只留一份）。"""
    fake_post(kb_response([
        {'baseName': 'b1', 'docs': [{'chunkId': 'a', 'content': '同样的正文', 'score': 0.9, 'metadata': {}}]},
        {'baseName': 'b2', 'docs': [{'chunkId': 'c', 'content': '同样的正文', 'score': 0.8, 'metadata': {}}]},
    ]))

    nodes = kb.invoke_knowledge_base_client({}, {'question': 'q', 'type': 0, 'bases': []})

    assert len(nodes) == 1


def test_business_error_code_becomes_exception_not_empty_result(fake_post):
    """检索接口返回业务错误时**必须抛**，不能退化成「检索为空」——
    否则用户拿到的是一个没有检索结果的正常回答。"""
    from engine.common.exception.rag_exception import RagException

    fake_post({'code': 'workflow_not_found', 'status': 404, 'detail': 'boom'},
              status_code=404)

    with pytest.raises(RagException):
        kb.invoke_knowledge_base_client({}, {'question': 'q', 'type': 0, 'bases': []})


def test_http_error_becomes_exception(fake_post):
    from engine.common.exception.rag_exception import RagException

    fake_post({'code': {'code': '0000'}, 'bo': []}, status_code=500)

    with pytest.raises(RagException):
        kb.invoke_knowledge_base_client({}, {'question': 'q', 'type': 0, 'bases': []})
