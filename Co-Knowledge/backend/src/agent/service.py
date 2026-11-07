"""REST 与 MCP 共用的门面：作用域检查、调用领域逻辑、审计。

审计只写 ``LOG_DIR`` 下的应用日志（与 RKB 其余模块一致，不进 ``docker logs``）。
默认**不记录原始 query**，只记长度；``RKB_AGENT_LOG_QUERY=true`` 时才记录，
排查完记得关掉。
"""

from __future__ import annotations

import time
from typing import Optional

from infrastructure.logging.logutil import log

from agent import answer as answer_mod
from agent import config, knowledge
from agent import search as search_mod
from agent import workflows as workflows_mod
from agent.auth import AgentPrincipal, require_scope
from agent.errors import AgentApiError
from agent.schemas import AnswerRequest, SearchRequest

SURFACE_REST = 'rest'
SURFACE_MCP = 'mcp'


def _audit(surface: str, operation: str, principal: AgentPrincipal, trace_id: str,
           started: float, status: str, query: Optional[str] = None, **fields) -> None:
    elapsed_ms = int((time.monotonic() - started) * 1000)
    parts = [
        f'agent_api surface={surface}',
        f'op={operation}',
        f'key={principal.key_prefix}',
        f'key_name={principal.name}',
        f'trace={trace_id}',
        f'status={status}',
        f'latency_ms={elapsed_ms}',
    ]
    parts.extend(f'{key}={value}' for key, value in fields.items() if value is not None)
    if query is not None:
        if config.log_query():
            parts.append(f'query={query!r}')
        else:
            parts.append(f'query_len={len(query)}')
    log.info(' '.join(parts))


def list_knowledge_bases(principal: AgentPrincipal, trace_id: str,
                         surface: str = SURFACE_REST) -> list[dict]:
    started = time.monotonic()
    status = 'ok'
    try:
        require_scope(principal, 'kb:list')
        rows = knowledge.list_knowledge_bases(principal)
        return rows
    except AgentApiError as error:
        status = error.code
        raise
    except Exception:
        status = 'internal_error'
        log.exception('agent api list knowledge bases failed trace=%s', trace_id)
        raise
    finally:
        _audit(surface, 'list_knowledge_bases', principal, trace_id, started, status)


def get_knowledge_base(principal: AgentPrincipal, kb_id: str, trace_id: str,
                       surface: str = SURFACE_REST) -> dict:
    started = time.monotonic()
    status = 'ok'
    try:
        require_scope(principal, 'kb:list')
        rows, _explicit = knowledge.resolve_kbases(principal, [kb_id])
        return knowledge.to_info(rows[0])
    except AgentApiError as error:
        status = error.code
        raise
    except Exception:
        status = 'internal_error'
        log.exception('agent api get knowledge base failed trace=%s kb=%s', trace_id, kb_id)
        raise
    finally:
        _audit(surface, 'get_knowledge_base', principal, trace_id, started, status,
               kb_ids=[kb_id])


def search(principal: AgentPrincipal, request: SearchRequest, trace_id: str,
           surface: str = SURFACE_REST) -> dict:
    started = time.monotonic()
    status = 'ok'
    data = None
    try:
        require_scope(principal, 'kb:search')
        data = search_mod.search(principal, request)
        return data
    except AgentApiError as error:
        status = error.code
        raise
    except Exception:
        status = 'internal_error'
        log.exception('agent api search failed trace=%s', trace_id)
        raise
    finally:
        _audit(surface, 'search', principal, trace_id, started, status,
               query=request.query, top_k=request.top_k, mode=request.mode,
               results=len(data.get('results') or []) if data else None,
               degraded=data.get('degraded') if data else None,
               **_parse_kb_fields(request.knowledge_base_ids))


def answer(principal: AgentPrincipal, request: AnswerRequest, trace_id: str,
           surface: str = SURFACE_REST) -> dict:
    started = time.monotonic()
    status = 'ok'
    data = None
    try:
        require_scope(principal, 'kb:answer')
        data = answer_mod.answer(principal, request)
        return data
    except AgentApiError as error:
        status = error.code
        raise
    except Exception:
        status = 'internal_error'
        log.exception('agent api answer failed trace=%s', trace_id)
        raise
    finally:
        _audit(surface, 'answer', principal, trace_id, started, status,
               query=request.question, top_k=request.top_k, mode=request.mode,
               citations=len(data.get('citations') or []) if data else None,
               no_results=data.get('no_results') if data else None,
               **_parse_kb_fields(request.knowledge_base_ids))


def list_workflows(principal: AgentPrincipal, page: int, size: int,
                   keyword: Optional[str], publish_type: Optional[int],
                   trace_id: str, surface: str = SURFACE_REST) -> dict:
    started = time.monotonic()
    status = 'ok'
    data = None
    try:
        require_scope(principal, 'workflow:read')
        data = workflows_mod.list_workflows(page, size, keyword, publish_type)
        return data
    except AgentApiError as error:
        status = error.code
        raise
    except Exception:
        status = 'internal_error'
        log.exception('agent api list workflows failed trace=%s', trace_id)
        raise
    finally:
        _audit(surface, 'list_workflows', principal, trace_id, started, status,
               keyword=keyword, publish_type=publish_type,
               total=data.get('total') if data else None)


def _parse_kb_fields(kb_ids: Optional[list[str]]) -> dict:
    """把 ``_kb_fields`` 的字符串拆成两个审计字段（避免 ** 展开嵌套）。"""
    if not kb_ids:
        return {'kb_count': 'all'}
    preview = ','.join(kb_ids[:5])
    if len(kb_ids) > 5:
        preview += ',...'
    return {'kb_count': len(kb_ids), 'kb_ids': preview}
