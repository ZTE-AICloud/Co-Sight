"""``POST /graph/query``（图谱查询，四种 ``query_type``）。

这是本接口层里最大的一块，因此单独成文件，
**没有**并进 ``graph_review_service``（两者除了都叫「图谱读接口」之外几乎不共享逻辑）。

## 为什么不直接复用底层图谱引擎的原生输出

实测同一个 ``query_type=entity`` 请求，两种输出的**结构就不一样**：

* 对外契约：``entities`` 是按 schema 过滤过的扁平结构，并且**额外查一次边**
  一起返回，还有 ``entity_num``/``edge_num``/``paths``/``total`` 等字段；
* 原生输出：``entities`` 是**原始图行**（``@rid``/``@class``/``out_WorksAt``…），
  而且**根本没有 ``edges`` 这个键**。

所以查询构造与响应装配按对外契约实现。**唯一复用的是路径提取** ——
``query_type=path`` 返回的 ``{nodes, edges}`` 数组字节级一致，
所以路径那一步直接调 :func:`extract_paths`。有测量支撑才复用，
其余宁可重写也不「适配」—— 适配出来的东西会在字段级悄悄跑偏。

## 两条语言规则（与 review 同构但落点不同）

| 校验 | 来源 | 码 | 语言 |
|---|---|---|---|
| ``kb_id`` 空 / ``query_type`` 空 / ``depth`` / ``limit`` / ``offset`` 越界 | **DTO 注解内联字面量** | **0004** | **恒中文** |
| ``query_type`` 非法 / 知识库不存在 / 构建中 / 构建失败 | 服务层 i18n 键 | 0005 | 跟随请求 |

DTO 那五条在 ``messages.py`` 里 zh 与 en **写成同一句中文** —— 不是偷懒，
是因为它们真的不查 i18n 表（en-US 实测仍回中文）。
注意 ``RetCode.graph.query.depth.invalid`` 的文案是「深度必须在1-100之间」而不是
i18n 表里那个多一个「查询」的写法：**DTO 先跑**，表里那份不可达。

## 一处**已知非确定性**

同一次请求里若**同时**违反多条 DTO 约束，服务端返回哪一条是**随机的**：
同一个 ``{}`` 连打 12 次，6 次回「查询类型不能为空」、6 次回「知识库ID不能为空」；
``kb_id=""`` + ``depth=0`` 连打 12 次给出 9/3 分裂（三错并发时还有 7/3/2 的三分裂）。
原因是全局异常处理器在遍历一个 HashMap 式的错误集合。既然顺序本身不确定，
这里**按 DTO 字段声明顺序**取第一条（kbId → queryType → depth → limit → offset）——
最可解释的选择。因此校验只比**单点违规**用例，多违规的差异不计入不一致。
"""

from __future__ import annotations

import itertools
from typing import Any, Optional

from graph.constants import GRAPH_TABLE_PREFIX
from graph.repository import graph_pg
from shared.errors.api import CODE_VALIDATION_ERROR, KbApiError
from infrastructure.http import binding
from graph.service import graph_common
from knowledge_base.service import kbase_service as kbase_store
from graph.service.graph_query_service import extract_paths
from infrastructure.logging.logutil import log

QUERY_TYPES = ('entity', 'edge', 'path', 'sub_graph')

# ``GraphQueryDTO`` 的字段默认值（缺省时生效；显式传 null 也会回落到这里）
DEFAULT_DEPTH = 10
DEFAULT_DIRECTION = 'both'
DEFAULT_LIMIT = 100
DEFAULT_OFFSET = 0

# 路径提取的调用参数（写死 10000）
MAX_PATHS_PER_START = 10000

# ``KbaseStatusEnum``：构建中 1-4，构建失败 101-104
BUILDING_STATUSES = ('1', '2', '3', '4')
BUILD_FAILED_STATUSES = ('101', '102', '103', '104')

_ALL_VERTICES = '(SELECT FROM V)'


def query(payload: dict) -> dict:
    """``POST /graph/query``。"""
    # 绑定先于校验 —— 请求体先读成对象，再做业务校验
    payload = binding.bind(payload, binding.QUERY_FIELDS)
    _validate(payload)

    kb_id = payload['kb_id']
    try:
        # ``String.replace`` 是**全局替换**，不是只去前缀
        kbase = kbase_store.get_kbase_row(str(kb_id).replace(GRAPH_TABLE_PREFIX, ''))
        if kbase is None:
            raise KbApiError('RetCode.kbase.not.exist')

        _check_kbase_build_status(kbase)

        schema_obj = graph_common.schema_obj(kbase)
        if not schema_obj:
            # schema 没定义：**直接回空**，根本不碰图库
            return _empty_response(payload)

        schema = graph_common.SchemaIndex(schema_obj)

        dbname = graph_pg.graph_db_name_for_query(str(kb_id))
        client = graph_pg.new_client(dbname)
        if not graph_pg.is_database_exists(client):
            raise KbApiError('RetCode.kbase.not.exist')

        response = _execute(client, payload, schema)
    except KbApiError:
        # 业务异常原样上抛
        raise
    except Exception:
        log.exception('graph query failed for kb_id=%s', kb_id)
        raise KbApiError('RetCode.graph.query.database.operation.failed')

    _ensure_fields_not_null(response)
    response['entity_num'] = len(response['entities'])
    response['edge_num'] = len(response['edges'])
    return response


# ----------------------------------------------------------------------
# 校验
# ----------------------------------------------------------------------


def _validate(payload: dict) -> None:
    """按 **DTO 字段声明顺序**依次判，命中即抛（理由见模块注释的非确定性一节）。"""
    if _blank(payload.get('kb_id')):
        raise _dto_error('RetCode.graph.query.kbid.empty')
    if _blank(payload.get('query_type')):
        raise _dto_error('RetCode.graph.query.type.empty')

    depth = payload.get('depth')
    if depth is not None and not 1 <= depth <= 100:
        raise _dto_error('RetCode.graph.query.depth.invalid')

    limit = payload.get('limit')
    if limit is not None and not 1 <= limit <= 1000:
        raise _dto_error('RetCode.graph.query.limit.invalid')

    offset = payload.get('offset')
    if offset is not None and offset < 0:
        raise _dto_error('RetCode.graph.query.offset.invalid')

    # 这一条 DTO 上没有对应约束，落到服务层 —— 0005、且跟随请求语言
    if payload['query_type'] not in QUERY_TYPES:
        raise KbApiError('RetCode.graph.query.type.invalid')


def _dto_error(key: str) -> KbApiError:
    """DTO 注解违规：**0004**、文案恒中文（见 messages.py 那一段说明）。"""
    return KbApiError(key, code=CODE_VALIDATION_ERROR)


def _blank(value: Any) -> bool:
    return value is None or not str(value).strip()


def _check_kbase_build_status(kbase: dict) -> None:
    """构建中/构建失败时给明确提示，避免误报「知识库不存在」。

    这一条**不查图库**：抽图期间 ``graph_<kbId>`` 还没建出来，若直接跑存在性
    校验就会把「正在建」说成「不存在」。两条都是 **0005**。
    """
    status = kbase.get('status')
    if status is None:
        return
    text = str(status)
    if text in BUILDING_STATUSES:
        raise KbApiError('RetCode.graph.query.building')
    if text in BUILD_FAILED_STATUSES:
        raise KbApiError('RetCode.graph.query.build.failed')


# ----------------------------------------------------------------------
# 分派
# ----------------------------------------------------------------------


def _execute(client, payload: dict, schema: graph_common.SchemaIndex) -> dict:
    query_type = payload['query_type']
    if query_type == 'entity':
        return _query_entities(client, payload, schema)
    if query_type == 'edge':
        return _query_edges(client, payload, schema)
    if query_type == 'path':
        return _query_paths(client, payload, schema)
    return _query_subgraph(client, payload, schema, include_paths=False)


def _limit(payload: dict) -> int:
    value = payload.get('limit')
    return DEFAULT_LIMIT if value is None else int(value)


def _cursor(payload: dict) -> Optional[str]:
    value = payload.get('cursor')
    return None if _blank(value) else str(value).strip()


def _ensure_fields_not_null(response: dict) -> None:
    for field in ('entities', 'edges', 'paths'):
        if response.get(field) is None:
            response[field] = []


def _blank_response() -> dict:
    """空响应骨架。**键序照字段声明序**（按声明序序列化）。"""
    return {'entities': [], 'edges': [], 'paths': None,
            'entity_num': 0, 'edge_num': 0, 'total': 0, 'has_more': False,
            'offset': None, 'limit': None, 'next_cursor': None}


def _empty_response(payload: dict) -> dict:
    """空响应。

    ``paths`` 在这里没被赋值 —— 但调用方紧接着会跑
    ``ensureResponseFieldsNotNull``，所以**出口处它一定是 ``[]``**，不会是 null。
    """
    response = _blank_response()
    _apply_pagination(response, payload, [])
    return response


def _apply_pagination(response: dict, payload: dict, raw_data: list) -> None:
    """``applyPaginationToResponse``。

    ``has_more`` 的判据是 ``len(raw_data) >= limit``（**取等号**），
    不是「是否多查了一条」—— 刚好用满一页就会置 true。
    """
    limit = _limit(payload)
    has_more = len(raw_data) >= limit
    response['has_more'] = has_more

    if _cursor(payload) is not None:
        # ``applyCursorPagination``：只有 hasMore 时才给 next_cursor
        if has_more and raw_data and raw_data[-1].get('@rid') is not None:
            response['next_cursor'] = str(raw_data[-1]['@rid'])
        return

    offset = payload.get('offset')
    response['offset'] = DEFAULT_OFFSET if offset is None else offset
    response['limit'] = limit


# ----------------------------------------------------------------------
# entity / edge 查询
# ----------------------------------------------------------------------


def _filter_items(payload: dict, type_key: str) -> list[dict]:
    items = []
    for item in payload.get('filters') or []:
        items.append({type_key: item.get(type_key),
                      'properties': item.get('properties') or {}})
    return items


def _query_entities(client, payload: dict, schema: graph_common.SchemaIndex) -> dict:
    groups = _filter_items(payload, 'entity_type')
    rows = graph_pg.query_vertices(
        client.dbname, groups, _limit(payload),
        DEFAULT_OFFSET if payload.get('offset') is None else payload.get('offset'),
        _cursor(payload),
        # 详情页「搜索实体名称、ID 或描述」框；与 filters 是 AND 关系
        payload.get('keyword'))
    entities = _convert_entities(rows, schema)
    entity_ids = [str(row['entity_id']) for row in rows if row.get('entity_id')]
    edges = _convert_edges(graph_pg.edges_between_entities(client.dbname, entity_ids), schema)

    response = _blank_response()
    response['entities'] = entities
    response['edges'] = edges
    response['paths'] = []
    response['total'] = len(entities)
    _apply_pagination(response, payload, rows)
    return response


def _query_edges(client, payload: dict, schema: graph_common.SchemaIndex) -> dict:
    groups = _filter_items(payload, 'edge_type')
    rows = graph_pg.query_edges(
        client.dbname, groups, _limit(payload),
        DEFAULT_OFFSET if payload.get('offset') is None else payload.get('offset'),
        _cursor(payload))
    edges = _convert_edges(rows, schema)
    entity_ids = sorted({str(row[key]) for row in rows
                         for key in ('source_id', 'target_id') if row.get(key)})
    entities = _convert_entities(
        graph_pg.vertices_by_entity_ids(client.dbname, entity_ids), schema)

    response = _blank_response()
    response['entities'] = entities
    response['edges'] = edges
    response['paths'] = []
    response['total'] = len(edges)
    _apply_pagination(response, payload, rows)
    return response


def _query_subgraph(client, payload: dict, schema: graph_common.SchemaIndex,
                    include_paths: bool) -> dict:
    filters = payload.get('filters') or []
    depth = payload.get('depth')
    depth = DEFAULT_DEPTH if depth is None else depth
    direction = payload.get('direction')
    direction = DEFAULT_DIRECTION if direction is None else direction

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
            vertex_groups.append({
                'entity_type': item.get('path_entity_type'),
                'properties': item.get('path_entity_properties') or {},
            })

    offset = payload.get('offset')
    offset = DEFAULT_OFFSET if offset is None else offset
    edge_rows, vertex_rows = graph_pg.subgraph(
        client.dbname, seeds, depth, direction, edge_types, edge_properties,
        vertex_groups, _limit(payload), offset, _cursor(payload))
    if not edge_rows:
        return _empty_subgraph_response(payload, include_paths)

    for edge in edge_rows:
        edge.pop('out_entity_id', None)
        edge.pop('in_entity_id', None)

    response = _blank_response()
    response['entities'] = _convert_entities(vertex_rows, schema)
    response['edges'] = _convert_edges(edge_rows, schema)
    response['paths'] = []
    response['total'] = len(response['edges'])
    _apply_pagination(response, payload, edge_rows)
    if include_paths:
        response['paths'] = _extract_paths_for_subgraph(payload, vertex_rows, edge_rows)
    return response


def _convert_entities(rows: list, schema: graph_common.SchemaIndex) -> list:
    """``convertEntitiesToFlat``：缺 ``@class`` 的行**静默丢弃**。"""
    return [item for item in (graph_common.to_entity(row, schema) for row in rows)
            if item is not None]


def _convert_edges(rows: list, schema: graph_common.SchemaIndex) -> list:
    """``convertEdgesToFlat``：同样丢弃缺 ``@class`` 的行。"""
    return [graph_common.to_edge(row, schema) for row in rows if row.get('@class') is not None]


def _empty_subgraph_response(payload: dict, include_paths: bool) -> dict:
    """``createEmptySubgraphResponse``。"""
    response = _blank_response()
    if include_paths:
        response['paths'] = []
    _apply_pagination(response, payload, [])
    return response


def _query_paths(client, payload: dict, schema: graph_common.SchemaIndex) -> dict:
    """``queryPaths``：跑一遍子图、只留路径，``entities``/``edges`` 清空。

    路径提取复用 :func:`extract_paths`（输出字节级一致）。
    """
    subgraph = _query_subgraph(client, payload, schema, include_paths=True)

    response = _blank_response()
    response['entities'] = []
    response['edges'] = []
    response['paths'] = subgraph.get('paths') or []
    response['total'] = len(response['paths'])
    response['has_more'] = subgraph['has_more']
    response['offset'] = subgraph['offset']
    response['limit'] = subgraph['limit']
    response['next_cursor'] = subgraph['next_cursor']
    return response


def _extract_paths_for_subgraph(payload: dict, entity_rows: list, edge_rows: list) -> list:
    depth = payload.get('depth')
    depth = DEFAULT_DEPTH if depth is None else depth
    return extract_paths(entity_rows, edge_rows, _start_conditions_for_paths(payload),
                         depth, MAX_PATHS_PER_START)


def _start_conditions_for_paths(payload: dict) -> Any:
    """展开成「起点条件字典的列表」；一个都没有时用**入度为 0** 的特殊条件。"""
    all_conditions: list[dict] = []

    for item in payload.get('filters') or []:
        base = {}
        rid = item.get('start_entity_rid')
        if not _blank(rid):
            base['@rid'] = rid

        # 没有类型限制时塞一个 ``null`` 占位，保证「每个 filter 至少产出一组」
        types = item.get('start_entity_type') or [None]
        properties = item.get('start_entity_properties')
        combinations = _expand_property_combinations(properties) if properties else [{}]

        for entity_type in types:
            for combination in combinations:
                condition = dict(base)
                if entity_type is not None:
                    condition['@class'] = entity_type
                condition.update(combination)
                if condition:
                    all_conditions.append(condition)

    if not all_conditions:
        return {'_use_in_degree_zero': True}
    return all_conditions


def _expand_property_combinations(properties: dict) -> list[dict]:
    """把列表值展开成**笛卡尔积**；``{op,...}`` 形式的条件原样保留、不参与展开。"""
    keys: list[str] = []
    values: list[list] = []
    operator_conditions: dict = {}

    for key, value in properties.items():
        if isinstance(value, dict) and 'op' in value:
            operator_conditions[key] = value
            continue
        keys.append(key)
        values.append(list(value) if isinstance(value, (list, tuple)) else [value])

    if not keys:
        return [dict(operator_conditions)] if operator_conditions else [{}]

    # ``itertools.product`` 的进位顺序是「最后一个下标先自增」
    return [{**operator_conditions, **dict(zip(keys, combo))}
            for combo in itertools.product(*values)]


# ----------------------------------------------------------------------
# SQL 字面量格式化（``backtick`` / ``formatSqlValue`` / ``escapeSqlValue``）
#
# 这一组与 graph_common 里那份**故意不复用**：query 的 ``formatSqlValue(null)`` 是
# ``''``（经 escapeSqlValue 落成空串），而 graph_common.format_sql_value(None) 会得到
# ``'None'``；graph_common.simple_property_condition 还会把 null 变成 ``IS NULL``。
# 三条都与 query 的实际行为不符。
# ----------------------------------------------------------------------
