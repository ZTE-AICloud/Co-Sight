"""知识图谱检索算子（`KnowledgeGraphRetriever`）+ RKB 图谱网关的测试。

数据源：RKB 的 `POST /api/co-knowledge/v1/retrieval/graph`。与其余端点同一契约：2xx 的 body 就是图数据对象 `{"base_results": [...]}`，失败是真实
HTTP 状态码 + problem+json。这里钉住的是：非 2xx 必须抛错，不能退化成「检索为空」；
2xx 的非对象 body 也必须显式失败。

第二条链是两条处理路径：有 `chunks` → chunk 路径；没有 `chunks`（或实体都没有 chunk_id）
→ BFS 子图路径。两条路径的 metadata 键集合与引用标记都是前端事实契约。

第三条链（用户点名）：`_retrieve` 的异常**必须冒泡** —— `try/except -> return []`
会造出「HTTP 200、其实没检索」的隐形失败。
"""

import pytest
from engine.primitives.models import QueryBundle


from engine.common import const
from engine.common.beans.rag_request_headers import RagRequestHeaders
from engine.common.exception.rag_exception import RagException
from engine.gateways import knowledge_base_client as kb
from engine.retriever import knowledgegraph_retriever as kgr
from engine.retriever.base import BaseRagRetriever
from engine.retriever.knowledgegraph_retriever import KnowledgeGraphRetriever

QUESTION = '张三的同事是谁？'

# 两条路径产出的 metadata 键集合完全一致（前端按这套键取值）
METADATA_KEYS = {
    'source', 'content_expand', 'knowledge_name', 'chunk_id', 'chunk_order',
    'spilt_type', 'label', 'table_name', 'table_id', 'related_chunk_ids',
}


def _config(**kwargs):
    config = {'headers': RagRequestHeaders(language_option='en'),
              'knowledge_base_name': ['graph_kb_1'],
              'embedding': 'bge-m3'}
    config.update(kwargs)
    return config


def graph_data(base_results):
    """RKB 图谱检索的成功 body（`GraphQueryService._build_retrieve_result`）。"""
    return {'base_results': base_results, 'total_entities': 0,
            'total_edges': 0, 'base_count': len(base_results)}


# ---------------------------------------------------------------------------
# 网关：调 RKB 图谱检索
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_post(monkeypatch):
    """换掉进程内 transport，记录 body/headers。

    四条调用走进程内直调（`rkb_transport`），**没有 URL 可断言** ——
    断言「递过去的 body/headers」。
    """
    captured = {}

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    def _install(payload, status_code=200):
        def _post(body, headers=None):
            captured['body'] = body
            captured['headers'] = headers
            return FakeResponse(payload, status_code)

        from types import SimpleNamespace
        monkeypatch.setattr(kb, '_transport', SimpleNamespace(post_graph_retrieve=_post))
        return captured

    return _install


def test_graph_client_returns_the_plain_result_body(fake_post):
    captured = fake_post(graph_data([{'base': 'graph_kb_1'}]))

    data = kb.invoke_knowledge_graph_client({'Content-Type': 'application/json'},
                                            {'query': QUESTION})

    assert data['base_results'] == [{'base': 'graph_kb_1'}]
    assert captured['body'] == {'query': QUESTION}
    assert captured['headers'] == {'Content-Type': 'application/json'}


def test_graph_client_raises_on_a_non_object_success_body(fake_post):
    """2xx 但 body 不是对象（例如空的 problem 解析失败）必须显式失败。"""
    fake_post([], status_code=200)

    with pytest.raises(RagException) as excinfo:
        kb.invoke_knowledge_graph_client({}, {'query': QUESTION})

    assert excinfo.value.get_error_tag() == 'request-knowledge-graph-failed'
    assert excinfo.value.get_error_code() == -2


def test_graph_client_raises_on_http_error(fake_post):
    fake_post({'code': 0, 'message': '成功'}, status_code=500)

    with pytest.raises(RagException) as excinfo:
        kb.invoke_knowledge_graph_client({}, {'query': QUESTION})

    assert excinfo.value.get_error_tag() == 'bad-status-code'


# ---------------------------------------------------------------------------
# 装配与请求体
# ---------------------------------------------------------------------------

def test_from_args_keeps_the_config_info_and_is_a_rag_retriever():
    config = _config()
    operator = KnowledgeGraphRetriever.from_args(config)

    assert isinstance(operator, KnowledgeGraphRetriever)
    # 分桶靠这个类型判定（OperatorBean：isinstance(operator, BaseRagRetriever) → retrievers）
    assert isinstance(operator, BaseRagRetriever)
    assert operator.config_info is config
    assert operator.header is config['headers']
    assert operator.get_description() == ''


def test_operator_is_instantiable_through_the_real_loading_path():
    """画布 → 内置清单 → 实例化：`instance_operator` 按清单解析包名，
    并把 headers / user_request 注进 kwargs（`_pre_setting_params`）。"""
    from engine.rag_utils import instance_operator

    operator = instance_operator(
        'core.rag.retriever.knowledgegraph_retriever', 'KnowledgeGraphRetriever',
        {'knowledge_base_name': ['graph_uuid_1|#|图谱库一'], 'top_k': 5,
         'headers': RagRequestHeaders(language_option='en'), 'user_request': None})

    assert isinstance(operator, KnowledgeGraphRetriever)
    body = operator._build_request_body(QUESTION)
    assert body['bases'] == ['graph_uuid_1']
    assert body['seed_k'] == 5


def test_build_request_body_shape_strips_base_suffix():
    operator = KnowledgeGraphRetriever(_config(
        knowledge_base_name=['graph_uuid_1|#|图谱库一', 'graph_uuid_2'],
        top_k=30, depth=3, score=0.5))

    body = operator._build_request_body(QUESTION)

    assert body == {
        'query': QUESTION,
        'embedding': 'bge-m3',
        'bases': ['graph_uuid_1', 'graph_uuid_2'],
        'seed_k': 30,
        'depth': 3,
        'score': 0.5,
    }


def test_build_request_body_falls_back_to_defaults():
    operator = KnowledgeGraphRetriever({'knowledge_base_name': ['graph_uuid_1']})

    body = operator._build_request_body(QUESTION)

    assert body['embedding'] == ''
    assert body['seed_k'] == 10  # 画布没存 top_k 时的兜底
    assert body['depth'] == 1
    assert body['score'] == 0


def test_retrieve_sends_built_body_and_built_headers_to_the_client(monkeypatch):
    captured = {}

    def _invoke(headers, body):
        captured['headers'] = headers
        captured['body'] = body
        return graph_data([])

    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client', _invoke)
    operator = KnowledgeGraphRetriever(_config(knowledge_base_name=['graph_uuid_1|#|图谱库一']))

    nodes = operator._retrieve(QueryBundle(query_str=QUESTION))

    assert nodes == []
    assert captured['body']['query'] == QUESTION
    assert captured['body']['bases'] == ['graph_uuid_1']
    # build_headers 把请求头上下文的语言带下去（RKB 用它选错误消息语言）
    assert captured['headers']['Content-Type'] == 'application/json'
    assert captured['headers']['X-Lang-Id'] == 'en'


# ---------------------------------------------------------------------------
# 异常必须冒泡（不许静默空返回）
# ---------------------------------------------------------------------------

def test_retrieve_lets_client_errors_bubble(monkeypatch):
    """检索失败不能伪装成「检索为空」：用户会拿到一个没有引用的正常回答。
    必须抛。"""
    def _boom(headers, body):
        raise RagException(-2, 'request-knowledge-graph-failed')

    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client', _boom)
    operator = KnowledgeGraphRetriever(_config())

    with pytest.raises(RagException) as excinfo:
        operator._retrieve(QueryBundle(query_str=QUESTION))

    assert excinfo.value.get_error_tag() == 'request-knowledge-graph-failed'


def test_per_base_processing_error_is_raised_with_the_base_name(monkeypatch):
    """N 个库里坏掉 1 个不能悄悄丢掉：要记 error 后抛出，
    并且异常里带上 base 名。"""
    def _boom(base_result, base_name, chunks, depth, **_kwargs):
        raise ValueError('bad shape')

    monkeypatch.setattr(kgr, '_process_base_result', _boom)
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([{'base': 'graph_kb_broken'}]))
    operator = KnowledgeGraphRetriever(_config())

    with pytest.raises(RagException) as excinfo:
        operator._retrieve(QueryBundle(query_str=QUESTION))

    assert excinfo.value.get_error_tag() == 'request-knowledge-graph-failed'
    assert 'graph_kb_broken' in excinfo.value.get_args()
    assert isinstance(excinfo.value.__cause__, ValueError)


# ---------------------------------------------------------------------------
# 路径一：有 chunks → chunk 路径
# ---------------------------------------------------------------------------

def _chunk_base_result():
    return {
        'base': 'graph_kb_1',
        'entities': [
            {'entity_id': 'e1', 'name': '张三', 'chunk_id': 'c1'},
            {'entity_id': 'e2', 'name': '李四', 'chunk_id': 'c1,c2'},
            {'entity_id': 'e3', 'name': '王五', 'chunk_id': 'c3'},
        ],
        'edges': [
            {'source_id': 'e1', 'target_id': 'e2', 'type': '同事'},
            {'source_id': 'e1', 'target_id': 'e3', 'type': '上级'},
        ],
        'seed_entity_ids': ['e1', 'e2'],
        'chunks': {
            'c1': {'chunk_id': 'c1', 'text': '切片一', 'source': 'doc.md', 'chunk_order': 1,
                   'spilt_type': 'text', 'label': 'l1', 'table_name': 't', 'table_id': 'tid'},
            'c2': {'chunk_id': 'c2', 'text': '切片二', 'source': 'doc.md'},
            'c3': {'chunk_id': 'c3', 'text': '切片三', 'source': 'doc2.md'},
        },
    }


def test_chunk_path_builds_nodes_and_merges_related_chunk_ids(monkeypatch):
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([_chunk_base_result()]))
    operator = KnowledgeGraphRetriever(_config())

    nodes = operator._retrieve(QueryBundle(query_str=QUESTION))

    # c1/c2 是种子 chunk，c3 是「非种子语义命中」兜底进来的
    assert [n.node.metadata['chunk_id'] for n in nodes] == ['c1', 'c2', 'c3']
    by_chunk = {n.node.metadata['chunk_id']: n for n in nodes}

    # c1 被 e1、e2 两个种子实体同时命中 → related_chunk_ids 走合并分支（去重后的并集）
    assert set(by_chunk['c1'].node.metadata['related_chunk_ids']) == {'c2', 'c3'}
    # c2 只在 e2 下被命中，邻居 e1 的 chunk 是 c1
    assert by_chunk['c2'].node.metadata['related_chunk_ids'] == ['c1']
    # 非种子 chunk 的兜底：related_chunk_ids 为空
    assert by_chunk['c3'].node.metadata['related_chunk_ids'] == []


def test_chunk_path_metadata_keys_and_citation_markers(monkeypatch):
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([_chunk_base_result()]))
    operator = KnowledgeGraphRetriever(_config())

    node = operator._retrieve(QueryBundle(query_str=QUESTION))[0]

    assert node.base_name == 'graph_kb_1'
    assert node.score == 0.0
    metadata = node.node.metadata
    assert set(metadata.keys()) == METADATA_KEYS
    # 正文进 text、content_expand 置空（防重复喂模型），三个引用标记是前端契约
    assert node.node.text == f"{const.expand_format}切片一{const.expand_format}"
    assert metadata['content_expand'] == ''
    assert metadata['source'] == f"{const.source_format}doc.md{const.source_format}"
    assert metadata['knowledge_name'] == f"{const.base_format}graph_kb_1{const.base_format}"
    assert metadata['spilt_type'] == 'text'  # 拼写固定为 spilt_type（不是 split_type），不能改
    assert metadata['chunk_order'] == 1


def test_chunk_path_can_include_one_and_two_hop_edge_facts(monkeypatch):
    """`include_edge_facts=True`：seed 的直接边与一跳邻居上的属性边要进正文。

    2Wiki 的典型失败是「问父亲的生日」：图里有
    `父亲 --date of birth--> 1654`，但 chunk 模式只回 seed chunk，答案边没进上下文。
    """
    base_result = {
        'base': 'graph_kb_1',
        'entities': [
            {'entity_id': 'e1', 'entity_name': '张三', 'chunk_id': 'c1'},
            {'entity_id': 'e2', 'entity_name': '李四', 'chunk_id': 'c2'},
            {'entity_id': 'e3', 'entity_name': '1654', 'chunk_id': 'c2'},
        ],
        'edges': [
            # 与 `/retrieval/graph` 的真实形状一致：关系字段在顶层
            {'source_id': 'e1', 'target_id': 'e2',
             'relationship_keywords': 'father'},
            {'source_id': 'e2', 'target_id': 'e3',
             'relationship_keywords': 'date of birth',
             'relationship_description': '李四 was born in 1654.'},
        ],
        'seed_entity_ids': ['e1'],
        'chunks': {
            'c1': {'chunk_id': 'c1', 'text': '张三的切片', 'source': 'doc.md'},
            'c2': {'chunk_id': 'c2', 'text': '李四的切片', 'source': 'doc.md'},
        },
    }
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([base_result]))
    operator = KnowledgeGraphRetriever(_config(include_edge_facts=True, depth=2))

    nodes = operator._retrieve(QueryBundle(query_str=QUESTION))
    by_chunk = {n.node.metadata['chunk_id']: n for n in nodes}

    text = by_chunk['c1'].node.text
    assert 'Knowledge graph facts:' in text
    assert '张三 --[father]--> 李四' in text
    assert '李四 --[date of birth]--> 1654' in text
    assert '李四 was born in 1654.' in text


def test_edge_facts_do_not_expand_through_date_hubs(monkeypatch):
    """`1966` 这类年份节点度数很高；只保留 seed→年份这条边，不沿它扩散。"""
    base_result = {
        'base': 'graph_kb_1',
        'entities': [
            {'entity_id': 'e1', 'entity_name': '张三', 'chunk_id': 'c1'},
            {'entity_id': 'e2', 'entity_name': '李四', 'chunk_id': 'c2'},
            {'entity_id': 'e3', 'entity_name': '1654', 'chunk_id': 'c2'},
            {'entity_id': 'e4', 'entity_name': 'Other Film', 'chunk_id': 'c3'},
        ],
        'edges': [
            {'source_id': 'e1', 'target_id': 'e2', 'relationship_keywords': 'father'},
            {'source_id': 'e2', 'target_id': 'e3',
             'relationship_keywords': 'date of birth',
             'relationship_description': '李四 was born in 1654.'},
            {'source_id': 'e4', 'target_id': 'e3',
             'relationship_keywords': 'release date',
             'relationship_description': 'Other Film was released in 1654.'},
        ],
        'seed_entity_ids': ['e1'],
        'chunks': {
            'c1': {'chunk_id': 'c1', 'text': '张三的切片', 'source': 'doc.md'},
            'c2': {'chunk_id': 'c2', 'text': '李四的切片', 'source': 'doc.md'},
        },
    }
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([base_result]))
    operator = KnowledgeGraphRetriever(_config(include_edge_facts=True, depth=2))

    text = operator._retrieve(QueryBundle(query_str=QUESTION))[0].node.text

    assert '李四 --[date of birth]--> 1654' in text
    assert 'Other Film' not in text


def test_edge_facts_drop_leading_honorifics(monkeypatch):
    """`King Gustaf / Gustaf` 不应在上下文里表现成两个名字。"""
    base_result = {
        'base': 'graph_kb_1',
        'entities': [
            {'entity_id': 'e1', 'entity_name': 'King Gustaf VI Adolf', 'chunk_id': 'c1'},
            {'entity_id': 'e2', 'entity_name': 'Sweden', 'chunk_id': 'c2'},
        ],
        'edges': [
            {'source_id': 'e1', 'target_id': 'e2',
             'relationship_keywords': 'country of citizenship'},
        ],
        'seed_entity_ids': ['e1'],
        'chunks': {
            'c1': {'chunk_id': 'c1', 'text': '古斯塔夫六世', 'source': 'doc.md'},
            'c2': {'chunk_id': 'c2', 'text': '瑞典', 'source': 'doc.md'},
        },
    }
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([base_result]))
    operator = KnowledgeGraphRetriever(_config(include_edge_facts=True, depth=1))

    text = operator._retrieve(QueryBundle(query_str=QUESTION))[0].node.text

    assert 'Gustaf VI Adolf --[country of citizenship]--> Sweden' in text
    assert 'King Gustaf' not in text


def test_chunk_path_does_not_include_edge_facts_by_default(monkeypatch):
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([_chunk_base_result()]))
    operator = KnowledgeGraphRetriever(_config(depth=2))

    nodes = operator._retrieve(QueryBundle(query_str=QUESTION))

    assert all('Knowledge graph facts:' not in n.node.text for n in nodes)


def test_chunks_without_any_entity_chunk_id_still_use_the_subgraph_path(monkeypatch):
    """`_check_need_subgraph_processing` 的第二个触发条件：有 chunks，但所有实体都没有 chunk_id。"""
    base_result = {
        'base': 'graph_kb_1',
        'entities': [{'entity_id': 'e1', 'name': '张三'}, {'entity_id': 'e2', 'name': '李四'}],
        'edges': [{'source_id': 'e1', 'target_id': 'e2', 'type': '同事'}],
        'seed_entity_ids': ['e1'],
        'chunks': {'c9': {'chunk_id': 'c9', 'text': '与图谱无关的语义命中'}},
    }
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([base_result]))
    operator = KnowledgeGraphRetriever(_config())

    nodes = operator._retrieve(QueryBundle(query_str=QUESTION))

    assert len(nodes) == 1
    assert 'Entity[Level 0]: 张三' in nodes[0].node.text
    assert '张三 --[同事]--> 李四' in nodes[0].node.text
    assert nodes[0].node.metadata['chunk_id'] == ''


# ---------------------------------------------------------------------------
# 路径二：没有 chunks → BFS 子图路径
# ---------------------------------------------------------------------------

def _subgraph_base_result():
    return {
        'base': 'graph_kb_2',
        'entities': [
            {'entity_id': 'e1', 'name': '张三', 'type': 'Person', 'source': 'g.md', 'age': '30'},
            {'entity_id': 'e2', 'name': '李四', 'type': 'Person'},
            {'entity_id': 'e3', 'name': 'Acme'},
        ],
        'edges': [
            {'source_id': 'e1', 'target_id': 'e2', 'type': '同事'},
            {'source_id': 'e2', 'target_id': 'e3'},
        ],
        'seed_entity_ids': ['e1'],
        'chunks': {},
    }


def test_subgraph_path_builds_bfs_text_and_metadata(monkeypatch):
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([_subgraph_base_result()]))
    operator = KnowledgeGraphRetriever(_config(depth=2))

    nodes = operator._retrieve(QueryBundle(query_str=QUESTION))

    assert len(nodes) == 1
    node = nodes[0]
    assert node.base_name == 'graph_kb_2'
    assert node.node.text == f"{const.expand_format}" + '\n'.join([
        'Entity[Level 0]: 张三 (Type: Person)',
        '  - source: g.md',
        '  - age: 30',
        'Entity[Level 1]: 李四 (Type: Person)',
        'Entity[Level 2]: Acme',
        '',
        'Relations:',
        '  张三 --[同事]--> 李四',
        '  李四 -> Acme',
    ]) + f"{const.expand_format}"

    metadata = node.node.metadata
    assert set(metadata.keys()) == METADATA_KEYS
    assert metadata['source'] == f"{const.source_format}g.md{const.source_format}"
    assert metadata['knowledge_name'] == f"{const.base_format}graph_kb_2{const.base_format}"
    assert metadata['content_expand'] == ''
    assert metadata['chunk_id'] == ''
    assert metadata['related_chunk_ids'] == []
    # 图谱节点在前端没有引用序号：node_id / chunk_index 从未被这条链路写过
    assert 'node_id' not in metadata and 'chunk_index' not in metadata


def test_subgraph_depth_limits_the_bfs(monkeypatch):
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([_subgraph_base_result()]))
    operator = KnowledgeGraphRetriever(_config(depth=1))

    node = operator._retrieve(QueryBundle(query_str=QUESTION))[0]

    assert 'Entity[Level 1]: 李四' in node.node.text
    assert 'Acme' not in node.node.text


def test_subgraph_path_skips_bases_without_seed_entities(monkeypatch):
    """没有种子实体（没命中任何东西）的库返回空节点，不影响同批其它库。"""
    empty = {'base': 'graph_kb_2', 'entities': [], 'edges': [], 'seed_entity_ids': [], 'chunks': {}}
    monkeypatch.setattr(kgr, 'invoke_knowledge_graph_client',
                        lambda headers, body: graph_data([_subgraph_base_result(), empty]))
    operator = KnowledgeGraphRetriever(_config(depth=1))

    nodes = operator._retrieve(QueryBundle(query_str=QUESTION))

    assert [n.base_name for n in nodes] == ['graph_kb_2']
