from typing import Dict, Any

from engine.primitives.interfaces import RagQueryEngine

from engine.common.beans.rag_request import RagRequest
from engine.common.beans.rag_request_headers import RagRequestHeaders
from engine.context.rag_context import RagContext
from engine.query_engine.sequential_query_engine import SequentialQueryEngine
from engine.logutil import logger
from engine.rag_utils import instance_query_engine


def build_query_engine(user_request: RagRequest, request_headers: RagRequestHeaders,
                       workflow_config_provider=None) -> RagQueryEngine:
    rag_context = RagContext(user_request, request_headers, workflow_config_provider)
    query_engine_config: Dict[str, Any] = rag_context.query_engine
    package = query_engine_config.get('package', '')
    operator = query_engine_config.get('operator', '')
    logger.info('[query] engine=%s package=%s workflow=%s conversation_id=%s',
                operator, package, user_request.workflow_id, user_request.conversation_id)
    engine = instance_query_engine(package, operator, rag_context)
    logger.info('[query] engine instance=%s workflow=%s',
                type(engine).__name__, user_request.workflow_id)
    return engine
