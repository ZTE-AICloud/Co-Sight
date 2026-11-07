"""Composition root for the RKB HTTP surface.

Domain modules own their routes:

* :mod:`system.api` — health and deployment capability information
* :mod:`knowledge_base.api` — knowledge-base metadata and nested content
* :mod:`retrieval.api` — the retrieval endpoint
* :mod:`operators.api` — operator registry
* :mod:`graph.api` — graph schemas, extraction, import and content

This module only wires them together in the historical registration order
(route order is part of the OpenAPI contract) and keeps the catch-all last.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.prefixes import RKB_PREFIX
from shared.errors.api import KbApiError
from infrastructure.logging.logutil import log

from graph import api as graph_api
from graph.service import lifecycle as graph_lifecycle
from knowledge_base import api as knowledge_base_api
from knowledge_base import graph_bridge
from knowledge_base.service import kbase_service, kbase_v2_service
from retrieval.repository.kbase_lookup import set_kbase_row_provider
from workflow.bindings import workflow_ids_binding
from infrastructure.http.rkb_support import (http_exception_handler,
                                              kb_error_handler, not_found,
                                              validation_handler)
from operators import api as operators_api
from retrieval import api as retrieval_api
from system import api as system_api

#: Single external prefix for the REST surface.
KBASE_PREFIX = RKB_PREFIX


def build_router() -> APIRouter:
    """Build the RKB router without a prefix.

    Registration order mirrors the pre-split router: system, KB collection,
    retrieval, KB content, operators, graph, then the catch-all.  FastAPI
    matches in registration order and the OpenAPI generator emits paths in the
    same order, so this sequence is part of the contract.
    """
    router = APIRouter()
    router.include_router(system_api.build_router())
    router.include_router(knowledge_base_api.build_router())
    router.include_router(retrieval_api.build_router())
    router.include_router(knowledge_base_api.build_content_router())
    router.include_router(operators_api.build_router())
    router.include_router(graph_api.build_router())

    # Unknown paths under the prefix keep the historical problem response.
    # This route must remain last: it would otherwise swallow every later
    # registration under the same prefix.
    @router.api_route('/{unknown_path:path}',
                      methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'],
                      include_in_schema=False)
    async def kb_api_catch_all(request: Request, unknown_path: str):
        log.warning('kb api unknown path: %s %s', request.method, request.url.path)
        return not_found(request)

    return router


def register_rkb_api(app) -> None:
    """Mount the RKB router and its prefix-level exception handlers."""
    graph_bridge.install(graph_lifecycle)
    kbase_v2_service.set_workflow_binding_provider(workflow_ids_binding)
    set_kbase_row_provider(kbase_service.get_kbase_row)
    app.include_router(build_router(), prefix=KBASE_PREFIX)
    app.add_exception_handler(RequestValidationError, validation_handler)
    # These two handle exceptions that escape a route function; in-route
    # failures are already converted by ``dispatch_sync``'s ladder.
    app.add_exception_handler(KbApiError, kb_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    log.info('Registered kb api under %s', KBASE_PREFIX)
