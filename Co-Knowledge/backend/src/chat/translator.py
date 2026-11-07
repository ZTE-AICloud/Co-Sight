"""画布 blob → 运行时配置（`RagConfig` 的形状）。

这是本服务**唯一自己定义**的数据映射。形状：

    {
      "workflow_id": "...",
      "query-engine":        {id, package, operator, kwargs},
      "pre-retriever":       [ {...}, ... ],
      "retriever":           [ ... ],
      "post-retriever":      [ ... ],
      "response-synthesizer":[ ... ],
      "workflow": {"edges": [[1,2],[2,3],[3,4]]}
    }

两边形状本来就近乎 1:1（方案里写过「画布 blob → RagConfig 是近乎 1:1 的翻译」）：
画布节点的 `variables` 下每个环节键对应的列表元素就是 `{package, operator, kwargs}`。

**id 与 edges 的处理**（默认配置里 id 是 1..N、edges 是相邻对）：
画布上的算子 id 是各自节点本地的（默认 1、自定义算子则是 `<nodeId>_<3位>`），
不能直接当运行时 id 用。这里按**画布连线的拓扑顺序**重新编号为 1..N，edges 则
**按画布的真实结构连**：节点内按算子顺序串，节点之间照画布的连线接（见
`:func:`_structured_edges``）—— 条件检索的画布是两条分支，串成一条链会让它跑成「一条半」。
只有**没有任何可用连线**（或连线成环、画布上没有可信结构）时才退回
「pre → retriever → post → synthesizer」的固定顺序并串成一条链，
两种情况都**记日志说明走了哪条路** —— 顺序错了会让编排执行顺序与用户画的不一致，必须可查。
"""
from typing import Any, Dict, List, Optional

from engine.logutil import logger

# 画布节点的 variables 键 → 运行时配置的段名（键名已逐个核对四个 Node.vue）
STAGE_KEY_TO_CONFIG = [
    ('preretriever', 'pre-retriever'),
    ('retriever', 'retriever'),
    ('postretriever', 'post-retriever'),
    ('responsesynthesizer', 'response-synthesizer'),
]
STAGE_CONFIG_ORDER = [config_key for _, config_key in STAGE_KEY_TO_CONFIG]
QUERY_ENGINE_COMPONENT = 'QUERY_ENGINE'
EDGES_COMPONENT = 'EDGES'


def _operators_of(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """取出一个节点里所有环节的算子，保持它们在画布上的顺序。"""
    variables = node.get('variables') or {}
    result = []
    for stage_key, config_key in STAGE_KEY_TO_CONFIG:
        stage_operators = variables.get(stage_key)
        if isinstance(stage_operators, list):
            for operator in stage_operators:
                if isinstance(operator, dict):
                    result.append((config_key, operator))
    return result


def _canvas_edges(other_node_config_list: Optional[List[Dict[str, Any]]]) -> List[List[str]]:
    for node in other_node_config_list or []:
        if node.get('componentType') != EDGES_COMPONENT:
            continue
        edges = ((node.get('variables') or {}).get('edges')) or []
        pairs = []
        for edge in edges:
            source, target = edge.get('source'), edge.get('target')
            if source and target:
                pairs.append([source, target])
        return pairs
    return []


def _node_order(node_ids: List[str], edges: List[List[str]]) -> Optional[List[str]]:
    """按连线做拓扑排序；**有环**才返回 None（交给调用方回退）。

    允许多个起点与孤立节点（它们按画布顺序排在队列里）—— 用户的画布上多一个还没连线的
    节点是常态（拖进来没配就保存），这种情况**不能**让整张画布退回单链：那样条件检索的
    两条分支会被串成一条，而且没有任何使用者可见的报错。孤立节点翻译后本来就连不到
    链上（运行期的 `get_workflow_nodes()` 从链头 BFS，够不着它），保持结构是对的。

    队列按 ``node_ids``（画布顺序）初始化 → 同一层里先出现的节点先编号，结果确定。
    """
    known = [node_id for node_id in node_ids if node_id]
    if len(known) != len(node_ids):
        return None
    indegree = {node_id: 0 for node_id in known}
    successors: Dict[str, List[str]] = {node_id: [] for node_id in known}
    for source, target in edges:
        if source not in indegree or target not in indegree:
            return None
        indegree[target] += 1
        successors[source].append(target)
    # 起点（无入边的节点）**按连通块排队**，覆盖节点最多的块先编号（并列时取画布顺序在前的）。
    # 为什么要挑：运行期 `RagContext.get_workflow_nodes()` 取「出现在边里的、无入边的节点中
    # 编号最小的那个」当链头，整张图从它 BFS。画布上多一个还没接完的节点（用户拖进来只连了
    # 下游、或干脆没连）就多一个起点，它一旦拿到更小的编号，主链会被整块当成不可达而跳过 ——
    # 表现是「画布上有、跑起来像没有」，且不报任何错。
    roots = [node_id for node_id in known if indegree[node_id] == 0]
    roots.sort(key=lambda node_id: (-len(_descendants(node_id, successors)), known.index(node_id)))
    queue: List[str] = [roots[0]] if roots else []
    pending_roots = roots[1:]
    ordered = []
    while queue or pending_roots:
        if not queue:
            # 上一个连通块编完了：接下一个起点（块与块之间没有边，谁先谁后只影响编号）
            queue.append(pending_roots.pop(0))
        current = queue.pop(0)
        ordered.append(current)
        for target in successors[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return ordered if len(ordered) == len(known) else None


def _descendants(start: str, successors: Dict[str, List[str]]) -> List[str]:
    """从 ``start`` 沿边能到达的全部节点（不含自己）。"""
    seen, queue = [], [start]
    while queue:
        current = queue.pop(0)
        for target in successors.get(current, []):
            if target not in seen:
                seen.append(target)
                queue.append(target)
    return seen


def _query_engine(other_node_config_list: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    for node in other_node_config_list or []:
        if node.get('componentType') != QUERY_ENGINE_COMPONENT:
            continue
        engine = ((node.get('variables') or {}).get('queryengine')) or {}
        if engine.get('operator'):
            return {
                'id': 0,
                'package': engine.get('package', ''),
                'operator': engine.get('operator'),
                'desc': engine.get('desc', ''),
                'kwargs': engine.get('kwargs') or {},
            }
    return {}


def canvas_to_rag_config(workflow_id: str, node_config_list, other_node_config_list) -> Dict[str, Any]:
    """画布 → 运行时配置。"""
    nodes = [node for node in (node_config_list or []) if isinstance(node, dict)]

    # 1) 每个节点带的是哪一段配置（用节点 id 记住，后面按顺序摊平）
    per_node: List[tuple] = []
    for index, node in enumerate(nodes):
        node_id = node.get('nodeId') or node.get('id') or f'node-{index}'
        per_node.append((node_id, _operators_of(node)))

    # 2) 定执行顺序
    node_ids = [node_id for node_id, _ in per_node]
    known_ids = set(node_ids)
    # 只认**两端都在画布上**的边：前端可能留下指向已删节点的陈旧边（`importGraph` 也按它重建连线）
    edges = [edge for edge in _canvas_edges(other_node_config_list)
             if edge[0] in known_ids and edge[1] in known_ids]
    ordered_ids = _node_order(node_ids, edges) if edges else None
    if ordered_ids:
        logger.info('operator order taken from canvas edges: %s', ordered_ids)
        ordered = [entry for node_id in ordered_ids for entry in per_node if entry[0] == node_id]
    else:
        # 回退：按固定环节顺序（pre → retriever → post → synthesizer），同环节内保持画布顺序
        logger.warning('canvas edges are missing or cyclic; '
                       'falling back to the fixed stage order (pre -> retriever -> post -> synthesizer)')
        ordered = sorted(per_node, key=lambda entry: _stage_rank(entry[1]))

    # 3) 摊平成运行时配置，并重新编号
    config: Dict[str, Any] = {config_key: [] for config_key in STAGE_CONFIG_ORDER}
    runtime_id = 1
    ops_by_node: Dict[str, List[int]] = {}
    for node_id, operators in ordered:
        operator_ids = []
        for config_key, operator in operators:
            config[config_key].append({
                'id': runtime_id,
                'package': operator.get('package', ''),
                'operator': operator.get('operator', ''),
                'desc': operator.get('desc', ''),
                'kwargs': operator.get('kwargs') or {},
            })
            operator_ids.append(runtime_id)
            runtime_id += 1
        ops_by_node[node_id] = operator_ids

    # 4) 运行时边。**两条路**：
    #    走拓扑序时按画布的真实结构连（分支画布要保住分支，见 _structured_edges）；
    #    退回固定环节序时没有可信的连线，只能按环节顺序串成一条链。
    runtime_edges = (_structured_edges(node_ids, ops_by_node, edges) if ordered_ids
                     else _chained_edges(ops_by_node))

    result = {
        'workflow_id': workflow_id,
        'query-engine': _query_engine(other_node_config_list),
        'workflow': {'edges': runtime_edges},
    }
    for config_key in STAGE_CONFIG_ORDER:
        result[config_key] = config[config_key]
    return result


def _chained_edges(ops_by_node: Dict[str, List[int]]) -> List[List[int]]:
    """把算子按编号顺序串成一条链（退回固定环节序时用）。"""
    edges: List[List[int]] = []
    previous_id = None
    for operator_ids in ops_by_node.values():
        for operator_id in operator_ids:
            if previous_id is not None:
                edges.append([previous_id, operator_id])
            previous_id = operator_id
    return edges


def _structured_edges(node_ids: List[str], ops_by_node: Dict[str, List[int]],
                      canvas_edges: List[List[str]]) -> List[List[int]]:
    """按**画布的真实结构**连边：节点内按顺序串，节点间照画布的连线接。

    为什么不能一律串成一条链：条件检索（``ConditionalQueryEngine``）的画布是**两条分支**，
    每条分支各带一个后检索算子与合成器。运行期 `RagContext.get_chain_all_nodes(retriever)`
    沿边找「这个检索器后面挂的是谁」，据此把那一路的后检索与合成器配给它 —— 串成一条链时，
    第一条分支会连到第二条分支的合成器上（引擎取链上**最后**一个合成器），另一条分支则
    永远拿不到自己的后检索：用户画的两条路，跑出来的是一条半。

    画布上有**没有算子**的节点（模板里的 ``QUERY`` / ``RESPONSE`` 伪节点，以及用户拖进来
    还没配算子的节点），它们不该出现在运行时的边里 —— 用 :func:`_anchor` 跨过去接上游/下游。

    产物排序 ``(source, target)``：与默认工作流配置里的边同序，便于逐行对比。
    """
    predecessors: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
    successors: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
    for source, target in canvas_edges:
        if source in successors and target in predecessors:
            successors[source].append(target)
            predecessors[target].append(source)
    for neighbours in (predecessors, successors):
        for node_id in neighbours:
            neighbours[node_id].sort()

    edges = set()
    for operator_ids in ops_by_node.values():
        for previous_id, operator_id in zip(operator_ids, operator_ids[1:]):
            edges.add((previous_id, operator_id))
    for source, target in canvas_edges:
        if source not in ops_by_node or target not in ops_by_node:
            continue
        source_id = _anchor(ops_by_node, source, predecessors, from_tail=True)
        target_id = _anchor(ops_by_node, target, successors, from_tail=False)
        if source_id is not None and target_id is not None and source_id != target_id:
            edges.add((source_id, target_id))
    return [[source, target] for source, target in sorted(edges)]


def _anchor(ops_by_node: Dict[str, List[int]], node_id: str,
            neighbours: Dict[str, List[str]], *, from_tail: bool) -> Optional[int]:
    """找一个节点的「算子锚点」：自己带算子就取自己（首/尾个），否则沿 ``neighbours``
    方向穿过无算子的节点继续找（广度优先、邻居已排序 → 结果稳定）。

    找不到（例如 ``QUERY`` 伪节点往上、``RESPONSE`` 伪节点往下）返回 ``None``，
    调用方据此跳过这条边 —— 那两端的链子本来就是链头/链尾。
    """
    seen = set()
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        operator_ids = ops_by_node.get(current) or []
        if operator_ids:
            return operator_ids[-1] if from_tail else operator_ids[0]
        queue.extend(neighbours.get(current, []))
    return None


def _stage_rank(operators: List[tuple]) -> int:
    """同环节归一组，用于回退排序。"""
    if not operators:
        return len(STAGE_CONFIG_ORDER)
    config_key = operators[0][0]
    return STAGE_CONFIG_ORDER.index(config_key) if config_key in STAGE_CONFIG_ORDER else len(STAGE_CONFIG_ORDER)
