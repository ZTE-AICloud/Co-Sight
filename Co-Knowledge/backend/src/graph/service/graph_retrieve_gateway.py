"""图谱检索的**进程内入口**与响应构造。

为什么有这个模块：同一条能力现在有两条调用路径 ——
  1. RKB 自己的 HTTP 路由 ``POST <RKB_PREFIX>/retrieval/graph``（浏览器/外部走它）；
  2.编排层在**同进程内**调用。
两条路径必须产出**同一形状**的响应与同一套错误映射，否则「编排看到的失败原因」
与「浏览器看到的」会悄悄分叉。所以把实现收在这里，两边都调这里。

本接口走统一 REST 契约（与其余 ``/api/co-knowledge/v1`` 端点一致）：
成功返回**检索结果对象本身**，失败抛 :class:`GraphRetrieveError`，
由 HTTP 侧映射成真实状态码 + ``application/problem+json``、进程内侧映射成同形 dict。

⚠️ 本模块是**叶子**：不得 import `app`。原因有二 ——
  * `app.py` 会 import 本模块（反向依赖），成环；
  * P3 之后 `app.py` 还要 import 编排的路由，编排又要经 `rkb_transport`
    回到本模块，环会绕得更远。
只依赖 common/tool/core 这三类底层件。
"""
import time
from typing import Any, Optional

from graph.models.graph_retrieve_dto import GraphRetrieveDto
from infrastructure.http.request_headers import EMRequestHeaders
from shared.errors.exception import EMException
from shared.problem import (INTERNAL_ERROR, UPSTREAM_UNAVAILABLE, ProblemSpec,
                            generic_detail)
from graph.service.graph_query_service import GraphQueryService
from infrastructure.http import headers as httputil
from infrastructure.logging.logutil import log


class GraphRetrieveError(Exception):
    """图谱检索失败：已解析的问题规格 + 已本地化的 ``detail``。"""

    def __init__(self, spec: ProblemSpec, detail: str):
        super().__init__(detail)
        self.spec = spec
        self.detail = detail


#: 检索路径上会出现的 ``EMException`` 码 → problem 规格（逐键显式，未知码按 500）。
_GRAPH_ERROR_SPECS: dict[str, ProblemSpec] = {
    'embedding-service-error': UPSTREAM_UNAVAILABLE,
    'database-operation-failed': INTERNAL_ERROR,
}


def graph_problem_spec(error_code: str) -> ProblemSpec:
    """``EMException`` 的错误码 → :class:`ProblemSpec`。"""

    return _GRAPH_ERROR_SPECS.get(error_code, INTERNAL_ERROR)


def graph_error_message(exception: EMException, language: str) -> str:
    """根据异常类型和语言获取错误消息

    Args:
        exception: 异常对象
        language: 语言标识

    Returns:
        str: 错误消息
    """
    # 错误消息映射
    error_messages = {
        'file-size-exceeded': {
            'zh': '文件大小超过限制',
            'en': 'File size exceeds limit'
        },
        'extract-size-exceeded': {
            'zh': '解压后文件大小超过限制',
            'en': 'Extracted file size exceeds limit'
        },
        'unsupported-file-format': {
            'zh': '文件格式不支持',
            'en': 'File format not supported'
        },
        'invalid-file-format': {
            'zh': '文件格式无效',
            'en': 'Invalid file format'
        },
        'schema-name-exists': {
            'zh': 'Schema名称已存在',
            'en': 'Schema name already exists'
        },
        'empty-file': {
            'zh': '文件内容为空',
            'en': 'File content is empty'
        },
        'entity-type-is-none': {
            'zh': '数据与Schema定义不匹配, 详情：实体类型缺失，实体数据：{}',
            'en': 'Data does not match the schema definition. Details: Missing entity_type, Entity data: {}'
        },
        'entity-type-undefined': {
            'zh': '数据与Schema定义不匹配, 详情：实体类型{}未在Schema中定义',
            'en': 'Data does not match the schema definition. Details: Entity type {} is not defined in Schema'
        },
        'edge-type-is-none': {
            'zh': '数据与Schema定义不匹配, 详情：边类型缺失，边数据：{}',
            'en': 'Data does not match the schema definition. Details: Missing edge_type, Edge data: {}'
        },
        'edge-type-undefined': {
            'zh': '数据与Schema定义不匹配, 详情：边类型{}未在Schema中定义',
            'en': 'Data does not match the schema definition. Details: Edge type {} is not defined in Schema'
        },
        'source-and-target-miss': {
            'zh': '数据与Schema定义不匹配, 详情：边数据中缺失source_id或target_id，边数据：{}',
            'en': 'Data does not match the schema definition. Details: Missing source_id or target_id in edge data: {}'
        },
        'property-undefined': {
            'zh': '数据与Schema定义不匹配, 详情：属性{}未在Schema中定义',
            'en': 'Data does not match the schema definition. Details: Property {} is not defined in Schema'
        },
        'database-operation-failed': {
            'zh': '数据库操作失败',
            'en': 'Database operation failed'
        },
        'network-error': {
            'zh': '网络连接异常',
            'en': 'Network connection error'
        },
        'system-error': {
            'zh': '系统错误',
            'en': 'System error'
        },
        'kb-not-exists': {
            'zh': '知识库不存在',
            'en': 'Knowledge base does not exist'
        },
        'sql-operation-not-allowed': {
            'zh': 'SQL写操作不被允许',
            'en': 'SQL write operations are not allowed'
        },
        'schema-not-exists': {
            'zh': 'Schema模版不存在',
            'en': 'Schema template does not exist'
        },
        'insufficient-storage-space': {
            'zh': '存储空间不足',
            'en': 'Insufficient storage space'
        },
        'query-type-not-supported': {
            'zh': '查询类型不支持',
            'en': 'Query type not supported'
        },
        'depth-exceeds-limit': {
            'zh': '查询深度超过限制',
            'en': 'Query depth exceeds limit'
        },
        'subgraph-depth-exceeds-limit': {
            'zh': '子图查询深度超过限制',
            'en': 'Subgraph query depth exceeds limit'
        },
        'entity-not-exists': {
            'zh': '实体不存在',
            'en': 'Entity does not exist'
        },
        'entity-id-required': {
            'zh': '实体ID不能为空',
            'en': 'Entity ID cannot be empty'
        },
        'query-timeout': {
            'zh': '查询超时',
            'en': 'Query timeout'
        },
        'invalid-entity-type': {
            'zh': '无效的实体类型',
            'en': 'Invalid entity type'
        },
        'task-not-found': {
            'zh': '任务不存在',
            'en': 'Task not found'
        },
        'schema-conflict': {
            'zh': 'Schema冲突：存在相同类型的实体或边',
            'en': 'Schema conflict: entities or edges of the same type already exist'
        },
        'permission-denied': {
            'zh': '权限不足',
            'en': 'Permission denied'
        },
        'graph-retrieve-failed': {
            'zh': '图检索失败',
            'en': 'Graph retrieve failed'
        },
        'graph-db-not-exists': {
            'zh': '图数据库不存在',
            'en': 'Graph database does not exist'
        },
        'schema-id-required': {
            'zh': 'Schema ID不能为空',
            'en': 'Schema ID cannot be empty'
        },
        'embedding-service-error': {
            'zh': 'Embedding服务调用失败',
            'en': 'Embedding service call failed'
        },
        'entity-id-format-invalid': {
            'zh': '实体ID格式不正确：必须以{}_开头，后面只能包含字母、数字或中划线，整个ID长度不超过100',
            'en': 'Invalid entity ID format: must start with {}_, followed by letters, numbers, or hyphens, total length not exceeding 100'
        },
        'entity-id-length-exceed': {
            'zh': '实体ID长度超过限制：当前长度为{}，最大长度为100',
            'en': 'Entity ID length exceeds limit: current length is {}, maximum length is 100'
        },
        'edge-id-format-invalid': {
            'zh': '边ID格式不正确：必须以{}_开头，后面只能包含字母、数字或中划线，整个ID长度不超过100',
            'en': 'Invalid edge ID format: must start with {}_, followed by letters, numbers, or hyphens, total length not exceeding 100'
        },
        'edge-id-length-exceed': {
            'zh': '边ID长度超过限制：当前长度为{}，最大长度为100',
            'en': 'Edge ID length exceeds limit: current length is {}, maximum length is 100'
        },
        'edge-source-node-type-invalid': {
            'zh': '数据与Schema定义不匹配, 详情：关系类型{}的起始节点ID格式无效，节点ID：{}，期望的节点类型：{}',
            'en': 'Data does not match the schema definition. Details: Invalid source node ID format for edge type {}, node ID: {}, expected node type: {}'
        },
        'edge-source-node-type-mismatch': {
            'zh': '数据与Schema定义不匹配, 详情：关系类型{}的起始节点类型{}与Schema中定义的类型{}不一致',
            'en': 'Data does not match the schema definition. Details: Source node type {} for edge type {} does not match the defined type {} in Schema'
        },
        'edge-source-node-type-undefined': {
            'zh': '数据与Schema定义不匹配, 详情：关系类型{}的起始节点类型{}未在Schema中定义',
            'en': 'Data does not match the schema definition. Details: Source node type {} for edge type {} is not defined in Schema'
        },
        'edge-target-node-type-invalid': {
            'zh': '数据与Schema定义不匹配, 详情：关系类型{}的终止节点ID格式无效，节点ID：{}，期望的节点类型：{}',
            'en': 'Data does not match the schema definition. Details: Invalid target node ID format for edge type {}, node ID: {}, expected node type: {}'
        },
        'edge-target-node-type-mismatch': {
            'zh': '数据与Schema定义不匹配, 详情：关系类型{}的终止节点类型{}与Schema中定义的类型{}不一致',
            'en': 'Data does not match the schema definition. Details: Target node type {} for edge type {} does not match the defined type {} in Schema'
        },
        'edge-target-node-type-undefined': {
            'zh': '数据与Schema定义不匹配, 详情：关系类型{}的终止节点类型{}未在Schema中定义',
            'en': 'Data does not match the schema definition. Details: Target node type {} for edge type {} is not defined in Schema'
        },
        'edge-node-type-pair-mismatch': {
            'zh': '数据与Schema定义不匹配, 详情：关系类型{}的起始节点类型{}与终止节点类型{}的组合未在Schema中定义',
            'en': 'Data does not match the schema definition. Details: Edge type {} with source entity {} and target entity {} is not defined in Schema'
        }
    }

    # 使用get_errcode()方法获取错误码
    error_code = exception.get_errcode()
    error_args = exception.get_args()

    if error_code in error_messages:
        error_message = error_messages[error_code].get(language, error_messages[error_code]['en'])
        return error_message.format(*error_args) if error_args else error_message

    # 默认错误消息
    default_messages = {
        'zh': '操作失败',
        'en': 'Operation failed'
    }
    return default_messages.get(language, default_messages['en'])


# ---------------------------------------------------------------------------
# 进程内入口（编排用）
# ---------------------------------------------------------------------------


def retrieve_result(retrieve_dto: GraphRetrieveDto,
                    http_headers: Optional[EMRequestHeaders] = None) -> Any:
    """图谱检索的**唯一实现**：HTTP 路由与进程内调用都走它。

    :param retrieve_dto: 已绑定的入参（HTTP 侧由 FastAPI 绑定；进程内侧由
        :func:`retrieve_result_from_payload` 绑定）
    :param http_headers: 请求头对象；语言由它决定（缺省时 `httputil` 会回落 'en'）
    :return: 检索结果对象本身（原 ``{code,message,data}`` 里的 ``data``）
    :raises GraphRetrieveError: 检索失败；调用方按 :class:`ProblemSpec` 出响应
    """
    http_headers = http_headers if http_headers is not None else httputil.build_http_headers({})
    language = http_headers.get_language_option()
    started = time.perf_counter()
    log.info('[graph-retrieve][gateway] start bases=%s seed_k=%s depth=%s '
             'query_len=%s', retrieve_dto.bases, retrieve_dto.seed_k, retrieve_dto.depth,
             len(retrieve_dto.query or ''))
    try:
        graph_query_service = GraphQueryService()
        result = graph_query_service.retrieve_graph(retrieve_dto, http_headers)
        log.info('[graph-retrieve][gateway] done ok=True bases=%s elapsed=%.3fs',
                 retrieve_dto.bases, time.perf_counter() - started)
        return result
    except GraphRetrieveError:
        raise
    except EMException as e:
        log.warning('[graph-retrieve][gateway] business failure bases=%s error=%s '
                    'elapsed=%.3fs', retrieve_dto.bases, e.get_errcode(),
                    time.perf_counter() - started)
        raise GraphRetrieveError(
            graph_problem_spec(e.get_errcode()), graph_error_message(e, language)) from e
    except Exception as e:
        log.exception('[graph-retrieve][gateway] unexpected failure bases=%s elapsed=%.3fs',
                      retrieve_dto.bases, time.perf_counter() - started)
        raise GraphRetrieveError(
            INTERNAL_ERROR, generic_detail(INTERNAL_ERROR, language)) from e


def retrieve_result_from_payload(payload: dict,
                                 headers: Optional[dict] = None) -> dict:
    """进程内调用入口：从**原始报文形状**的 dict 走一遍与 HTTP 完全相同的绑定。

    :param payload: 请求体（与 HTTP 侧同形）
    :param headers: 原始请求头 dict（可为 None）；经 `httputil.build_http_headers`
        解出语言等字段 —— 与 HTTP 侧同一个解析器，所以**语言码的来源也一致**。
    :raises pydantic.ValidationError: 入参不符合契约时**原样抛出**，由调用方映射 ——
        HTTP 侧这种情况是 FastAPI 的 422，进程内侧必须能区分出「协议级失败」，
        不能与「业务失败」混成同一种。
    """
    retrieve_dto = GraphRetrieveDto(**payload)
    return retrieve_result(retrieve_dto, httputil.build_http_headers(headers or {}))
