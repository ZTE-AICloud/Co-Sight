"""`chat_query_trace` 读接口的业务层：日期/时区/过滤/分页口径。

API 路由只做参数声明与 problem 映射；所有可测的语义都在这里：
* date-only 边界按 **Asia/Shanghai** 解释，`to` 为开区间；
* 统计默认最近 7 天，day 最多 366 天、hour 最多 31 天；
* 延迟/命中率只统计 `status='ok'`（错误行通常很快，会把 P50 拉低）；
* 每个阶段返回样本数，调用方不会误读「P50 是 40 条还是 2 条算出来的」。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from chat import repository_pg, schema

TIMEZONE = ZoneInfo(repository_pg.TIMEZONE)
DEFAULT_STATS_SPAN = timedelta(days=7)
MAX_DAY_SPAN = timedelta(days=366)
MAX_HOUR_SPAN = timedelta(days=31)
MAX_PAGE_SIZE = 200
MAX_FILTER_LENGTH = {
    'workflow_id': 128,
    'conversation_id': 128,
    'trace_id': 64,
    'org_id': 128,
}

_STAGE_ALIASES = (
    ('understanding', 'understanding'),
    ('retrieval', 'retrieval'),
    ('rerank', 'rerank'),
    ('generate', 'generate'),
    ('first_token', 'firstToken'),
    ('total', 'total'),
)


class TraceQueryError(ValueError):
    """语义校验失败（日期反了、跨度太大、过滤值超长）→ API 422。"""


def parse_bound(value: Optional[str], *, is_to: bool) -> Optional[datetime]:
    """解析 `YYYY-MM-DD` / ISO-8601；date-only 的 `to` 取次日 00:00（开区间）。"""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) == 10:
        try:
            day = date.fromisoformat(text)
        except ValueError as error:
            raise TraceQueryError(f'invalid date: {value!r}') from error
        result = datetime.combine(day, time.min, tzinfo=TIMEZONE)
        return result + timedelta(days=1) if is_to else result
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise TraceQueryError(f'invalid datetime: {value!r}') from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)
    return parsed


def _resolve_list_range(from_value: Optional[str],
                        to_value: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    from_dt = parse_bound(from_value, is_to=False)
    to_dt = parse_bound(to_value, is_to=True)
    if from_dt is not None and to_dt is not None and from_dt > to_dt:
        raise TraceQueryError('from must be earlier than or equal to to')
    return from_dt, to_dt


def _resolve_stats_range(from_value: Optional[str], to_value: Optional[str],
                         bucket: str) -> Tuple[datetime, datetime]:
    to_dt = parse_bound(to_value, is_to=True)
    from_dt = parse_bound(from_value, is_to=False)
    now = datetime.now(TIMEZONE)
    if to_dt is None:
        to_dt = now
    if from_dt is None:
        from_dt = to_dt - DEFAULT_STATS_SPAN
    if from_dt > to_dt:
        raise TraceQueryError('from must be earlier than or equal to to')
    max_span = MAX_HOUR_SPAN if bucket == 'hour' else MAX_DAY_SPAN
    if to_dt - from_dt > max_span:
        raise TraceQueryError(
            f'{bucket} span must not exceed {max_span.days} days')
    return from_dt, to_dt


def _validate_filters(workflow_id: Optional[str], conversation_id: Optional[str],
                      trace_id: Optional[str], org_id: Optional[str],
                      status: Optional[str]) -> None:
    for name, value in (
        ('workflow_id', workflow_id),
        ('conversation_id', conversation_id),
        ('trace_id', trace_id),
        ('org_id', org_id),
    ):
        if value is not None and len(value) > MAX_FILTER_LENGTH[name]:
            raise TraceQueryError(f'{name} is too long')
    if status is not None and status not in schema.STATUS_VALUES:
        raise TraceQueryError(f'invalid status: {status!r}')


def _filters(workflow_id: Optional[str], conversation_id: Optional[str],
             trace_id: Optional[str], org_id: Optional[str],
             status: Optional[str],
             from_dt: Optional[datetime],
             to_dt: Optional[datetime]) -> Dict[str, Any]:
    return {
        'workflow_id': workflow_id,
        'conversation_id': conversation_id,
        'trace_id': trace_id,
        'org_id': org_id,
        'status': status,
        'from_dt': from_dt,
        'to_dt': to_dt,
    }


def _as_float(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def _round(value: Optional[float], digits: int) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _as_int(value: Any) -> int:
    return int(value) if value is not None else 0


def trace_to_camel(row: Mapping[str, Any]) -> Dict[str, Any]:
    """DB snake_case 行 → API camelCase（Pydantic 再负责 datetime/Decimal 序列化）。"""
    return {
        'id': int(row['id']),
        'traceId': row.get('trace_id') or '',
        'conversationId': row.get('conversation_id') or '',
        'workflowId': row.get('workflow_id') or '',
        'orgId': row.get('org_id') or '',
        'isStream': bool(row.get('is_stream')),
        'status': row.get('status') or '',
        'errorCode': row.get('error_code') or '',
        'httpStatus': _as_int(row.get('http_status')) if row.get('http_status') is not None else None,
        'errorStatus': _as_int(row.get('error_status')) if row.get('error_status') is not None else None,
        'questionLen': _as_int(row.get('question_len')),
        'answerLen': _as_int(row.get('answer_len')),
        'understandingMs': _as_float(row.get('understanding_ms')),
        'retrievalMs': _as_float(row.get('retrieval_ms')),
        'rerankMs': _as_float(row.get('rerank_ms')),
        'generateMs': _as_float(row.get('generate_ms')),
        'firstTokenMs': _as_float(row.get('first_token_ms')),
        'totalMs': _as_float(row.get('total_ms')),
        'hitCount': _as_int(row.get('hit_count')),
        'sourceCount': _as_int(row.get('source_count')),
        'kbCount': _as_int(row.get('kb_count')),
        'topScore': _as_float(row.get('top_score')),
        'createdAt': row.get('created_at'),
    }


def _stats_to_camel(row: Mapping[str, Any]) -> Dict[str, Any]:
    count = _as_int(row.get('count'))
    ok_count = _as_int(row.get('ok_count'))
    hit_positive = _as_int(row.get('ok_hit_count'))
    result: Dict[str, Any] = {
        'count': count,
        'okCount': ok_count,
        'errorCount': _as_int(row.get('error_count')),
        'clientDisconnectCount': _as_int(row.get('client_disconnect_count')),
        'hitRate': _round(hit_positive / ok_count, 4) if ok_count else None,
        'avgHitCount': _round(_as_float(row.get('avg_hit_count')), 2),
        'avgSourceCount': _round(_as_float(row.get('avg_source_count')), 2),
    }
    for key, alias in _STAGE_ALIASES:
        result[alias] = {
            'count': _as_int(row.get(f'{key}_count')),
            'p50': _round(_as_float(row.get(f'{key}_p50')), 1),
            'p95': _round(_as_float(row.get(f'{key}_p95')), 1),
            'p99': _round(_as_float(row.get(f'{key}_p99')), 1),
        }
    return result


def list_traces(*, workflow_id: Optional[str], conversation_id: Optional[str],
                trace_id: Optional[str], org_id: Optional[str],
                status: Optional[str], from_value: Optional[str],
                to_value: Optional[str], page: int,
                size: int) -> Tuple[List[Dict[str, Any]], int]:
    _validate_filters(workflow_id, conversation_id, trace_id, org_id, status)
    if page < 1:
        raise TraceQueryError('page must be >= 1')
    if size < 1 or size > MAX_PAGE_SIZE:
        raise TraceQueryError(f'size must be between 1 and {MAX_PAGE_SIZE}')
    from_dt, to_dt = _resolve_list_range(from_value, to_value)
    rows, total = repository_pg.list_query_traces(
        _filters(workflow_id, conversation_id, trace_id, org_id, status, from_dt, to_dt),
        page, size)
    return [trace_to_camel(row) for row in rows], total


def get_trace(trace_row_id: int) -> Optional[Dict[str, Any]]:
    row = repository_pg.get_query_trace(trace_row_id)
    return trace_to_camel(row) if row else None


def stats(*, workflow_id: Optional[str], org_id: Optional[str],
          from_value: Optional[str], to_value: Optional[str],
          bucket: str) -> Dict[str, Any]:
    _validate_filters(workflow_id, None, None, org_id, None)
    if bucket not in ('hour', 'day'):
        raise TraceQueryError(f'invalid bucket: {bucket!r}')
    from_dt, to_dt = _resolve_stats_range(from_value, to_value, bucket)
    raw = repository_pg.query_trace_stats(
        _filters(workflow_id, None, None, org_id, None, from_dt, to_dt), bucket)
    summary = _stats_to_camel(raw.get('summary') or {})
    series = []
    for row in raw.get('series') or []:
        item = _stats_to_camel(row)
        item['bucket'] = row.get('bucket')
        series.append(item)
    return {'summary': summary, 'series': series}
