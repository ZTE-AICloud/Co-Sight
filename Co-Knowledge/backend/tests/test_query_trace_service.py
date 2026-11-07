"""`chat.trace_service` 的日期/时区/统计口径。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from chat import trace_service
from chat.trace_service import TraceQueryError

TZ = trace_service.TIMEZONE


def test_date_only_bounds_are_shanghai_days_with_exclusive_to():
    start = trace_service.parse_bound('2026-10-25', is_to=False)
    end = trace_service.parse_bound('2026-10-25', is_to=True)

    assert start == datetime(2026, 10, 25, tzinfo=TZ)
    assert end == datetime(2026, 10, 26, tzinfo=TZ)


def test_iso_bounds_keep_offsets_and_assume_shanghai_when_naive():
    with_offset = trace_service.parse_bound('2026-10-25T10:00:00+08:00', is_to=False)
    with_z = trace_service.parse_bound('2026-10-25T02:00:00Z', is_to=False)
    naive = trace_service.parse_bound('2026-10-25T10:00:00', is_to=False)

    assert with_offset.utcoffset() == timedelta(hours=8)
    assert with_z == with_offset
    assert naive == with_offset


def test_invalid_bounds_raise_trace_query_error():
    with pytest.raises(TraceQueryError):
        trace_service.parse_bound('2026-13-40', is_to=False)
    with pytest.raises(TraceQueryError):
        trace_service.parse_bound('not-a-date', is_to=False)


def test_list_range_rejects_reversed_bounds():
    # date-only 的 to 取次日 00:00；用 27 日对 25 日才是真正的反向
    with pytest.raises(TraceQueryError):
        trace_service._resolve_list_range('2026-10-27', '2026-10-25')


def test_stats_range_defaults_to_last_seven_days_and_caps_spans():
    to_value = '2026-10-25T00:00:00+08:00'
    from_dt, to_dt = trace_service._resolve_stats_range(None, to_value, 'day')
    assert to_dt - from_dt == timedelta(days=7)

    with pytest.raises(TraceQueryError):
        trace_service._resolve_stats_range('2025-01-01', '2026-10-25', 'day')
    with pytest.raises(TraceQueryError):
        trace_service._resolve_stats_range('2026-09-01', '2026-10-25', 'hour')


def test_stats_mapping_uses_ok_only_hit_rate_and_stage_counts():
    row = {
        'count': 10, 'ok_count': 8, 'error_count': 1, 'client_disconnect_count': 1,
        'ok_hit_count': 6, 'avg_hit_count': 3.456, 'avg_source_count': 2.0,
        'understanding_count': 8, 'understanding_p50': 1.234,
        'understanding_p95': 2.0, 'understanding_p99': 3.0,
        'retrieval_count': 8, 'retrieval_p50': 2.0, 'retrieval_p95': 3.0,
        'retrieval_p99': 4.0,
        'rerank_count': 8, 'rerank_p50': 5.0, 'rerank_p95': 6.0, 'rerank_p99': 7.0,
        'generate_count': 8, 'generate_p50': 8.0, 'generate_p95': 9.0,
        'generate_p99': 10.0,
        'first_token_count': 8, 'first_token_p50': 11.0, 'first_token_p95': 12.0,
        'first_token_p99': 13.0,
        'total_count': 8, 'total_p50': 14.0, 'total_p95': 15.0, 'total_p99': 16.0,
    }

    mapped = trace_service._stats_to_camel(row)

    assert mapped['hitRate'] == 0.75
    assert mapped['avgHitCount'] == 3.46
    assert mapped['understanding'] == {
        'count': 8, 'p50': 1.2, 'p95': 2.0, 'p99': 3.0}
    assert mapped['firstToken']['p50'] == 11.0
    assert mapped['total']['p99'] == 16.0


def test_stats_mapping_hit_rate_is_none_without_ok_rows():
    mapped = trace_service._stats_to_camel({
        'count': 1, 'ok_count': 0, 'error_count': 1,
        'client_disconnect_count': 0, 'ok_hit_count': 0,
    })
    assert mapped['hitRate'] is None


def test_trace_mapping_and_filter_validation():
    row = {
        'id': 1, 'trace_id': 't', 'conversation_id': 'd', 'workflow_id': 'w',
        'org_id': '', 'is_stream': True, 'status': 'ok', 'error_code': '',
        'http_status': 200, 'error_status': None, 'question_len': 3,
        'answer_len': 8, 'understanding_ms': 1.0, 'retrieval_ms': None,
        'rerank_ms': None, 'generate_ms': None, 'first_token_ms': None,
        'total_ms': 2.0, 'hit_count': 5, 'source_count': 3, 'kb_count': 1,
        'top_score': None, 'created_at': datetime(2026, 10, 25, tzinfo=timezone.utc),
    }
    mapped = trace_service.trace_to_camel(row)
    assert mapped['traceId'] == 't'
    assert mapped['httpStatus'] == 200
    assert mapped['errorStatus'] is None

    with pytest.raises(TraceQueryError):
        trace_service._validate_filters('x' * 129, None, None, None, None)
    with pytest.raises(TraceQueryError):
        trace_service._validate_filters(None, None, None, None, 'weird')
