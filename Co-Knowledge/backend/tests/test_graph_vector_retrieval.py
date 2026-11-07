"""图谱**读侧**回归：向量种子检索的 SQL 形状、种子解析与子图装配。

写侧（``graph_index_store`` 把实体/边/切片写进 ``graph_<uuid>_vector``）已有
``test_graph_index_store.py``；本文件钉住读侧那一半：

    graph_<uuid>_vector --(_build_retrieve_sql)--> key_id/source_id/target_id
    --(_extract_entity_ids_from_records)--> seed entity ids
    --(_retrieve_subgraph_for_base)--> PG BFS 子图（见 graph_query_service）

**为什么值得钉**：表不存在时必须显式失败，不能静默返回空结果。
读侧的三个契约仍可能被顺手改坏而测试全绿：
参数化顺序、边身份（``edge_id`` vs 旧 ``"<source>,<target>"``）、chunk 固定 top_50。
"""
from __future__ import annotations

import pytest

from graph.models.graph_retrieve_dto import GraphRetrieveDto
from graph.service import graph_query_service as gqs

EMBEDDING = '[0.1,0.2,0.3]'


def _service():
    """不跑 ``__init__``：那里会连 PG；本文件测的方法都不依赖实例状态。"""
    return object.__new__(gqs.GraphQueryService)


# ----------------------------------------------------------------------
# SQL：全部参数化 + 余弦距离阈值与 ORDER BY 用同一个可索引表达式
# ----------------------------------------------------------------------


def test_retrieve_sql_keeps_every_value_parameterized():
    sql, params = gqs._build_retrieve_sql(
        'graph_abc123', 'entity', EMBEDDING, 5, 0.25)

    assert 'kb_index.graph_abc123_vector' in sql
    assert 'key_type = %s' in sql
    assert 'embedding <=> %s::vector <= %s' in sql
    assert 'ORDER BY' in sql and 'LIMIT %s' in sql
    # 任何入参都不能被拼进 SQL 文本（历史注入点）
    assert EMBEDDING not in sql
    assert 'entity' not in sql
    # 参数顺序：SELECT 的向量 → WHERE(key_type, 向量, 距离上限) → ORDER BY → LIMIT
    assert params == [EMBEDDING, 'entity', EMBEDDING, 0.75, EMBEDDING, 5]


def test_retrieve_sql_labels_take_effect_only_when_present():
    sql, params = gqs._build_retrieve_sql(
        'graph_abc123', 'edge', EMBEDDING, 3, 0.0, ['Person', 'Knows'])

    assert 'labels && %s::text[]' in sql
    assert params == [EMBEDDING, 'edge', EMBEDDING, 1.0, ['Person', 'Knows'], EMBEDDING, 3]

    sql_without, params_without = gqs._build_retrieve_sql(
        'graph_abc123', 'edge', EMBEDDING, 3, 0.0, [])
    assert 'labels &&' not in sql_without
    assert params_without == [EMBEDDING, 'edge', EMBEDDING, 1.0, EMBEDDING, 3]


def test_retrieve_sql_rejects_illegal_base():
    with pytest.raises(ValueError):
        gqs._build_retrieve_sql('graph_x; DROP TABLE t', 'entity', EMBEDDING, 5, 0.0)


# ----------------------------------------------------------------------
# 种子解析：实体用 key_id；边优先端点列，旧行才拆逗号
# ----------------------------------------------------------------------


def test_extract_entity_seed_ids():
    records = [{'key_id': 'Entity_1'}, {'key_id': 'Entity_2'}]

    assert gqs.GraphQueryService._extract_entity_ids_from_records(
        _service(), records, 'entity') == ['Entity_1', 'Entity_2']


def test_extract_edge_seed_ids_prefers_endpoint_columns():
    """新行 ``key_id = edge_id``，不能按逗号拆（会拆坏 id）。"""
    records = [{
        'key_id': 'Knows_0001', 'source_id': 'Entity_1', 'target_id': 'Entity_2'}]

    assert gqs.GraphQueryService._extract_entity_ids_from_records(
        _service(), records, 'edge') == ['Entity_1', 'Entity_2']


def test_extract_edge_seed_ids_ignores_key_id_without_endpoints():
    records = [{'key_id': 'Entity_1,Entity_2', 'source_id': None, 'target_id': None}]

    assert gqs.GraphQueryService._extract_entity_ids_from_records(
        _service(), records, 'edge') == []


def test_extract_edge_seed_ids_tolerates_one_missing_endpoint():
    records = [{'key_id': 'R1', 'source_id': 'Entity_1', 'target_id': None}]

    assert gqs.GraphQueryService._extract_entity_ids_from_records(
        _service(), records, 'edge') == ['Entity_1']


# ----------------------------------------------------------------------
# 种子合并：entity/edge 用 DTO 的 seed_k，chunk 固定 CHUNK_SEED_K
# ----------------------------------------------------------------------


def test_retrieve_seed_ids_merges_entity_edge_and_chunk(monkeypatch):
    service = _service()
    calls = []
    rows = {
        'entity': [{'key_id': 'Entity_1'}, {'key_id': 'Entity_2'}],
        'edge': [{'key_id': 'Knows_1', 'source_id': 'Entity_2',
                  'target_id': 'Entity_3'}],
        'chunk': [{'key_id': 'chunk_a'}, {'key_id': 'chunk_b'}],
    }

    def fake_query(base, key_type, query_embedding, dto, seed_k=None):
        calls.append((key_type, seed_k))
        return rows[key_type]

    monkeypatch.setattr(service, '_query_vector_index', fake_query)
    dto = GraphRetrieveDto(query='q', embedding='m', bases=['graph_x'], seed_k=7)

    entity_ids, chunk_ids = service._retrieve_seed_ids('graph_x', EMBEDDING, dto)

    # 去重后合并（entity + edge 两端）
    assert set(entity_ids) == {'Entity_1', 'Entity_2', 'Entity_3'}
    assert set(chunk_ids) == {'chunk_a', 'chunk_b'}
    # chunk 的 top_k 不随 DTO；entity/edge 走 DTO 默认（函数内读取）
    assert calls == [('entity', None), ('edge', None), ('chunk', gqs.CHUNK_SEED_K)]


# ----------------------------------------------------------------------
# 路由：对外前缀必须有入口，且必须早于 kb_api 的兜底路由
# ----------------------------------------------------------------------


def test_graph_retrieve_registered_under_public_prefix_before_catch_all():
    from app import app
    from shared.prefixes import GRAPH_RETRIEVE_PATH, RKB_PREFIX

    from route_helpers import route_paths

    paths = route_paths(app)
    catch_all = f'{RKB_PREFIX}/{{unknown_path:path}}'

    assert GRAPH_RETRIEVE_PATH in paths, '对外前缀下缺图谱检索入口'
    assert catch_all in paths, 'kb_api 兜底路由不见了，本用例的前提已变'
    assert paths.index(GRAPH_RETRIEVE_PATH) < paths.index(catch_all), \
        '图谱检索注册在兜底路由之后，会被 200+0005 吃掉'
