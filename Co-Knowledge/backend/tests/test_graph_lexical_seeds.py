"""图谱检索的词面种子：问题里出现的实体名直接进种子，并命中缓存。"""
from graph.repository import graph_pg
from graph.service import graph_query_service as svc


def _service():
    return object.__new__(svc.GraphQueryService)


def test_lexical_seeds_find_topic_and_cache(monkeypatch):
    svc._MENTION_CACHE.clear()
    calls = []

    def fake_entity_names(base, limit=100000):
        calls.append(base)
        return [('E1', 'Tom McLoughlin'), ('E2', 'Someone Else')]

    monkeypatch.setattr(graph_pg, 'entity_names', fake_entity_names,
                        raising=True)
    service = _service()

    assert service._lexical_seed_entity_ids(
        'graph_demo', 'what did Tom McLoughlin direct') == ['E1']
    assert service._lexical_seed_entity_ids(
        'graph_demo', 'what did Tom McLoughlin direct') == ['E1']
    assert calls == ['graph_demo']


def test_lexical_seeds_can_be_disabled(monkeypatch):
    monkeypatch.setenv('GRAPH_LEXICAL_SEEDS_ENABLED', '0')
    service = _service()
    assert service._lexical_seed_entity_ids('graph_demo', 'Tom McLoughlin') == []


def test_lexical_match_focuses_seeds_and_drops_vector_noise(monkeypatch):
    from graph.models.graph_retrieve_dto import GraphRetrieveDto

    service = _service()
    service._lexical_seed_entity_ids = lambda base, query: ['TOPIC']

    def fake_query(base, key_type, embedding, dto, seed_k=None):
        if key_type == 'entity':
            return [{'key_id': 'VEC1'}, {'key_id': 'VEC2'}]
        if key_type == 'edge':
            return [{'key_id': 'E1', 'source_id': 'VEC3', 'target_id': 'VEC4'}]
        return []

    service._query_vector_index = fake_query
    # 默认 backfill=5；单个专名命中时不启用兜底。
    dto = GraphRetrieveDto(query='q', embedding='m', bases=['b'],
                           seed_k=10, depth=1, limit=1000)

    entities, chunks = service._retrieve_seed_ids('graph_demo', 'emb', dto)
    assert entities == ['TOPIC']
    assert chunks == []


def test_lexical_match_can_keep_vector_backfill(monkeypatch):
    from graph.models.graph_retrieve_dto import GraphRetrieveDto

    service = _service()
    # 多个专名命中 = 描述型提问（提到的是邻居），保留向量兜底。
    service._lexical_seed_entity_ids = lambda base, query: ['TOPIC', 'NEIGHBOR']

    def fake_query(base, key_type, embedding, dto, seed_k=None):
        if key_type == 'entity':
            return [{'key_id': 'VEC1'}, {'key_id': 'VEC2'}]
        return []

    service._query_vector_index = fake_query
    monkeypatch.setattr(svc, '_LEXICAL_VECTOR_BACKFILL', 1)
    dto = GraphRetrieveDto(query='q', embedding='m', bases=['b'],
                           seed_k=10, depth=1, limit=1000)

    entities, _chunks = service._retrieve_seed_ids('graph_demo', 'emb', dto)
    assert entities == ['TOPIC', 'NEIGHBOR', 'VEC1']


def test_query_embedding_uses_qwen_instruction(monkeypatch):
    from graph.models.graph_retrieve_dto import GraphRetrieveDto
    from model import llm_gateway

    captured = {}

    def fake_embedding(text, model, headers):
        captured['text'] = text
        return [0.1, 0.2]

    monkeypatch.setattr(llm_gateway, 'get_embedding_info', fake_embedding)
    service = _service()
    dto = GraphRetrieveDto(query='who directed Kismet', embedding='m', bases=['b'])

    assert service._get_query_embedding(dto, None) == [0.1, 0.2]
    assert captured['text'].startswith('Instruct: Retrieve the entity')
    assert captured['text'].endswith('who directed Kismet')
