"""进程内调用面：编排层**不经过 HTTP** 直接调 RKB 的四条能力。

## 为什么是「返回 HTTP 形状」而不是直接返回业务对象

编排侧的 4 个客户端（``engine/gateways/knowledge_base_client.py`` 等）以
「状态码检查 → 抛 RagException」作为报文形状的契约，保持不变。所以这里的做法是
**只把字节换成对象**：

    HTTP 路径：requests.post(url, ...) -> Response
    进程内路径：rkb_inprocess.post_retrieve(body) -> InProcessResponse

响应形状与 HTTP 路径一致：成功是纯 payload，失败是真实状态码 +
RFC 9457 problem JSON（不是 `{code,bo,other}` 信封）。编排客户端只按状态码判成败。

## 与 HTTP 路径的已知差异（刻意保留，逐条登记）

* **超时**：HTTP 时代各调用点有 30s/60s，进程内没有超时；行为改为跟随
  RKB 自己的 DB/ES 连接参数（慢库不再被 30s 截断）。
* **语言**：HTTP 时代编排不带 `language-option` 头，`httputil.get_language_option`
  恒回落 `'en'`；这里同样传 `'en'`，保持错误文案与合并前一致。
* **绑定失败**：HTTP 时代入参不符合契约是 FastAPI 的 422；这里
  `retrieve_result_from_payload` **原样抛出 pydantic 的 ValidationError**，
  由编排的 transport 映射成同一条件（`bad-status-code`），不在这里吞掉。
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from workflow import runtime as flow_runtime
from workflow.errors import FlowError, FlowStoreError
from graph.service.graph_retrieve_gateway import (GraphRetrieveError,
                                           retrieve_result_from_payload)
from shared.errors.api import KbApiError
from knowledge_base.service import kbase_service
from retrieval.service import retrieve_service as retrieve_service
from shared.problem import (CONFLICT, INTERNAL_ERROR, NOT_FOUND,
                            PROBLEM_TYPE_PREFIX, ProblemSpec, generic_detail)
from infrastructure.logging.logutil import log

#: 编排的 HTTP 时代不带 language-option 头，RKB 侧解析结果恒为 'en'（见模块文档）
_DEFAULT_LANGUAGE = 'en'


class InProcessResponse:
    """`requests.Response` 的**最小替身**：只实现被用到的那两处。"""

    __slots__ = ('status_code', '_payload')

    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def __repr__(self) -> str:  # 便于日志里直接打
        return f'<InProcessResponse {self.status_code} {str(self._payload)[:120]}>'


def _problem(spec: ProblemSpec, detail: str | None = None) -> dict:
    return {
        'type': PROBLEM_TYPE_PREFIX + spec.code,
        'title': spec.title,
        'status': spec.status,
        'detail': detail or generic_detail(spec, _DEFAULT_LANGUAGE),
        'code': spec.code,
    }


def _api_error_response(error: Exception) -> InProcessResponse:
    """家族异常 → 真实状态码 + problem dict（与 HTTP 路径同形）。"""

    if isinstance(error, FlowStoreError):
        spec = {
            FlowStoreError.DUPLICATE: CONFLICT,
            FlowStoreError.NOT_FOUND: NOT_FOUND,
        }.get(error.kind, INTERNAL_ERROR)
        return InProcessResponse(spec.status, _problem(spec))
    spec = error.problem_spec() if hasattr(error, 'problem_spec') else INTERNAL_ERROR
    detail = (error.problem_detail(_DEFAULT_LANGUAGE)
              if hasattr(error, 'problem_detail') else None)
    return InProcessResponse(spec.status, _problem(spec, detail))


# ---------------------------------------------------------------------------
# 1) 检索：编排 invoke_knowledge_base_client 的目标
# ---------------------------------------------------------------------------


def post_retrieve(body: dict) -> InProcessResponse:
    """对应 `POST <prefix>/retrieval`。成功返回 `SearchResult[]`。"""

    try:
        results = retrieve_service.retrieve(body)
    except KbApiError as error:
        log.warning('in-process retrieve rejected: %s', error)
        return _api_error_response(error)
    except Exception:
        log.exception('in-process retrieve failed')
        return InProcessResponse(500, _problem(INTERNAL_ERROR))
    return InProcessResponse(200, results)


# ---------------------------------------------------------------------------
# 2) 知识库列表：编排 invoke_list_vector_knowledge_bases 的目标
# ---------------------------------------------------------------------------


def get_kbase_list() -> InProcessResponse:
    """对应 `GET <prefix>/knowledge-bases`。

    ⚠️ **不设 tableName 是现存行为**（见 `kbase_service.list_authority_kbases`
    的文档）：编排因此恒抛 `knowledgebase-not-imported`。合并前后完全一致，
    不在这里「修好」。
    """

    try:
        rows = kbase_service.list_authority_kbases(None)
    except KbApiError as error:
        log.warning('in-process kbase list rejected: %s', error)
        return _api_error_response(error)
    except Exception:
        log.exception('in-process kbase list failed')
        return InProcessResponse(500, _problem(INTERNAL_ERROR))
    return InProcessResponse(200, rows)


# ---------------------------------------------------------------------------
# 3) 图谱检索：编排 invoke_knowledge_graph_client 的目标
# ---------------------------------------------------------------------------


def post_graph_retrieve(body: dict, headers: dict | None = None) -> InProcessResponse:
    """对应 `POST <prefix>/retrieval/graph`。

    成功返回检索结果对象本身（与 HTTP 路径同一形状）；失败返回真实状态码 +
    problem dict（不再有裸 ``code``）。

    入参不符合契约时抛 `pydantic.ValidationError`（HTTP 时代是 422）——
    **不吞**，交由 transport 映射。
    """

    try:
        payload = retrieve_result_from_payload(body, headers)
    except ValidationError:
        # 绑定失败必须原样抛出（对应 HTTP 侧 422），不能折成 500。
        raise
    except GraphRetrieveError as error:
        return InProcessResponse(error.spec.status,
                                 _problem(error.spec, error.detail))
    except Exception:
        log.exception('in-process graph retrieve failed')
        return InProcessResponse(500, _problem(INTERNAL_ERROR))
    return InProcessResponse(200, payload)


# ---------------------------------------------------------------------------
# 4) 画布配置：编排 flow_config_provider 的目标
# ---------------------------------------------------------------------------


def get_flow_config(app_id: str, scope: str = '') -> InProcessResponse:
    """对应 `GET <prefix>/workflows/{id}/flow` 与 `/publication`。

    `scope` 语义与编排侧一致：只有 `'dev'` 读草稿，其余读最新发布快照。
    没有发布过 → 404 `published_workflow_not_found`；编排侧把它映射成
    `published-workflow-not-found`（与合并前同一个键）。
    """

    service = flow_runtime.get_flow_service()
    try:
        if scope == 'dev':
            canvas = service.get_flow_config(app_id, _DEFAULT_LANGUAGE)
        else:
            canvas = service.get_published_flow_config(app_id, _DEFAULT_LANGUAGE)
    except (FlowError, FlowStoreError) as error:
        log.warning('in-process flow config unavailable for %s: %s', app_id, error)
        return _api_error_response(error)
    except Exception:
        log.exception('in-process flow config failed for %s', app_id)
        return InProcessResponse(500, _problem(INTERNAL_ERROR))
    return InProcessResponse(200, canvas)
