"""``POST /query`` 的业务错误 → RFC 9457 问题规格。

编排内部的 ``RagException`` 只有数字码 + i18n tag；对外契约需要稳定的 HTTP 状态码
和 snake_case 机器码。这里集中做映射，路由与流式生成器共用同一份 —— 否则
「未进入流式」和「流中途失败」会给出两套不一致的错误。
"""
from __future__ import annotations

from shared.problem import (INTERNAL_ERROR, ProblemSpec, generic_detail,
                            title_for)
from engine import i18n

#: tag → (HTTP 状态, 机器码)。逐键显式；未知 tag 一律 500 internal_error。
_TAG_SPECS: dict[str, tuple[int, str]] = {
    # ---- 入参 ----------------------------------------------------------
    'required_param_missing': (422, 'validation_failed'),
    'parameter_length_limit_illegal': (422, 'validation_failed'),
    'question_length_over_limit': (422, 'validation_failed'),
    'question_not_match_desc_info': (422, 'question_not_match_desc_info'),
    'only-support-sequential-hybrid': (422, 'only_support_sequential_hybrid'),
    'web-search-not-supported': (422, 'web_search_not_supported'),
    # ---- 工作流 --------------------------------------------------------
    'published-workflow-not-found': (404, 'published_workflow_not_found'),
    'workflow-has-no-operator': (422, 'workflow_has_no_operator'),
    'workflow-config-invalid': (500, 'workflow_config_invalid'),
    # ---- 依赖不可用 ----------------------------------------------------
    'knowledgebase-not-imported': (503, 'knowledge_base_not_imported'),
    'no-llm-available': (503, 'no_llm_available'),
    'rerank-endpoint-not-configured': (503, 'rerank_endpoint_not_configured'),
    'rerank-model-not-configured': (503, 'rerank_model_not_configured'),
    # ---- 上游失败 ------------------------------------------------------
    'request-knowledgebase-failed': (502, 'knowledge_base_unavailable'),
    'request-knowledge-graph-failed': (502, 'knowledge_graph_unavailable'),
    'request-llm-failed': (502, 'llm_unavailable'),
    'request-llm-gateway-failed': (502, 'llm_gateway_unavailable'),
    'request-model-gateway-failed': (502, 'model_gateway_unavailable'),
    'bad-status-code': (502, 'upstream_unavailable'),
    'llm-empty-content': (502, 'llm_empty_content'),
    'llm-empty-content-truncated': (502, 'llm_empty_content_truncated'),
}


def query_problem(tag: str, args: tuple, language: str) -> tuple[ProblemSpec, str]:
    """``RagException`` → ``(ProblemSpec, 本地化 detail)``。"""

    status, code = _TAG_SPECS.get(tag, (INTERNAL_ERROR.status, INTERNAL_ERROR.code))
    spec = ProblemSpec(status, code, title_for(code))
    detail = i18n.get_i18n_safe(language, tag, *args)
    return spec, detail or generic_detail(spec, language)
