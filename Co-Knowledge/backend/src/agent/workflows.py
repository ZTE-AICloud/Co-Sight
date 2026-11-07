"""Agent 工作流查询（只读）。

工作流的**创建、画布编排、Embedding/LLM/检索参数调整都在控制台画布完成**；
Agent API 只提供列表查询，用来发现可用的工作流 ID（尤其是已发布、可被
``POST /query`` 使用的那些）。这样既不把管理面暴露给 API Key，也避免
「API 建出来的流参数不可调」的尴尬。

本模块不依赖 FastAPI；存储异常统一翻成 :class:`AgentApiError`，由 REST 层渲染成
``application/problem+json``。
"""

from __future__ import annotations

from typing import Optional

from infrastructure.logging.logutil import log

from agent.errors import AgentApiError
from workflow.errors import FlowError, FlowStoreError


def _service(flow_service=None):
    """取 FlowService：生产路径走进程内单例，测试可注入。"""
    if flow_service is not None:
        return flow_service
    from workflow.runtime import get_flow_service

    return get_flow_service()


def list_workflows(page: int, size: int, keyword: Optional[str],
                   publish_type: Optional[int], *, flow_service=None) -> dict:
    """分页列表；``publish_type`` 在 SQL 侧过滤，total 与当前页一致。"""
    service = _service(flow_service)
    return _call(lambda: service.page_workflows(page, size, keyword, publish_type))


def bound_kb_ids(workflow_id: str, *, flow_service=None) -> tuple[str, ...]:
    """已发布快照绑定的、**受 Key 白名单约束**的知识库标识（通常为 UUID）。

    读取的是**发布快照**而不是 ``flow_workflow.bound_info``：后者只在建流时写入，
    之后画布改绑不会更新；拿它做权限判断会漏放行。

    快照里库名形如 ``doc_<uuid>`` / ``graph_<uuid>`` / ``data_<uuid>``。
    - ``doc_``（文档）与 ``data_``（结构化）去掉前缀后可直接与 Key 的
      ``kbIds`` 比较；
    - ``graph_``（图谱）**跳过**：Agent Key 的白名单下拉只列文档库，图谱库
      无法被授权；运行含图谱检索的工作流由 ``workflow:run`` scope 显式授权。

    工作流未发布/不存在时会抛 ``AgentApiError(404, published_workflow_not_found)``
    —— 与 ``POST /query`` 的失败语义一致。
    """
    from workflow.canvas import collect_bound_kbase_names, strip_kb_prefix

    service = _service(flow_service)
    published = _call(lambda: service.get_published_flow_config(workflow_id, 'zh'))
    names = collect_bound_kbase_names(published.get('nodeConfigDTOList') or [])
    return tuple(strip_kb_prefix(name) for name in names
                 if name and not name.startswith('graph_'))


def _call(fn):
    """执行领域调用，把 FlowError / FlowStoreError 翻成 Agent 的错误语义。"""
    try:
        return fn()
    except FlowStoreError as error:
        log.error('agent workflow store error (%s): %s', error.kind, error.detail)
        raise AgentApiError(500, 'internal_error',
                            'Workflow store is unavailable') from error
    except FlowError as error:
        spec = error.problem_spec()
        # Agent API 的 detail 固定英文（见对外文档 §3.4），机器码才是稳定契约。
        raise AgentApiError(spec.status, spec.code,
                            error.problem_detail('en')) from error
