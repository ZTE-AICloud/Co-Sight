"""画布（``nodeConfigDTOList`` / ``otherNodeConfigList``）的解析。

画布 JSON **原样存**（后端不解释节点结构，画布改版时这里不用跟着改），
所以本模块只做「读」的几件事：找编排引擎、抽算子、收集绑定的知识库名、
去 scope 后缀。

画布的形状（前端 ``CustomizedAdvancedFlow.exportGraph()`` 产出）::

    nodeConfigDTOList: [
      {"variables": {"preretriever": [{"package": ..., "operator": ..., "kwargs": {...}}],
                     "retriever": [...], "postretriever": [...], "responsesynthesizer": [...]}},
      ...
    ]
    otherNodeConfigList: [
      {"componentType": "QUERY_ENGINE", "variables": {"queryengine": {"operator": "SequentialQueryEngine"}}},
      {"componentType": "EDGES", ...}
    ]
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from shared.kb_names import drop_scope_suffix

# 编排引擎伪节点
COMPONENT_QUERY_ENGINE = 'QUERY_ENGINE'
ENGINE_SEQUENTIAL = 'SequentialQueryEngine'
ENGINE_BLENDED = 'BlendedQueryEngine'
ENGINE_CONDITIONAL = 'ConditionalQueryEngine'

# 本栈 vendor 了、因而发布时不拒的引擎（**必须与编排层的
# `default_packages_info.query_engine_packages` 一一对应**：这里放行一个没 vendor 的引擎，
# 表现是「发布成功、一问就 500」，而画布上完全看不出来）。
#
# 三个引擎对能力的要求不同，画布与模板之外的约束只有一个：
# 查询请求里带 `base_names`（指定知识库问答）时，运行期 `RagContext._check_query_engine`
# 只放行顺序与混合两种（条件引擎的检索器由查询路由挑，不能被外部指定覆盖）。
ENGINE_OPERATORS = frozenset({ENGINE_SEQUENTIAL, ENGINE_BLENDED, ENGINE_CONDITIONAL})

# 画布序列化上限（5MB）
MAX_CANVAS_BYTES = 5 * 1024 * 1024

# 四个环节的键名（出现在 node.variables 里）
STAGE_KEYS = ('preretriever', 'retriever', 'postretriever', 'responsesynthesizer')

# 知识库名相关键
KEY_KWARGS = 'kwargs'
KEY_KNOWLEDGE_BASE_NAME = 'knowledge_base_name'
KEY_KNOWLEDGE_INFO_LIST = 'knowledge_info_list'
KEY_GENERATOR_CONFIG = 'generator_config'

# 绑定关系提取时要剥掉的前缀（库标识 → uuid/pkId）。``doc_`` 是
# 文档库基名；``graph_`` 图谱库；``data_`` 是旧向量表拼法（保留兜底）。
KB_NAME_PREFIXES = ('doc_', 'graph_', 'data_')
# 物理表名后缀：``doc_<uuid>_vector`` 的身份 token 是中间的 uuid
KB_NAME_SUFFIXES = ('_vector', '_chunk')


def node_list(value: Any) -> list[dict]:
    """把「可能是 null / 不是 list」的节点列表归一成 list（画布字段全可选）。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def find_engine_operator(other_node_config: Any) -> str | None:
    """取编排引擎名：``otherNodeConfigList`` 里 ``componentType=QUERY_ENGINE`` 的伪节点，
    其 ``variables.queryengine.operator``。缺失返回 None。"""
    for node in node_list(other_node_config):
        if node.get('componentType') != COMPONENT_QUERY_ENGINE:
            continue
        variables = node.get('variables')
        if not isinstance(variables, dict):
            continue
        query_engine = variables.get('queryengine')
        if not isinstance(query_engine, dict):
            continue
        operator = query_engine.get('operator')
        return None if operator is None else str(operator)
    return None


def extract_operators(variables: Any) -> list[dict]:
    """从节点 ``variables`` 里取出所有算子对象。

    规则：``variables`` 下**所有** list 值里的 dict 都算算子。
    对「值恰好是 List 但不是算子列表」的情况**不做特判** —— 宁可多报一个警告，
    也不要把一个藏在预期之外的键名下的算子漏掉（漏报会导致发布通过、运行期才炸）。
    这是有意行为，改之前先想清楚往哪边失败。
    """
    operators: list[dict] = []
    if not isinstance(variables, dict):
        return operators
    for value in variables.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                operators.append(item)
    return operators


def iter_operators(node_config: Any) -> Iterator[dict]:
    """遍历画布上全部算子（跨节点）。"""
    for node in node_list(node_config):
        yield from extract_operators(node.get('variables'))


def find_operator_names(node_config: Any) -> list[str]:
    """全部算子名（用于判断是否用了需要 rerank 端点的算子）。"""
    names: list[str] = []
    for operator in iter_operators(node_config):
        names.append('' if operator.get('operator') is None else str(operator.get('operator')))
    return names


def strip_kb_prefix(name: str) -> str:
    """去掉库名前缀与物理表后缀，得到「标识 token」（uuid 或 pkId）。

    删除前置检查里做 token 比较：画布上的库名是
    ``doc_<uuid>`` / ``graph_<uuid>`` / ``data_<uuid>``（+可选 scope 后缀），
    而调删除接口时手里只有 uuid 或 pkId，两边要靠 token 对上。
    """
    token = name
    stripped = True
    while stripped:
        stripped = False
        for prefix in KB_NAME_PREFIXES:
            if token.startswith(prefix):
                token = token[len(prefix):]
                stripped = True
                break
    for suffix in KB_NAME_SUFFIXES:
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def collect_bound_kbase_names(node_config: Any) -> list[str]:
    """从画布节点里取出所有绑定的知识库名（去 scope 后缀、去重、保持出现顺序）。

    取库名的三个位置（已逐个核对前端 modules 各算子的 Drawer.vue）：

    1. ``kwargs.knowledge_base_name`` —— 关键字检索 / 图谱检索的直挂字段
    2. ``kwargs.knowledge_info_list[].knowledge_base_name`` —— 向量检索的多库列表
    3. ``kwargs.generator_config[].knowledge_base_name`` —— 响应合成器

    扫**全部** variables 列表
    而不是只看 retriever/responsesynthesizer 两个键 —— 上游漏掉一处就是「删库把工作流
    删坏」，多扫到的键（如预检索器）本就不含知识库名，误报代价为零。
    """
    names: dict[str, None] = {}
    for operator in iter_operators(node_config):
        kwargs = operator.get(KEY_KWARGS)
        if not isinstance(kwargs, dict):
            continue
        _add_names(kwargs.get(KEY_KNOWLEDGE_BASE_NAME), names)
        _add_names_from_config_list(kwargs.get(KEY_KNOWLEDGE_INFO_LIST), names)
        _add_names_from_config_list(kwargs.get(KEY_GENERATOR_CONFIG), names)
    return list(names)


def _add_names_from_config_list(value: Any, names: dict) -> None:
    """取「配置列表」里每个元素的 ``knowledge_base_name``。"""
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return
    for item in value:
        if isinstance(item, dict):
            _add_names(item.get(KEY_KNOWLEDGE_BASE_NAME), names)


def _add_names(value: Any, names: dict) -> None:
    """加一个名字：字符串或字符串数组都收（前端历史版本两种形态都出现过）。"""
    if isinstance(value, str):
        _add_name(value, names)
        return
    if isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        for item in value:
            if isinstance(item, str):
                _add_name(item, names)


def _add_name(raw_name: str, names: dict) -> None:
    if not raw_name or not raw_name.strip():
        return
    name = drop_scope_suffix(raw_name.strip())
    if name:
        names[name] = None
