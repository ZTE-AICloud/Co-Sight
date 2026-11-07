"""知识图谱检索算子。

数据源：RKB（rag-knowledge-base）的 `POST /api/co-knowledge/v1/retrieval/graph`，
入参与响应键保持同构（`GraphRetrieveDto` → `data.base_results[]`）。

**3 处刻意行为**：

1. 删掉 `_retrieve` 外层的 `try/except -> return []` —— 静默空返回会造出
   「HTTP 200、其实没检索」的隐形失败；异常冒泡，与同目录 `vector_retriever` 一致；
2. per-base 的 `except -> continue` 改为**记 error 后抛出**（异常里带上 base 名）——
   静默丢掉 N 个库里的 1 个，症状正是「答得不对但状态码 200」；
3. import 路径对齐本仓（`core.gateways.knowledge_base_client` / `tools.utils.http_utils`
   / `tools.log.logutil.logger`）。

已知行为（不是 bug，勿改）：只用了 expand_format / source_format / base_format 三个
引用标记，`node_id_format` / `chunk_index_format` 从未使用 —— 图谱节点在前端没有引用序号。
"""
import re
import time
from abc import ABC
from collections import defaultdict, deque
from typing import List, Dict, Set, Any

from engine.primitives.models import NodeWithScore, QueryBundle, TextNode

from engine.common import const, stage_timing
from engine.common.exception.rag_exception import RagException
from engine.gateways.knowledge_base_client import invoke_knowledge_graph_client
from engine.retriever import RagNodeWithScore
from engine.retriever.base import BaseRagRetriever
from engine.logutil import logger
from engine.http_utils import build_headers


def _create_node_from_chunk(
        chunk_info: Dict[str, Any],
        chunk_text: str,
        related_chunk_ids: List[str],
        base_name: str
) -> Dict[str, Any]:
    text = f"{const.expand_format}{chunk_text}{const.expand_format}"
    metadata = {
        'source': f"{const.source_format}{chunk_info.get('source', '')}{const.source_format}",
        'content_expand': '',
        'knowledge_name': f"{const.base_format}{base_name}{const.base_format}",
        'chunk_id': chunk_info.get('chunk_id', ''),
        'chunk_order': chunk_info.get('chunk_order', ''),
        'spilt_type': chunk_info.get('spilt_type', ''),  # typo? "split_type"
        'label': chunk_info.get('label', ''),
        'table_name': chunk_info.get('table_name', ''),
        'table_id': chunk_info.get('table_id', ''),
        'related_chunk_ids': related_chunk_ids  # already a flat list
    }
    return {
        'text': text,
        'relationships': {},
        'metadata': metadata
    }


#: chunk 模式默认只回 seed chunk；打开 `include_edge_facts` 后，把 seed 及其
#: 一跳邻居上的边压成短事实块附在 seed chunk 正文后。属性边（日期/出生地/国籍等）
#: 在多数图谱里度数很低，优先保留；其余边按“直接边优先、二跳属性边补足”截断。
GRAPH_FACT_MAX_DIRECT = 6
GRAPH_FACT_MAX_SECOND = 6
GRAPH_FACT_MAX_PER_CHUNK = 12
#: 高度数邻居（国家/年份等 hub）会把大量无关事实带进来；不再沿它做二跳扩散。
GRAPH_FACT_MAX_NEIGHBOR_DEGREE = 12
GRAPH_FACT_ATTRIBUTE_HINTS = (
    'date', 'birth', 'born', 'death', 'died', 'country', 'citizenship',
    'place', 'location', 'located', 'origin', 'publication', 'release',
    'inception', 'spouse', 'father', 'mother', 'parent', 'child', 'director',
    'performer', 'award', 'occupation', 'employer', 'genre', 'founded',
    'alias',
)
GRAPH_FACT_LITERAL_RE = re.compile(r'^\s*\d{3,4}(?:[-/]\d{1,2}){0,2}\s*$')
#: 属性事实里展示的实体名去掉前缀头衔，避免 “King X / X” 被答案层当成两个名字。
#: 括号限定词（如年份）保留，因为同名电影靠它区分。
GRAPH_FACT_TITLE_PREFIXES = (
    'king', 'queen', 'emperor', 'empress', 'archduke', 'archduchess',
    'prince', 'princess', 'duke', 'duchess', 'count', 'countess',
    'maharaja', 'maharani', 'sir', 'dame',
)


def _entity_display_name(entity: Dict[str, Any]) -> str:
    name = str(entity.get('entity_name') or entity.get('name')
               or entity.get('entity_id') or '')
    parts = name.split()
    if len(parts) > 1 and parts[0].lower().strip('.,') in GRAPH_FACT_TITLE_PREFIXES:
        return ' '.join(parts[1:])
    return name


def _edge_relation_label(edge: Dict[str, Any]) -> str:
    """RKB 的 `/retrieval/graph` 把关系字段放在顶层；导入包里才在 properties 下。"""
    properties = edge.get('properties') or {}
    return str(properties.get('relationship_keywords')
               or edge.get('relationship_keywords')
               or edge.get('type') or edge.get('relation_type') or '').strip()


def _edge_description(edge: Dict[str, Any]) -> str:
    properties = edge.get('properties') or {}
    return str(properties.get('relationship_description')
               or edge.get('relationship_description') or '').strip()


def _is_attribute_edge(edge: Dict[str, Any], names: Dict[str, str]) -> bool:
    """属性边判断：关系名/描述命中白名单，或目标本身是日期/年份字面量。"""
    label = _edge_relation_label(edge).lower()
    description = _edge_description(edge).lower()
    if any(hint in label or hint in description
           for hint in GRAPH_FACT_ATTRIBUTE_HINTS):
        return True
    target = names.get(str(edge.get('target_id') or ''), '')
    return bool(GRAPH_FACT_LITERAL_RE.match(target))


def _edge_fact_line(edge: Dict[str, Any], names: Dict[str, str]) -> str:
    source = names.get(str(edge.get('source_id') or ''),
                       str(edge.get('source_id') or ''))
    target = names.get(str(edge.get('target_id') or ''),
                       str(edge.get('target_id') or ''))
    label = _edge_relation_label(edge)
    line = f"- {source} --[{label}]--> {target}" if label else \
        f"- {source} --> {target}"
    description = _edge_description(edge)
    if description and description.lower() not in line.lower():
        line += f" ({description})"
    return line


def _edge_facts_for_seed(
        seed_id: str,
        entity_id_to_entity: Dict[str, Dict[str, Any]],
        edges: List[Dict[str, Any]],
) -> List[str]:
    """一个 seed 的直接边 + 一跳邻居上的属性边，按优先级截断。"""
    names = {eid: _entity_display_name(entity)
             for eid, entity in entity_id_to_entity.items()}
    direct: List[Dict[str, Any]] = []
    neighbor_ids: Set[str] = set()
    for edge in edges:
        source = str(edge.get('source_id') or '')
        target = str(edge.get('target_id') or '')
        if seed_id in (source, target):
            direct.append(edge)
            neighbor_ids.update((source, target))
    neighbor_ids.discard(seed_id)

    # 日期/年份字面量是典型 hub（1966 连着几十部电影）；沿它扩散只会带噪声。
    # 高度数邻居同理，二跳只保留“低度数、非字面量”的中间实体。
    degree: Dict[str, int] = defaultdict(int)
    for edge in edges:
        for endpoint in (edge.get('source_id'), edge.get('target_id')):
            if endpoint is not None:
                degree[str(endpoint)] += 1
    neighbor_ids = {
        neighbor_id for neighbor_id in neighbor_ids
        if not GRAPH_FACT_LITERAL_RE.match(names.get(neighbor_id, '').strip())
        and degree.get(neighbor_id, 0) <= GRAPH_FACT_MAX_NEIGHBOR_DEGREE
    }

    direct.sort(key=lambda edge: 0 if _is_attribute_edge(edge, names) else 1)
    direct_ids = {id(edge) for edge in direct}
    second = [
        edge for edge in edges
        if id(edge) not in direct_ids
        and (str(edge.get('source_id') or '') in neighbor_ids
             or str(edge.get('target_id') or '') in neighbor_ids)
        and _is_attribute_edge(edge, names)
    ]
    selected = direct[:GRAPH_FACT_MAX_DIRECT] + second[:GRAPH_FACT_MAX_SECOND]
    return [_edge_fact_line(edge, names) for edge in selected]


def _build_subgraph_text(
        seed_entity_id: str,
        entity_id_to_entity: Dict[str, Dict[str, Any]],
        entity_connections: Dict[str, Set[str]],
        edge_info: Dict[tuple, Dict[str, Any]],
        depth: int
) -> str:
    """
    从种子节点开始，按照指定深度构建子图文本

    Args:
        seed_entity_id: 种子节点ID
        entity_id_to_entity: 实体ID到实体的映射
        entity_connections: 实体连接关系（双向）
        edge_info: 边的详细信息，key为(src_id, tgt_id)元组
        depth: 查询深度

    Returns:
        子图的文本表示
    """
    if seed_entity_id not in entity_id_to_entity:
        return ""

    # BFS遍历，按深度收集节点
    visited: Set[str] = {seed_entity_id}
    queue = deque([(seed_entity_id, 0)])  # (entity_id, current_depth)
    subgraph_edges: List[tuple] = []

    # 按深度层级收集实体（使用有序字典的key作为排序依据）
    entities_by_depth: Dict[int, List[str]] = defaultdict(list)
    entities_by_depth[0].append(seed_entity_id)
    max_depth = 0

    while queue:
        current_id, current_depth = queue.popleft()

        if current_depth >= depth:
            continue

        # 遍历邻居节点
        neighbors = entity_connections.get(current_id, set())
        for neighbor_id in neighbors:
            if neighbor_id not in visited and neighbor_id in entity_id_to_entity:
                visited.add(neighbor_id)
                next_depth = current_depth + 1
                if next_depth <= depth:
                    queue.append((neighbor_id, next_depth))
                    entities_by_depth[next_depth].append(neighbor_id)
                    max_depth = max(max_depth, next_depth)
                    # 记录边
                    subgraph_edges.append((current_id, neighbor_id))

    # 预先缓存实体名称和属性，避免重复查找
    entity_names: Dict[str, str] = {}
    entity_types: Dict[str, str] = {}
    entity_attrs: Dict[str, List[tuple]] = {}  # (key, value) pairs

    excluded_keys = {'entity_id', 'name', 'type', 'chunk_id'}
    for eid in visited:
        entity = entity_id_to_entity[eid]
        entity_names[eid] = entity.get('name', entity.get('entity_id', eid))
        entity_types[eid] = entity.get('type', '')
        # 预先过滤属性
        attrs = [
            (key, value) for key, value in entity.items()
            if key not in excluded_keys and value is not None and value != ''
        ]
        entity_attrs[eid] = attrs

    # 构建子图文本（使用列表join优化）
    lines = []

    # 按深度顺序输出实体（直接遍历0到max_depth，避免sorted）
    for d in range(max_depth + 1):
        if d not in entities_by_depth:
            continue
        entity_ids = entities_by_depth[d]
        for eid in entity_ids:
            entity_name = entity_names[eid]
            entity_type = entity_types[eid]
            if entity_type:
                lines.append(f"Entity[Level {d}]: {entity_name} (Type: {entity_type})")
            else:
                lines.append(f"Entity[Level {d}]: {entity_name}")

            # 添加实体的其他属性信息
            for key, value in entity_attrs[eid]:
                lines.append(f"  - {key}: {value}")

    # 输出边关系（使用缓存的名称）
    if subgraph_edges:
        lines.append("\nRelations:")
        for src_id, tgt_id in subgraph_edges:
            src_name = entity_names[src_id]
            tgt_name = entity_names[tgt_id]

            # 获取边的类型或其他属性（检查两个方向）
            edge_key = (src_id, tgt_id)
            if edge_key in edge_info:
                edge_data = edge_info[edge_key]
            else:
                edge_data = edge_info.get((tgt_id, src_id), {})
            relation_type = edge_data.get('type', edge_data.get('relation_type', ''))

            if relation_type:
                lines.append(f"  {src_name} --[{relation_type}]--> {tgt_name}")
            else:
                lines.append(f"  {src_name} -> {tgt_name}")

    return "\n".join(lines)


def _check_need_subgraph_processing(
        entities: List[Dict[str, Any]],
        chunks: Dict[str, Dict[str, Any]]
) -> bool:
    """
    检查是否需要使用子图处理逻辑

    Args:
        entities: 实体列表
        chunks: chunks字典

    Returns:
        True表示需要子图处理，False表示使用原有chunk处理逻辑
    """
    # 如果没有chunks，需要使用子图处理
    if not chunks:
        return True

    # 检查所有实体是否都没有chunk_id
    has_chunk_id = False
    for entity in entities:
        chunk_id = entity.get('chunk_id', '')
        if chunk_id and chunk_id.strip():
            has_chunk_id = True
            break

    # 如果所有实体都没有chunk_id，需要使用子图处理
    return not has_chunk_id


def _process_base_result_with_subgraph(
        base_result: Dict[str, Any],
        base_name: str,
        depth: int
) -> List[RagNodeWithScore]:
    """
    处理没有chunk_id的图谱数据，构建子图

    Args:
        base_result: 基础结果
        base_name: 知识库名称
        depth: 查询深度

    Returns:
        RagNodeWithScore列表
    """
    entities = base_result.get('entities', [])
    edges = base_result.get('edges', [])
    seed_entity_ids = base_result.get('seed_entity_ids', [])

    if not seed_entity_ids:
        return []

    # Build entity ID -> entity map
    entity_id_to_entity = {
        e['entity_id']: e for e in entities
        if e.get('entity_id') is not None
    }

    # Build bidirectional entity connections and edge info
    entity_connections = defaultdict(set)
    edge_info: Dict[tuple, Dict[str, Any]] = {}
    for edge in edges:
        src = edge.get('source_id')
        tgt = edge.get('target_id')
        if src and tgt:
            entity_connections[src].add(tgt)
            entity_connections[tgt].add(src)
            # 保存边的详细信息（排除source_id和target_id，因为它们已经是key的一部分）
            edge_data = {k: v for k, v in edge.items() if k not in ['source_id', 'target_id']}
            # 只保存一个方向，查找时检查两个方向（节省内存）
            edge_info[(src, tgt)] = edge_data

    # 预先计算格式化字符串，避免重复计算
    base_name_formatted = f"{const.base_format}{base_name}{const.base_format}"

    # 为每个种子节点构建子图
    nodes: List[RagNodeWithScore] = []
    for seed_id in seed_entity_ids:
        if seed_id not in entity_id_to_entity:
            continue

        # 构建子图文本
        subgraph_text = _build_subgraph_text(
            seed_id, entity_id_to_entity, entity_connections, edge_info, depth
        )

        if not subgraph_text:
            continue

        # 创建节点
        seed_entity = entity_id_to_entity[seed_id]
        text = f"{const.expand_format}{subgraph_text}{const.expand_format}"
        source_value = seed_entity.get('source', '')
        source_formatted = f"{const.source_format}{source_value}{const.source_format}"
        metadata = {
            'source': source_formatted,
            'content_expand': '',
            'knowledge_name': base_name_formatted,
            'chunk_id': '',
            'chunk_order': '',
            'spilt_type': '',
            'label': seed_entity.get('label', ''),
            'table_name': '',
            'table_id': '',
            'related_chunk_ids': []
        }

        node_json = {
            'text': text,
            'relationships': {},
            'metadata': metadata
        }

        node = RagNodeWithScore(
            node=TextNode.from_dict(node_json),
            score=0.0,
            base_name=base_name
        )
        nodes.append(node)

    return nodes


def _process_base_result(
        base_result: Dict[str, Any],
        base_name: str,
        chunks: Dict[str, Dict[str, Any]],
        depth: int = 1,
        include_edge_facts: bool = False
) -> List[RagNodeWithScore]:
    entities = base_result.get('entities', [])

    # 检查是否需要使用子图处理逻辑
    if _check_need_subgraph_processing(entities, chunks):
        return _process_base_result_with_subgraph(base_result, base_name, depth)

    # 原有的chunk处理逻辑
    edges = base_result.get('edges', [])
    seed_entity_ids = base_result.get('seed_entity_ids', [])

    # Build entity ID -> entity map
    entity_id_to_entity = {
        e['entity_id']: e for e in entities
        if e.get('entity_id') is not None
    }

    # Build entity -> chunk_id set
    entity_chunk_ids: Dict[str, Set[str]] = {}
    for eid, entity in entity_id_to_entity.items():
        chunk_id_str = entity.get('chunk_id', '')
        if chunk_id_str:
            chunk_ids = {s.strip() for s in chunk_id_str.split(',') if s.strip()}
            entity_chunk_ids[eid] = chunk_ids
        else:
            entity_chunk_ids[eid] = set[str]()

    # Build bidirectional entity connections
    entity_connections = defaultdict(set)
    for edge in edges:
        src = edge.get('source_id')
        tgt = edge.get('target_id')
        if src and tgt:
            entity_connections[src].add(tgt)
            entity_connections[tgt].add(src)

    # Track processed chunk IDs and their node JSON
    processed_chunk_nodes: Dict[str, Dict] = {}
    seed_chunk_ids: Set[str] = set()

    # 预先按 chunk 汇总事实行：同一 chunk 可能被多个 seed 命中，先合并再建节点，
    # 避免「后命中的 seed 只合并 related_chunk_ids、正文却漏掉它的边」。
    edge_facts_by_chunk: Dict[str, List[str]] = {}
    if include_edge_facts:
        for seed_id in seed_entity_ids:
            if seed_id not in entity_chunk_ids:
                continue
            lines = _edge_facts_for_seed(seed_id, entity_id_to_entity, edges)
            if not lines:
                continue
            for chunk_id in entity_chunk_ids.get(seed_id, set()):
                bucket = edge_facts_by_chunk.setdefault(chunk_id, [])
                for line in lines:
                    if line not in bucket and len(bucket) < GRAPH_FACT_MAX_PER_CHUNK:
                        bucket.append(line)

    # Process each seed entity
    for seed_id in seed_entity_ids:
        if seed_id not in entity_chunk_ids:
            continue

        seed_chunks = entity_chunk_ids[seed_id]
        connected_chunk_ids: Set[str] = set()

        # Gather chunks from directly connected entities
        for neighbor_id in entity_connections.get(seed_id, []):
            connected_chunk_ids.update(entity_chunk_ids.get(neighbor_id, set()))

        for chunk_id in seed_chunks:
            if chunk_id not in chunks:
                continue

            # Exclude self and non-existent chunks
            related_chunk_ids = [
                cid for cid in connected_chunk_ids
                if cid in chunks and cid != chunk_id
            ]

            if chunk_id in processed_chunk_nodes:
                # continue
                # Merge related_chunk_ids
                existing = set(processed_chunk_nodes[chunk_id]['metadata']['related_chunk_ids'])
                merged = existing | set(related_chunk_ids)
                processed_chunk_nodes[chunk_id]['metadata']['related_chunk_ids'] = list(merged)
                continue
            else:
                chunk_text = chunks[chunk_id].get('text', '')
                facts = edge_facts_by_chunk.get(chunk_id) or []
                if facts:
                    chunk_text = (chunk_text + '\n\nKnowledge graph facts:\n'
                                  + '\n'.join(facts))
                node_json = _create_node_from_chunk(
                    chunks[chunk_id], chunk_text, related_chunk_ids, base_name
                )
                processed_chunk_nodes[chunk_id] = node_json

            seed_chunk_ids.add(chunk_id)

    # Process non-seed chunks (fallback semantic hits)
    for chunk_id, chunk_info in chunks.items():
        if chunk_id not in seed_chunk_ids:
            node_json = _create_node_from_chunk(
                chunk_info, chunk_info.get('text', ''), [], base_name
            )
            processed_chunk_nodes[chunk_id] = node_json

    # Convert to RagNodeWithScore
    return [
        RagNodeWithScore(
            node=TextNode.from_dict(node_json),
            score=0.0,
            base_name=base_name
        )
        for node_json in processed_chunk_nodes.values()
    ]


class KnowledgeGraphRetriever(BaseRagRetriever, ABC):

    def __init__(self, config_info: Dict[str, Any]):
        super().__init__()
        self.config_info = config_info
        self.header = config_info.get('headers')

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """图谱检索。

        **不做 try/except -> return []**（这个分支原本会把「检索失败」伪装成「检索为空」）：
        客户端与网关的异常一律冒泡，由 app 层转成显式错误码。
        """
        started = time.perf_counter()
        body = self._build_request_body(query_bundle.query_str)
        logger.info('[retriever][graph] bases=%s embedding=%r seed_k=%s depth=%s score=%s '
                    'query_len=%s',
                    body.get('bases'), body.get('embedding'), body.get('seed_k'),
                    body.get('depth'), body.get('score'), len(body.get('query') or ''))
        # 分项耗时：图谱工作流没有向量/关键字两路，只有这段能标明「这是图谱检索」。
        # 与 vector_retriever 的口径一致：只量客户端调用，不含本地节点整形。
        with stage_timing.measure(stage_timing.STAGE_GRAPH_RETRIEVAL):
            response_data = invoke_knowledge_graph_client(build_headers(self.header), body)

        base_results = response_data.get('base_results', [])
        all_nodes: List[NodeWithScore] = []
        depth = self.config_info.get('depth', 1)
        include_edge_facts = bool(self.config_info.get('include_edge_facts', False))

        for base_result in base_results:
            base_name = base_result.get('base', '')
            chunks = base_result.get('chunks', {})
            seeds = base_result.get('seed_entity_ids') or []
            entities = base_result.get('entities') or []
            edges = base_result.get('edges') or []

            try:
                nodes = _process_base_result(
                    base_result, base_name, chunks, depth,
                    include_edge_facts=include_edge_facts)
                all_nodes.extend(nodes)
            except Exception as e:
                # 不 continue：丢掉 N 个库里的 1 个 = 「答得不对但状态码 200」
                logger.error('Error processing base result %s (seeds=%s entities=%s '
                             'edges=%s chunks=%s): %s',
                             base_name, len(seeds), len(entities), len(edges), len(chunks),
                             e, exc_info=True)
                raise RagException(-2, 'request-knowledge-graph-failed', base_name) from e

            logger.info('[retriever][graph] base=%s seeds=%s entities=%s edges=%s '
                        'chunks=%s nodes=%s',
                        base_name, len(seeds), len(entities), len(edges), len(chunks),
                        len(nodes))

        logger.info('[retriever][graph] done bases=%s nodes=%s elapsed=%.3fs',
                    len(base_results), len(all_nodes), time.perf_counter() - started)
        return all_nodes

    def _build_request_body(self, question: str) -> Dict[str, Any]:
        knowledge_base_names = self.config_info.get('knowledge_base_name', [])
        kb_ids = [kb.split('|#|')[0] if '|#|' in kb else kb for kb in knowledge_base_names]
        return {
            "query": question,
            "embedding": self.config_info.get('embedding', ''),
            "bases": kb_ids,
            "seed_k": self.config_info.get('top_k', 10),
            "depth": self.config_info.get('depth', 1),
            "score": self.config_info.get('score', 0),
        }

    def get_description(self) -> str:
        return self.config_info.get('desc_info', '')

    @classmethod
    def from_args(cls, config_dict: Dict[str, Any]) -> "BaseRagRetriever":
        return KnowledgeGraphRetriever(config_dict)
