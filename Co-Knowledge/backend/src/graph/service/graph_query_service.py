"""
图查询服务
"""
import os
import re
import threading
import time
from typing import Dict, Any, List, Optional, Tuple

from graph.models.graph_query_dto import GraphQueryDto
from graph.models.graph_retrieve_dto import GraphRetrieveDto
from graph.service.entity_mention import build_mention_trie, find_mentions
from infrastructure.http.request_headers import EMRequestHeaders
from shared.errors.exception import EMException
from infrastructure.db.connection_info import get_db_conn_info
from model import llm_gateway as llmgateway_service
from infrastructure.logging.logutil import log
from infrastructure.db.pool import _db_pool
from infrastructure.db.pg import PgDatabase

#: 词面实体提及缓存：base -> (built_at, trie)。图谱写入后最多陈旧 5 分钟。
_MENTION_CACHE: dict[str, tuple[float, dict]] = {}
_MENTION_CACHE_LOCK = threading.Lock()
_MENTION_CACHE_TTL = 300.0
_MENTION_CACHE_MAX_BASES = 32
_MENTION_MAX_MENTIONS = 20


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, '') or default))
    except (TypeError, ValueError):
        return default


_MENTION_MAX_ENTITIES = _env_int('GRAPH_LEXICAL_SEED_MAX_ENTITIES', 100000)

#: Qwen3-Embedding 的查询侧指令。MetaQA 上 entity+edge 种子 topic 命中：
#: 1/2/3-hop 69/56/52% → 77/76/63%。置空可关闭。
_QUERY_INSTRUCTION = os.environ.get(
    'GRAPH_QUERY_INSTRUCTION',
    'Instruct: Retrieve the entity that the question is about\nQuery: ')

#: 深图默认边预算：1-hop 1000 足够，2/3-hop 需要更大子图才能覆盖多答案。
#: 调用方显式传非默认 limit 时尊重调用方（默认值 1000 视为「未指定」）。
_DEPTH_LIMIT_DEFAULTS = {
    1: min(5000, _env_int('GRAPH_RETRIEVE_DEPTH1_LIMIT', 1000)),
    2: min(5000, _env_int('GRAPH_RETRIEVE_DEPTH2_LIMIT', 3000)),
    3: min(5000, _env_int('GRAPH_RETRIEVE_DEPTH3_LIMIT', 5000)),
}
#: 词面命中后保留的向量种子数。词面是高置信实体链接，留少量向量种子做兜底，
#: 避免 ~20 个向量种子把子图边预算摊薄到 topic 分支之外。
try:
    _LEXICAL_VECTOR_BACKFILL = max(0, int(os.environ.get(
        'GRAPH_LEXICAL_SEED_VECTOR_BACKFILL', '5') or 5))
except (TypeError, ValueError):
    _LEXICAL_VECTOR_BACKFILL = 5


def extract_paths(entities, edges, start_conditions, max_depth=10, max_paths_per_start=10000):
    """
    从图中提取所有路径 (深度优化版)

    Args:
        entities: 实体列表，每个实体是字典，必须包含 '@rid' 字段
        edges: 边列表，每个边是字典，必须包含 '@rid', 'out', 'in' 字段
        start_conditions: 起点条件，可以是:
            - 单个字典: {"field": "value"}
            - 字典列表: [{"field1":"v1"}, {"field2":"v2"}]
            - 特殊条件: {"_use_in_degree_zero": true} (入度为0的节点)
        max_depth: 最大搜索深度 (默认25，防止组合爆炸)
        max_paths_per_start: 每个起点最大路径数 (默认10万，内存保护)

    Returns:
        list[dict]: 路径列表，每个路径格式:
            {
                "nodes": ["#1:0", "#1:1", ...],  # 节点RID列表
                "edges": ["#2:0", "#2:1", ...]   # 边RID列表 (长度=节点数-1)
            }
    """
    from collections import defaultdict

    # ========== 1. 构建索引 ==========
    # 确保RID格式一致（转换为字符串）
    rid_to_entity = {str(ent.get('@rid')): ent for ent in entities if ent.get('@rid')}
    rid_to_edge = {str(edge.get('@rid')): edge for edge in edges if edge.get('@rid')}

    # 为节点分配连续ID (加速位掩码操作)
    # 确保使用字符串格式的RID
    node_ids = {str(rid): idx for idx, rid in enumerate(rid_to_entity.keys())}

    # ========== 2. 构建图 ==========
    graph = defaultdict(list)  # out_rid -> [(in_rid, edge_rid), ...] 正向图
    reverse_graph = defaultdict(list)  # in_rid -> [(out_rid, edge_rid), ...] 反向图
    in_degree = defaultdict(int)  # 节点入度计数

    # 优化：预先转换RID，避免重复转换
    for edge in edges:
        out_rid = edge.get('out')
        in_rid = edge.get('in')
        edge_rid = edge.get('@rid')

        # 转换为字符串格式，确保RID格式一致
        if out_rid:
            out_rid = str(out_rid)
        if in_rid:
            in_rid = str(in_rid)
        if edge_rid:
            edge_rid = str(edge_rid)

        # 只添加有效连接
        if (out_rid and in_rid and edge_rid and
                out_rid in rid_to_entity and
                in_rid in rid_to_entity and
                edge_rid in rid_to_edge):
            # 使用元组存储，节省内存（元组比列表更紧凑）
            graph[out_rid].append((in_rid, edge_rid))
            reverse_graph[in_rid].append((out_rid, edge_rid))
            in_degree[in_rid] += 1

    # 优化：记录哪些节点有入边，用于判断是否需要反向遍历
    nodes_with_in_edges = set(reverse_graph.keys())

    # ========== 3. 起点匹配逻辑 ==========
    def matches(entity, conditions):
        """检查实体是否匹配条件"""
        # 特殊条件：入度为0
        if '_use_in_degree_zero' in conditions:
            entity_rid = str(entity.get('@rid', ''))
            return in_degree.get(entity_rid, 0) == 0

        # 普通字段匹配
        for key, value in conditions.items():
            entity_value = entity.get(key)
            
            # 支持操作符格式：如果是字典且包含op字段，使用操作符匹配
            if isinstance(value, dict) and "op" in value:
                op = value.get("op")
                op_value = value.get("value")
                
                if op == "eq":
                    if entity_value != op_value:
                        return False
                elif op == "ne":
                    if entity_value == op_value:
                        return False
                elif op == "gt":
                    if not isinstance(entity_value, (int, float)) or entity_value <= op_value:
                        return False
                elif op == "gte":
                    if not isinstance(entity_value, (int, float)) or entity_value < op_value:
                        return False
                elif op == "lt":
                    if not isinstance(entity_value, (int, float)) or entity_value >= op_value:
                        return False
                elif op == "lte":
                    if not isinstance(entity_value, (int, float)) or entity_value > op_value:
                        return False
                elif op == "like":
                    if not isinstance(entity_value, str) or not isinstance(op_value, str):
                        return False
                    # 简单的like匹配：将%转换为.*，进行正则匹配
                    # 转义正则表达式特殊字符，但保留%和_的通配符语义
                    pattern = op_value.replace('%', '.*').replace('_', '.')
                    # 转义其他正则表达式特殊字符（除了已经转换的.*和.）
                    escaped_parts = []
                    i = 0
                    while i < len(pattern):
                        if i < len(pattern) - 1 and pattern[i:i+2] == '.*':
                            escaped_parts.append('.*')
                            i += 2
                        elif pattern[i] == '.':
                            escaped_parts.append('.')
                            i += 1
                        else:
                            # 转义其他特殊字符
                            char = pattern[i]
                            if char in '^$[]{}()*+?|\\':
                                escaped_parts.append('\\' + char)
                            else:
                                escaped_parts.append(char)
                            i += 1
                    pattern = ''.join(escaped_parts)
                    try:
                        if not re.search(pattern, entity_value, re.IGNORECASE):
                            return False
                    except re.error:
                        # 如果正则表达式无效，回退到简单的字符串包含匹配
                        if '%' in op_value:
                            # 如果有%，进行简单的通配符匹配
                            pattern_parts = [p for p in op_value.split('%') if p]
                            if not all(part.lower() in entity_value.lower() for part in pattern_parts):
                                return False
                        else:
                            if op_value.lower() not in entity_value.lower():
                                return False
                elif op == "in":
                    if not isinstance(op_value, list):
                        return False
                    if entity_value not in op_value:
                        return False
                elif op == "between":
                    if not isinstance(op_value, list) or len(op_value) != 2:
                        return False
                    min_val, max_val = op_value[0], op_value[1]
                    if not isinstance(entity_value, (int, float)) or not (min_val <= entity_value <= max_val):
                        return False
                elif op == "contains":
                    if not isinstance(op_value, (list, dict)):
                        # 简单contains：检查entity_value（列表）是否包含op_value
                        if not isinstance(entity_value, list):
                            return False
                        if op_value not in entity_value:
                            return False
                    # 嵌套contains条件暂不支持在内存中匹配，返回False
                    else:
                        return False
                elif op == "contains_all":
                    if not isinstance(op_value, list) or not isinstance(entity_value, list):
                        return False
                    if not all(v in entity_value for v in op_value):
                        return False
                elif op == "contains_any":
                    if not isinstance(op_value, list) or not isinstance(entity_value, list):
                        return False
                    if not any(v in entity_value for v in op_value):
                        return False
                else:
                    # 不支持的操作符，返回False
                    return False
            # 支持列表值匹配：如果条件是列表，检查实体值是否在列表中
            elif isinstance(value, list):
                if entity_value not in value:
                    return False
            else:
                if entity_value != value:
                    return False
        return True

    # 获取所有起点
    # 优化：预先检查起点条件类型，避免重复检查
    is_list_conditions = isinstance(start_conditions, list)
    is_in_degree_zero = False
    has_explicit_start = False

    if is_list_conditions:
        # 多条件：任意条件匹配即为起点
        # 优化：先检查是否有特殊条件，避免不必要的遍历
        for cond in start_conditions:
            if '_use_in_degree_zero' in cond:
                is_in_degree_zero = True
                break
            if '@rid' in cond:
                has_explicit_start = True

        if is_in_degree_zero:
            # 直接使用_use_in_degree_zero逻辑，避免遍历所有实体
            matched_rids = [
                str(rid) for rid, ent in rid_to_entity.items()
                if in_degree.get(str(rid), 0) == 0
            ]
        else:
            # 多条件匹配：使用集合去重，提高效率
            matched_rids = list({
                str(rid) for cond in start_conditions
                for rid, ent in rid_to_entity.items()
                if matches(ent, cond)
            })
    else:
        # 单条件
        if '_use_in_degree_zero' in start_conditions:
            is_in_degree_zero = True
            matched_rids = [
                str(rid) for rid, ent in rid_to_entity.items()
                if in_degree.get(str(rid), 0) == 0
            ]
        else:
            has_explicit_start = '@rid' in start_conditions
            matched_rids = [
                str(rid) for rid, ent in rid_to_entity.items()
                if matches(ent, start_conditions)
            ]

    # 优化：如果匹配到的节点都没有出边（都是终点），且不是明确指定的起点，则回退到入度为0的节点
    if matched_rids and not is_in_degree_zero:
        # 检查是否有匹配的节点有出边（使用集合交集，O(min(len(matched_rids), len(graph)))）
        matched_set = set(matched_rids)
        graph_keys = set(graph.keys())
        has_outgoing = bool(matched_set & graph_keys)

        # 如果所有匹配的节点都没有出边，且没有明确指定的起点，回退到入度为0的节点
        if not has_outgoing and not has_explicit_start:
            # 回退到入度为0的节点（只遍历一次）
            fallback_rids = [
                str(rid) for rid in rid_to_entity.keys()
                if in_degree.get(str(rid), 0) == 0
            ]
            # 如果回退找到了节点，使用回退结果；否则使用原始匹配结果
            start_rids = fallback_rids if fallback_rids else matched_rids
        else:
            # 优先选择有出边的节点（使用集合操作优化）
            preferred_starts = [
                rid for rid in matched_rids
                if in_degree.get(rid, 0) == 0 or rid in graph_keys
            ]
            # 如果优先节点存在，使用优先节点；否则使用所有匹配的节点
            start_rids = preferred_starts if preferred_starts else matched_rids
    else:
        start_rids = matched_rids

    # ========== 4. 核心DFS (迭代式+位掩码优化) ==========
    def dfs_for_start(start_rid, use_reverse=False):
        """为单个起点生成所有路径 (生成器)
        
        Args:
            start_rid: 起点RID
            use_reverse: 是否使用反向图（用于查找到达起点的路径）
        """
        if start_rid not in node_ids:
            return

        # 根据方向选择使用正向图还是反向图
        search_graph = reverse_graph if use_reverse else graph

        # 栈元素: (current_node, path_nodes, path_edges, visited_mask, edge_count)
        # 使用列表模拟栈，避免递归
        stack = [
            (
                start_rid,  # 当前节点
                [start_rid],  # 当前路径节点
                [],  # 当前路径边
                1 << node_ids[start_rid],  # 位掩码 (标记已访问节点)
                0  # 已用边计数 (用于索引)
            )
        ]

        paths_found = 0

        while stack and paths_found < max_paths_per_start:
            node, nodes_path, edges_path, visited_mask, edge_count = stack.pop()

            # 获取所有有效邻居
            neighbors = []
            for neighbor_rid, edge_rid in search_graph.get(node, []):
                # 跳过无效节点
                if neighbor_rid not in node_ids:
                    continue

                n_id = node_ids[neighbor_rid]
                # 1. 检查环 (O(1) 位掩码检测)
                if (visited_mask >> n_id) & 1:
                    continue

                # 2. 检查深度
                if len(nodes_path) >= max_depth:
                    continue

                neighbors.append((neighbor_rid, edge_rid))

            # 没有有效邻居 = 叶子节点
            if not neighbors:
                paths_found += 1
                # 反向路径需要反转节点和边的顺序
                # 使用切片反转，比list(reversed())更高效
                if use_reverse:
                    yield {
                        "nodes": nodes_path[::-1],  # 切片反转，避免创建新列表对象
                        "edges": edges_path[::-1]
                    }
                else:
                    yield {
                        "nodes": nodes_path,
                        "edges": edges_path
                    }
                continue

            # 有邻居：继续探索 (倒序入栈保持与递归相同的顺序)
            for neighbor_rid, edge_rid in reversed(neighbors):
                n_id = node_ids[neighbor_rid]

                # 创建新路径 (列表连接操作，Python会优化)
                new_nodes = nodes_path + [neighbor_rid]
                new_edges = edges_path + [edge_rid]
                new_mask = visited_mask | (1 << n_id)

                stack.append((
                    neighbor_rid,
                    new_nodes,
                    new_edges,
                    new_mask,
                    edge_count + 1
                ))

    # ========== 5. 收集所有路径 ==========
    all_paths = []
    total_paths = 0
    MAX_TOTAL_PATHS = 500000  # 50万条总路径上限

    for start_rid in start_rids:
        if start_rid not in rid_to_entity:
            continue

        # 查找正向路径（从起点出发，out方向）
        for path in dfs_for_start(start_rid, use_reverse=False):
            all_paths.append(path)
            total_paths += 1

            # 全局限制 (防止内存爆炸)
            if total_paths > MAX_TOTAL_PATHS:
                return all_paths

        # 查找反向路径（到达起点，in方向）
        # 优化：只有当起点有入边时才进行反向遍历
        if start_rid in nodes_with_in_edges:
            for path in dfs_for_start(start_rid, use_reverse=True):
                all_paths.append(path)
                total_paths += 1

                # 全局限制 (防止内存爆炸)
                if total_paths > MAX_TOTAL_PATHS:
                    return all_paths

    return all_paths


#: 图谱库基名的白名单。历史 kbase_id 有 16 位与 32 位 hex 两种，另外还有
#: ``graph_<uuid>`` / ``graph_<kbaseId>`` 形态；这里只允许字母、数字、下划线，
#: 足以覆盖现有数据，同时挡掉引号、分号、空白等 SQL 元字符。
_GRAPH_BASE_RE = re.compile(r'^graph_[A-Za-z0-9_]{1,64}$')

#: chunk 种子检索的固定 top_k（与注释「默认 top_50」一致；实体/边仍用 seed_k）。
CHUNK_SEED_K = 50


def _validate_graph_base(base: str) -> str:
    """校验图谱库基名；非法值直接拒绝，不拼 SQL、不连图存储。"""
    if not isinstance(base, str) or not _GRAPH_BASE_RE.match(base):
        raise ValueError(f'illegal graph base: {base!r}')
    return base


def _build_retrieve_sql(base, key_type, query_embedding, seek_k, score, labels=None):
    """构建图谱种子检索 SQL（**全部参数化**）。

    返回 ``(sql, params)``。``base`` 只做白名单校验后拼表名；``key_type`` /
    ``query_embedding`` / ``score`` / ``labels`` / ``seek_k`` 全部走绑定参数，
    不再拼进 SQL 文本。调用方必须用带 params 的执行方法（extended protocol）。
    """
    _validate_graph_base(base)
    schema_table = f'kb_index.{base}_vector'

    where_conditions = [
        'key_type = %s',
        f'{schema_table}.embedding <=> %s::vector <= %s',
    ]
    # score 是余弦相似度；转成距离上限后阈值与 ORDER BY 用同一个可索引表达式。
    params: list = [key_type, query_embedding, 1.0 - score]

    if labels and len(labels) > 0:
        # ``labels && %s::text[]``：有交集就匹配；列表作为绑定参数传入。
        where_conditions.append('labels && %s::text[]')
        params.append(list(labels))

    where_clause = ' AND '.join(where_conditions)
    params.append(query_embedding)   # ORDER BY embedding <=> %s
    params.append(seek_k)            # LIMIT %s

    sql = f"""
        SELECT {schema_table}.key_id,
               {schema_table}.source_id,
               {schema_table}.target_id,
               1 - ({schema_table}.embedding <=> %s::vector) AS cosine_similarity
        FROM {schema_table}
        WHERE {where_clause}
        ORDER BY {schema_table}.embedding <=> %s::vector ASC
        LIMIT %s
        """
    # 参数顺序：SELECT 里的 embedding、WHERE 的 key_type/embedding/距离上限、
    # 可选 labels、ORDER BY 的 embedding、LIMIT
    params = [query_embedding] + params
    return sql, params


class GraphQueryService:
    """图查询服务"""

    def __init__(self):
        pg_conn_info = get_db_conn_info()
        self.pg_db = PgDatabase(
            dbname=pg_conn_info.get('database'),
            host=pg_conn_info.get('host'),
            port=pg_conn_info.get('port'),
            user=pg_conn_info.get('user'),
            password=pg_conn_info.get('password')
        )

    def check_kb_db_exists(self, dbname: str) -> bool:
        """检查图谱库是否存在（PostgreSQL 表后端）。"""
        from graph.repository import graph_pg

        return graph_pg.is_database_exists(graph_pg.new_client(dbname))

    def _query_subgraph(self, query_dto: GraphQueryDto,
                           include_paths: bool = True) -> Dict[str, Any]:
        """子图查询：BFS 遍历。"""
        from graph.repository import graph_pg

        filters = list(query_dto.filters or [])
        # 起点条件（entity_id / start_entity_type + properties / RID）与查询 API
        # 走同一个解析函数，避免两处语义漂移。
        seeds = graph_pg.start_entity_ids(query_dto.kb_id, [{
            'start_entity_type': item.start_entity_type,
            'start_entity_properties': item.start_entity_properties or {},
            'start_entity_rid': item.start_entity_rid,
        } for item in filters])
        edge_types: list[str] = []
        edge_properties: dict = {}
        vertex_groups: list[dict] = []
        for item in filters:
            for name in item.path_edge_type or []:
                if name not in edge_types:
                    edge_types.append(name)
            edge_properties.update(item.path_edge_properties or {})
            if item.path_entity_type or item.path_entity_properties:
                vertex_groups.append({
                    'entity_type': item.path_entity_type,
                    'properties': item.path_entity_properties or {},
                })

        edge_rows, vertex_rows = graph_pg.subgraph(
            query_dto.kb_id, seeds or None,
            query_dto.depth or 10, query_dto.direction or 'both',
            edge_types, edge_properties, vertex_groups,
            query_dto.limit or 100, query_dto.offset or 0,
            getattr(query_dto, 'cursor', None),
            prioritize_levels=bool(getattr(query_dto, 'prioritize_levels', False)))
        for edge in edge_rows:
            edge.pop('out_entity_id', None)
            edge.pop('in_entity_id', None)
        return self._convert_subgraph_to_response(
            {'entities': vertex_rows, 'edges': edge_rows}, query_dto, include_paths)

    def _convert_subgraph_to_response(self, subgraph: Dict, query_dto: GraphQueryDto,
                                             include_paths: bool = True) -> Dict:
        """把子图查询结果转成对外响应。"""
        # 直接获取entities和edges（已经是列表格式）
        entities = subgraph.get('entities', [])
        edges = subgraph.get('edges', [])

        # 如果entities是列表但为空，确保是空列表
        if not isinstance(entities, list):
            entities = []
        if not isinstance(edges, list):
            edges = []

        # 构建响应
        response = {
            "entities": entities,
            "edges": edges,
            "total": len(edges)  # total表示边的总数
        }

        # 添加分页信息
        limit = query_dto.limit or 100
        has_more = len(edges) >= limit

        # 如果使用游标分页，返回最后一个边的@rid作为next_cursor
        cursor = getattr(query_dto, 'cursor', None)
        if cursor:
            # 只有在has_more为True时才返回next_cursor
            if has_more and edges:
                last_edge_rid = edges[-1].get('@rid')
                if last_edge_rid:
                    response["next_cursor"] = str(last_edge_rid)
            response["has_more"] = has_more
        else:
            # Skip分页
            offset = query_dto.offset or 0
            response["has_more"] = has_more
            response["offset"] = offset
            response["limit"] = limit

        if include_paths:
            paths = []
            if entities and edges:
                # 从查询参数中构建起点条件
                start_conditions = self._build_start_conditions_for_paths(query_dto)
                paths = extract_paths(entities, edges, start_conditions)
            response["paths"] = paths

        return response

    def _build_start_conditions_for_paths(self, query_dto: GraphQueryDto) -> Dict[str, Any]:
        """构建用于路径提取的起点条件"""
        # 收集所有filter的起点条件
        all_start_conditions = []

        for filter_item in query_dto.filters:
            # 先收集基础条件（不包含属性）
            base_conditions = {}

            # 添加起点实体类型条件
            if filter_item.start_entity_type:
                # 支持多个类型，展开为多个条件
                entity_types = filter_item.start_entity_type
                if not isinstance(entity_types, list):
                    entity_types = [entity_types]
            else:
                entity_types = [None]  # 没有类型限制

            # 添加起点实体关系ID条件
            if filter_item.start_entity_rid:
                base_conditions['@rid'] = filter_item.start_entity_rid

            # 处理起点实体属性条件，展开列表值
            if filter_item.start_entity_properties:
                # 获取所有属性的笛卡尔积组合
                property_combinations = self._expand_property_combinations(filter_item.start_entity_properties)
            else:
                property_combinations = [{}]  # 没有属性限制

            # 生成所有可能的条件组合
            for entity_type in entity_types:
                for properties in property_combinations:
                    condition = base_conditions.copy()
                    if entity_type is not None:
                        condition['@class'] = entity_type
                    condition.update(properties)

                    # 如果有有效的条件，添加到列表中
                    if condition:
                        all_start_conditions.append(condition)

        # 如果没有明确的起点条件，选择入度为0的节点作为起点
        if not all_start_conditions:
            return {'_use_in_degree_zero': True}

        # 返回所有起点条件的列表，extract_paths会分别处理每个条件
        return all_start_conditions

    def _expand_property_combinations(self, properties: Dict[str, Any]) -> List[Dict[str, Any]]:
        """展开属性值的所有组合，将列表值展开为多个单值条件
        
        支持新格式的操作符条件（字典格式包含op和value字段），这些条件不会被展开
        """
        from itertools import product

        # 分离可展开的条件和操作符条件
        expandable_keys = []
        expandable_values = []
        operator_conditions = {}

        for key, value in properties.items():
            # 如果是操作符格式（字典且包含op字段），直接保留，不展开
            if isinstance(value, dict) and "op" in value:
                operator_conditions[key] = value
            else:
                expandable_keys.append(key)
                if isinstance(value, list):
                    expandable_values.append(value)
                else:
                    expandable_values.append([value])

        # 生成可展开条件的组合
        combinations = []
        if expandable_keys:
            for value_combination in product(*expandable_values):
                combination = dict(zip(expandable_keys, value_combination))
                # 添加操作符条件
                combination.update(operator_conditions)
                combinations.append(combination)
        else:
            # 只有操作符条件，直接返回
            if operator_conditions:
                combinations.append(operator_conditions)
            else:
                combinations.append({})

        return combinations

    def retrieve_graph(self, retrieve_dto: GraphRetrieveDto, request_headers: EMRequestHeaders):
        """图检索接口实现
        
        通过向量检索找到种子节点，然后按深度传播获取子图
        
        Args:
            retrieve_dto: 检索请求参数
            request_headers: 请求头
            
        Returns:
            包含每个base的检索结果和统计信息的字典
        """
        query_embedding = self._get_query_embedding(retrieve_dto, request_headers)
        language = request_headers.get_language_option()

        base_results = []
        total_entities_count = 0
        total_edges_count = 0

        for base in retrieve_dto.bases:
            base_result = self._retrieve_single_base(
                base,
                query_embedding,
                retrieve_dto,
                language
            )
            base_results.append(base_result)

            # 累计统计
            total_entities_count += base_result.get('entity_count', 0)
            total_edges_count += base_result.get('edge_count', 0)

        return self._build_retrieve_result(base_results, total_entities_count, total_edges_count, retrieve_dto)

    def _get_query_embedding(self, retrieve_dto: GraphRetrieveDto, request_headers: EMRequestHeaders) -> str:
        """获取查询的向量表示（按 Qwen3-Embedding 的查询指令包装）。"""
        started = time.perf_counter()
        query = retrieve_dto.query or ''
        if _QUERY_INSTRUCTION and not query.lstrip().startswith('Instruct:'):
            query = _QUERY_INSTRUCTION + query
        try:
            embedding = llmgateway_service.get_embedding_info(
                query,
                retrieve_dto.embedding,
                request_headers
            )
        except Exception:
            log.exception('graph query embedding failed model=%r query_len=%s',
                          retrieve_dto.embedding, len(retrieve_dto.query or ''))
            raise EMException(err_code='embedding-service-error')
        log.info('graph query embedding model=%r query_len=%s elapsed=%.3fs',
                 retrieve_dto.embedding, len(retrieve_dto.query or ''),
                 time.perf_counter() - started)
        return embedding

    def _retrieve_single_base(self, base: str, query_embedding: str,
                              retrieve_dto: GraphRetrieveDto,
                              language: str) -> Dict[str, Any]:
        """检索单个知识库的子图"""
        # 先做基名白名单：非法值不连库、不拼 SQL，响应形状与「库不存在」一致。
        try:
            _validate_graph_base(base)
        except ValueError:
            log.warning('illegal graph base rejected: %r', base)
            return self._create_empty_base_result(
                base, self._get_i18n_error_message('graph-db-not-exists', language))

        # 验证知识库
        validation_error = self._validate_base(base, language)
        if validation_error:
            return validation_error

        # 检索种子节点（实体/边），以及按chunk进行的检索（top_50）
        seed_entity_ids, seed_chunk_ids = self._retrieve_seed_ids(base, query_embedding, retrieve_dto)
        if not seed_entity_ids:
            # 若没有命中种子实体，但存在 chunk 种子，仍需返回这些 chunk
            if seed_chunk_ids:
                try:
                    chunks_map = self._query_chunks_by_ids(base, seed_chunk_ids)
                except Exception as e:
                    log.warn(f"Build chunks map (no-entity case) failed for base={base}, error={str(e)}")
                    chunks_map = {}

                result = self._create_empty_base_result(base)
                result['seed_entity_ids'] = []
                result['chunks'] = chunks_map
                result['chunk_count'] = len(chunks_map)
                return result

            log.warn(f"No seed nodes found for base={base}")
            return self._create_empty_base_result(base)

        # 检索子图
        base_result = self._retrieve_subgraph_for_base(base, seed_entity_ids, retrieve_dto)

        # 组装 chunks 字段：
        # - 从实体的 chunk_id 字段收集
        # - 合并种子检索(key_type=chunk)得到的 chunk_id 并补齐
        try:
            entity_chunk_ids = self._collect_chunk_ids_from_entities(base_result.get('entities', []))
            all_chunk_ids = list(set(entity_chunk_ids).union(set(seed_chunk_ids)))
            chunks_map = self._query_chunks_by_ids(base, all_chunk_ids)
        except Exception as e:
            log.warn(f"Build chunks map failed for base={base}, error={str(e)}")
            chunks_map = {}

        # 从实体下移除 chunk_info（不再在实体里返回）
        for ent in base_result.get('entities', []):
            if 'chunks' in ent:
                try:
                    del ent['chunks']
                except Exception:
                    pass

        # 增加 seed_entity_ids 与 chunks 字段
        base_result['seed_entity_ids'] = seed_entity_ids
        base_result['chunks'] = chunks_map
        base_result['chunk_count'] = len(chunks_map)

        return base_result

    def _validate_base(self, base: str, language: str) -> Optional[Dict[str, Any]]:
        """验证知识库是否存在，返回错误结果或None"""

        if not self.check_kb_db_exists(base):
            log.warn(f"Graph database not exists for base, basename={base}")
            error_msg = self._get_i18n_error_message('graph-db-not-exists', language)
            return self._create_empty_base_result(base, error_msg)

        return None

    def _get_i18n_error_message(self, error_code: str, language: str) -> str:
        """获取国际化的错误消息
        
        Args:
            error_code: 错误码
            language: 语言标识
            
        Returns:
            国际化的错误消息
        """
        error_messages = {
            'kb-not-exists': {
                'zh': '知识库不存在',
                'en': 'Knowledge base does not exist'
            },
            'graph-db-not-exists': {
                'zh': '图数据库不存在',
                'en': 'Graph database does not exist'
            }
        }

        if error_code in error_messages:
            return error_messages[error_code].get(language, error_messages[error_code]['en'])

        return 'Unknown error' if language == 'en' else '未知错误'

    def _retrieve_seed_ids(self, base: str, query_embedding: str,
                           retrieve_dto: GraphRetrieveDto) -> Tuple[List[str], List[str]]:
        """通过向量检索获取种子 entity_id 列表与 chunk_id 列表

        返回:
            (seed_entity_ids, seed_chunk_ids)
        """
        entity_ids: List[str] = []
        chunk_ids: List[str] = []

        # 实体与边：仍然按 seed_k 返回 entity_ids
        for key_type in ['entity', 'edge']:
            records = self._query_vector_index(base, key_type, query_embedding, retrieve_dto)
            entity_ids.extend(self._extract_entity_ids_from_records(records, key_type))

        # 词面路径：问题里原样出现的实体名直接作为种子。
        # 名字型实体（MetaQA 的 topic）向量召回不稳，这条把上限从 ~60% 抬到 ~95%。
        try:
            lexical_ids = self._lexical_seed_entity_ids(base, retrieve_dto.query)
        except Exception as error:                                  # noqa: BLE001
            log.warning('lexical seed lookup failed base=%s: %s', base, error)
            lexical_ids = []
        if lexical_ids:
            lexical_unique = list(dict.fromkeys(lexical_ids))
            lexical_set = set(lexical_unique)
            # 单个专名命中 = 高置信 topic，聚焦它；多个专名 = 描述里提到的是
            # 邻居/相关实体，保留向量兜底把真正的 topic 找回来。
            backfill = _LEXICAL_VECTOR_BACKFILL if len(lexical_unique) > 1 else 0
            extras = [eid for eid in entity_ids
                      if eid not in lexical_set][:backfill]
            entity_ids = lexical_unique + extras
            log.info('lexical seeds base=%s lexical=%s vector_backfill=%s',
                     base, len(lexical_unique), len(extras))

        # chunk：固定 top_50（不受 seed_k 影响）
        records_chunk = self._query_vector_index(
            base, 'chunk', query_embedding, retrieve_dto, seed_k=CHUNK_SEED_K)
        for rec in records_chunk:
            cid = rec.get('key_id')
            if cid:
                chunk_ids.append(str(cid))

        unique_entity_ids = list(dict.fromkeys(entity_ids))
        unique_chunk_ids = list(dict.fromkeys(chunk_ids))
        log.info(
            f"Found {len(unique_entity_ids)} seed entities and {len(unique_chunk_ids)} seed chunks for base={base}")
        return unique_entity_ids, unique_chunk_ids

    def _lexical_seed_entity_ids(self, base: str, query: str) -> List[str]:
        """问题里原样出现的实体名 → entity_id；可用环境变量关闭。"""
        if os.environ.get('GRAPH_LEXICAL_SEEDS_ENABLED', '1').strip().lower() \
                in {'0', 'false', 'no', 'off'}:
            return []
        trie = self._entity_mention_trie(base)
        if not trie:
            return []
        return find_mentions(query, trie, max_mentions=_MENTION_MAX_MENTIONS)

    def _entity_mention_trie(self, base: str) -> dict:
        now = time.time()
        cached = _MENTION_CACHE.get(base)
        if cached and now - cached[0] < _MENTION_CACHE_TTL:
            return cached[1]
        with _MENTION_CACHE_LOCK:
            cached = _MENTION_CACHE.get(base)
            if cached and now - cached[0] < _MENTION_CACHE_TTL:
                return cached[1]
            from graph.repository import graph_pg

            rows = graph_pg.entity_names(base, limit=_MENTION_MAX_ENTITIES)
            trie = build_mention_trie(rows)
            if len(_MENTION_CACHE) >= _MENTION_CACHE_MAX_BASES:
                _MENTION_CACHE.clear()
            _MENTION_CACHE[base] = (now, trie)
            log.info('[graph-seed] lexical mention trie base=%s entities=%s',
                     base, len(rows))
            return trie

    def _query_vector_index(self, base: str, key_type: str, query_embedding: str,
                            retrieve_dto: GraphRetrieveDto,
                            seed_k: Optional[int] = None) -> List[Dict]:
        """查询向量索引；``seed_k`` 省略时用 DTO 的 ``seed_k``。"""
        # 从retrieve_dto获取labels参数（仅对entity/edge生效，chunk不受labels影响）
        labels = retrieve_dto.labels if key_type in ['entity', 'edge'] else None
        sql, params = _build_retrieve_sql(
            base, key_type, query_embedding,
            seed_k if seed_k is not None else retrieve_dto.seed_k,
            retrieve_dto.score, labels)
        log.info(f"Retrieve seed nodes, base={base}, key_type={key_type}, labels={labels}")

        # 图谱向量/切片表（graph_<uuid>_vector / graph_<uuid>_chunk）在业务库的
        # kb_index schema 下。⚠️ 必须走参数化执行：带 params 时 psycopg2 用
        # extended protocol，不允许堆叠语句；这是阻断 chunk_id 注入的关键。
        started = time.perf_counter()
        status, records = _db_pool.pg_select_zip_values_operator_with_params(sql, params)
        rows = records if status and records else []
        log.info('vector index query base=%s key_type=%s labels=%s seek_k=%s rows=%s '
                 'status=%s elapsed=%.3fs',
                 base, key_type, labels or [], params[-1] if params else None,
                 len(rows), status, time.perf_counter() - started)
        return rows

    def _extract_entity_ids_from_records(self, records: List[Dict], key_type: str) -> List[str]:
        """从查询记录中提取entity_id"""
        entity_ids = []

        for record in records:
            key_id = record.get('key_id')
            if key_type == 'edge':
                # 端点单独落列；key_id 是 edge_id，不能拆。
                source_id = record.get('source_id')
                target_id = record.get('target_id')
                if source_id:
                    entity_ids.append(str(source_id))
                if target_id:
                    entity_ids.append(str(target_id))
            elif key_id:
                entity_ids.append(key_id)

        return entity_ids

    def _retrieve_subgraph_for_base(self, base: str, seed_entity_ids: List[str],
                                    retrieve_dto: GraphRetrieveDto) -> Dict[str, Any]:
        """为指定知识库检索子图（过滤行内系统字段）"""
        try:
            query_dto = self._build_subgraph_query_for_seeds(base, seed_entity_ids, retrieve_dto)

            subgraph_result = self._query_subgraph(query_dto, include_paths=False)

            raw_entities = subgraph_result.get('entities', [])
            raw_edges = subgraph_result.get('edges', [])

            # 过滤系统字段，只保留用户自定义属性
            entities = [self._filter_system_fields_for_retrieve(entity) for entity in raw_entities]
            edges = [self._filter_system_fields_for_retrieve(edge) for edge in raw_edges]

            log.info(f"Retrieved subgraph for base={base}, entities={len(entities)}, edges={len(edges)}")

            return {
                "base": base,
                "entities": entities,
                "edges": edges,
                "entity_count": len(entities),
                "edge_count": len(edges)
            }

        except Exception as e:
            log.error(f"Failed to retrieve subgraph for base={base}, error={str(e)}")
            return self._create_empty_base_result(base, str(e))

    def _filter_system_fields_for_retrieve(self, data: Dict) -> Dict:
        """为 retrieve 接口过滤行内系统字段，只保留用户自定义属性。

        规则：去掉 ``@`` 开头的字段、``out``/``in``，以及 ``out_*``/``in_*``
        这类自动生成的边关系字段。
        """
        filtered_data = {}
        for key, value in data.items():
            if (
                    not key.startswith('@') and
                    key not in {'out', 'in'} and
                    not key.startswith('out_') and
                    not key.startswith('in_')
            ):
                filtered_data[key] = value

        return filtered_data

    def _collect_chunk_ids_from_entities(self, entities: List[Dict[str, Any]]) -> List[str]:
        """从实体属性中收集 chunk_id（可能为逗号分隔字符串）"""
        ids: List[str] = []
        for ent in entities:
            raw_ids = ent.get('chunk_id')
            if not raw_ids:
                continue
            parts = [s.strip() for s in str(raw_ids).split(',') if s and s.strip()]
            ids.extend(parts)
        return list(set(ids))

    def _query_chunks_by_ids(self, base: str, chunk_ids: List[str]) -> Dict[str, Any]:
        """批量查询 chunk 详情并返回 {chunk_id: chunk_info} 映射。"""
        if not chunk_ids:
            return {}
        _validate_graph_base(base)
        table_full_name = f"kb_index.{base}_chunk"
        ids_list = [str(v).strip() for v in chunk_ids if str(v).strip()]
        if not ids_list:
            return {}
        # ⚠️ 这里曾是 SQL 注入点：chunk_id 来自导入 zip 的实体属性，被 f"'{x}'"
        # 直接拼进 SQL。现在改为绑定参数 + extended protocol（不可堆叠语句）。
        sql = f"SELECT * FROM {table_full_name} WHERE id = ANY(%s)"
        status, all_records = _db_pool.pg_select_zip_values_operator_with_params(
            sql, (ids_list,))
        if not status or not all_records:
            return {}
        id_to_row: Dict[str, Any] = {}
        for row in all_records:
            cid = row.get('id', "")
            id_to_row[cid] = {
                "chunk_id": row.get('id', ""),
                "source": row.get('source', ""),
                "chunk_order": row.get('chunk_order', ""),
                "spilt_type": row.get('spilt_type', ""),
                "text": row.get('text', ""),
                "label": row.get('label', ""),
                "table_name": row.get('table_name', ""),
                "table_id": row.get('table_id', "")
            }
        return id_to_row

    def _build_subgraph_query_for_seeds(self, base: str, seed_entity_ids: List[str],
                                        retrieve_dto: GraphRetrieveDto):
        """构建基于种子节点的子图查询"""
        from graph.models.graph_query_dto import GraphQueryDto, GraphFilter

        filter_obj = GraphFilter(
            start_entity_properties={"entity_id": seed_entity_ids}
        )

        depth = int(retrieve_dto.depth or 1)
        limit = int(retrieve_dto.limit or 1000)
        if limit == 1000:
            limit = _DEPTH_LIMIT_DEFAULTS.get(min(depth, 3), 1000)
        log.info('[graph-retrieve] depth=%s edge_limit=%s', depth, limit)
        return GraphQueryDto(
            kb_id=base,
            query_type='sub_graph',
            filters=[filter_obj],
            depth=depth,
            direction='both',
            limit=limit,
            prioritize_levels=True,
        )

    def _create_empty_base_result(self, base: str, error: Optional[str] = None) -> Dict[str, Any]:
        """创建空的知识库结果"""
        result = {
            "base": base,
            "entities": [],
            "edges": [],
            "entity_count": 0,
            "edge_count": 0,
            "seed_entity_ids": [],
            "chunks": {},
            "chunk_count": 0
        }

        if error:
            result["error"] = error

        return result

    def _build_retrieve_result(self, base_results: List[Dict], total_entities: int,
                               total_edges: int, retrieve_dto: GraphRetrieveDto) -> Dict[str, Any]:
        """构建最终的检索结果"""
        return {
            "base_results": base_results,
            "total_entities": total_entities,
            "total_edges": total_edges,
            "base_count": len(retrieve_dto.bases)
        }
