"""``POST /graph/review``（图谱审阅）。

对照 ``GraphReviewServiceImpl.queryGraphReview``。

## 这个接口的三条反直觉之处

1. **它什么都不改**。名字叫「审阅/审核」，但实现是**纯读**：不写任何状态、
   也不调 ``setKbaseStatusModified``。返回的是 ``graph_<kbId>`` 里按起点
   条件遍历出来的实体与边。
2. **入参校验是 0004，不是 0005**。四条校验都走 0004
   → ``RetCode.ValidationError``；而同一个域里 ``query`` 的校验是 0005。
   两个兄弟端点两套错误码，别统一。
3. **数据库出错不抛，回空结果**。整段查询包在兜底捕获里 ——
   图库连不上、SQL 报错，对外都是「空图」而不是错误。这是刻意的（审阅页不该因为
   图库抖动就报错），但排障时要记得去日志里找。

另外：``kbId`` 在这里是 **camelCase 且不带 ``graph_`` 前缀**；而 ``query`` 用的是
snake_case 的 ``kb_id`` 且**必须带**前缀。两个端点的约定恰好相反。
"""

from __future__ import annotations

from graph.repository import graph_pg
from shared.errors.api import KbApiError
from infrastructure.http import binding
from graph.service import graph_common
from knowledge_base.service import kbase_service as kbase_store
from infrastructure.logging.logutil import log

DIRECTIONS = ('in', 'out', 'both')

# ``GraphReviewDTO`` 的 @Min/@Max（DTO 层先拦，但服务层又判了一遍）
DEPTH_RANGE = (1, 10)
LIMIT_RANGE = (1, 10000)
DEFAULT_DEPTH = 10
DEFAULT_LIMIT = 1000


def review(payload: dict) -> dict:
    """``POST /graph/review``。"""
    # 绑定先于校验 —— 与 query 同一套绑定语义，见 infrastructure/http/binding.py 的模块注释
    payload = binding.bind(payload, binding.REVIEW_FIELDS)

    kb_id = payload.get('kbId')
    direction = payload.get('direction')
    depth = payload.get('depth')
    limit = payload.get('limit')

    if kb_id is None or not str(kb_id).strip():
        raise _invalid('RetCode.graph.review.kbid.empty')
    # direction 为 None 是允许的（落到 both）
    if direction is not None and direction not in DIRECTIONS:
        raise _invalid('RetCode.graph.review.direction.invalid')
    if depth is not None and not (DEPTH_RANGE[0] <= depth <= DEPTH_RANGE[1]):
        raise _invalid('RetCode.graph.review.depth.invalid')
    if limit is not None and not (LIMIT_RANGE[0] <= limit <= LIMIT_RANGE[1]):
        raise _invalid('RetCode.graph.review.limit.invalid')

    kbase = kbase_store.get_kbase_row(str(kb_id))
    if kbase is None:
        # 这一条是 **0005**，与上面四条不同；
        # 而且它**跟随请求语言**（zh-CN 出中文、无头/en-US 出英文），
        # 上面那四条则恒为中文 —— 见 messages.py 里那一段说明。
        raise KbApiError('RetCode.kbase.not.exist')

    schema_obj = graph_common.schema_obj(kbase)
    if not schema_obj:
        # schema 没定义时**直接回空**，根本不碰图库
        return _empty()

    return _query_graph_data(str(kb_id), payload, graph_common.SchemaIndex(schema_obj))


def _invalid(key: str) -> KbApiError:
    """**0004**（参数非法）。"""
    return KbApiError(key, code='0004')


def _empty() -> dict:
    return {'entities': [], 'edges': [], 'entity_num': 0, 'edge_num': 0}


def _query_graph_data(kb_id: str, payload: dict, schema: graph_common.SchemaIndex) -> dict:
    """**整段吞异常** —— 见模块注释第 3 条。"""
    try:
        dbname = graph_pg.graph_db_name(kb_id)
        client = graph_pg.new_client(dbname)
        if not graph_pg.is_database_exists(client):
            return _empty()

        depth = payload.get('depth') if payload.get('depth') is not None else DEFAULT_DEPTH
        limit = payload.get('limit') if payload.get('limit') is not None else DEFAULT_LIMIT
        direction = payload.get('direction') or 'both'
        filters = payload.get('filters') or []

        return _graph_data(client, payload, schema, depth, limit, direction, filters)
    except Exception:
        log.exception('graph review failed for kbId=%s, returning empty result', kb_id)
        return _empty()


def _graph_data(client, payload: dict, schema: graph_common.SchemaIndex,
                depth: int, limit: int, direction: str, filters: list) -> dict:
    seeds = graph_pg.start_entity_ids(client.dbname, filters)
    edge_types: list[str] = []
    edge_properties: dict = {}
    vertex_groups: list[dict] = []
    for item in filters:
        for name in item.get('path_edge_type') or []:
            if name not in edge_types:
                edge_types.append(name)
        edge_properties.update(item.get('path_edge_properties') or {})
        if item.get('path_entity_type') or item.get('path_entity_properties'):
            vertex_groups.append({'entity_type': item.get('path_entity_type'),
                                   'properties': item.get('path_entity_properties') or {}})
    edge_rows, vertex_rows = graph_pg.subgraph(
        client.dbname, seeds or None, depth, direction, edge_types,
        edge_properties, vertex_groups, limit, 0, None)
    for edge in edge_rows:
        edge.pop('out_entity_id', None)
        edge.pop('in_entity_id', None)
    entities = [item for item in (graph_common.to_entity(row, schema) for row in vertex_rows)
                if item is not None]
    edges = [graph_common.to_edge(row, schema) for row in edge_rows
             if row.get('@class') is not None]
    return {'entities': entities, 'edges': edges,
            'entity_num': len(entities), 'edge_num': len(edges)}
