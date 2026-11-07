"""`/query-traces` 只读 API：列表 / 单条 / 聚合统计。

路由挂载在 `chat.router.register_query_api` 里，和 `/query` 同前缀、同在 kb_api
兜底路由之前注册。只暴露指标，不含问题/答案/证据正文；默认部署无鉴权，与其它 UI API
一致。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from chat import trace_service
from chat.trace_errors import QueryTraceStoreUnavailable
from engine.common.beans.rag_request_headers import RagRequestHeaders
from infrastructure.http.pagination import page
from shared.problem import (
    QUERY_TRACE_NOT_FOUND,
    QUERY_TRACE_STORE_UNAVAILABLE,
    VALIDATION_FAILED,
    generic_detail,
    problem_response,
)

router = APIRouter()

TraceStatus = Literal['ok', 'error', 'client_disconnect']
Bucket = Literal['hour', 'day']


class QueryTraceItem(BaseModel):
    id: int
    traceId: str
    conversationId: str
    workflowId: str
    orgId: str
    isStream: bool
    status: str
    errorCode: str
    httpStatus: Optional[int] = None
    errorStatus: Optional[int] = None
    questionLen: int
    answerLen: int
    understandingMs: Optional[float] = None
    retrievalMs: Optional[float] = None
    rerankMs: Optional[float] = None
    generateMs: Optional[float] = None
    firstTokenMs: Optional[float] = None
    totalMs: Optional[float] = None
    hitCount: int
    sourceCount: int
    kbCount: int
    topScore: Optional[float] = None
    createdAt: datetime


class QueryTracePage(BaseModel):
    items: List[QueryTraceItem]
    total: int
    page: int
    pageSize: int


class StageStats(BaseModel):
    count: int
    p50: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None


class TraceSummary(BaseModel):
    count: int
    okCount: int
    errorCount: int
    clientDisconnectCount: int
    hitRate: Optional[float] = None
    avgHitCount: Optional[float] = None
    avgSourceCount: Optional[float] = None
    understanding: StageStats
    retrieval: StageStats
    rerank: StageStats
    generate: StageStats
    firstToken: StageStats
    total: StageStats


class TraceBucket(TraceSummary):
    bucket: datetime


class QueryTraceStats(BaseModel):
    summary: TraceSummary
    series: List[TraceBucket]


def _language(request: Request) -> str:
    return RagRequestHeaders.build_rag_request_header(request.headers).language_option


def _validation_problem(request: Request, detail: str):
    return problem_response(VALIDATION_FAILED, detail, instance=request.url.path)


def _store_problem(request: Request):
    return problem_response(
        QUERY_TRACE_STORE_UNAVAILABLE,
        generic_detail(QUERY_TRACE_STORE_UNAVAILABLE, _language(request)),
        instance=request.url.path)


@router.get('/query-traces', response_model=QueryTracePage,
            summary='List query traces')
def query_traces_list(
        request: Request,
        workflow_id: Optional[str] = Query(None, alias='workflowId', max_length=128),
        conversation_id: Optional[str] = Query(None, alias='conversationId', max_length=128),
        trace_id: Optional[str] = Query(None, alias='traceId', max_length=64),
        org_id: Optional[str] = Query(None, alias='orgId', max_length=128),
        status: Optional[TraceStatus] = Query(None),
        from_value: Optional[str] = Query(None, alias='from'),
        to_value: Optional[str] = Query(None, alias='to'),
        page_no: int = Query(1, alias='page', ge=1),
        size: int = Query(20, ge=1, le=trace_service.MAX_PAGE_SIZE),
):
    try:
        items, total = trace_service.list_traces(
            workflow_id=workflow_id, conversation_id=conversation_id, trace_id=trace_id,
            org_id=org_id, status=status, from_value=from_value, to_value=to_value,
            page=page_no, size=size)
    except trace_service.TraceQueryError as error:
        return _validation_problem(request, str(error))
    except QueryTraceStoreUnavailable:
        return _store_problem(request)
    return page(items, total, page_no, size)


@router.get('/query-traces/stats', response_model=QueryTraceStats,
            summary='Aggregate query trace latency and hit rate')
def query_traces_stats(
        request: Request,
        workflow_id: Optional[str] = Query(None, alias='workflowId', max_length=128),
        org_id: Optional[str] = Query(None, alias='orgId', max_length=128),
        from_value: Optional[str] = Query(None, alias='from'),
        to_value: Optional[str] = Query(None, alias='to'),
        bucket: Bucket = Query('day'),
):
    try:
        return trace_service.stats(
            workflow_id=workflow_id, org_id=org_id, from_value=from_value,
            to_value=to_value, bucket=bucket)
    except trace_service.TraceQueryError as error:
        return _validation_problem(request, str(error))
    except QueryTraceStoreUnavailable:
        return _store_problem(request)


@router.get('/query-traces/{trace_row_id}', response_model=QueryTraceItem,
            summary='Get one query trace')
def query_traces_detail(trace_row_id: int, request: Request):
    try:
        item = trace_service.get_trace(trace_row_id)
    except QueryTraceStoreUnavailable:
        return _store_problem(request)
    if item is None:
        return problem_response(
            QUERY_TRACE_NOT_FOUND,
            generic_detail(QUERY_TRACE_NOT_FOUND, _language(request)),
            instance=request.url.path)
    return item
