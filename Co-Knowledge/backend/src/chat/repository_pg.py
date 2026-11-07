"""`chat_query_trace` 的读写（chat 域唯一持久化入口）。

写入是 **best-effort**：任何异常都只记 warning 并返回 False，绝不向调用方抛；
调用方是 `chat.trace_writer` 的单写线程。

读取（列表/详情/统计）失败统一收敛成 `QueryTraceStoreUnavailable`，由 API 映射为
503 problem，避免把 psycopg2 的 SQL 细节泄漏到响应里。
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from chat import schema
from chat.trace_errors import QueryTraceStoreUnavailable
from engine.logutil import logger
from infrastructure.db.rows import rows

#: 栈内统一时区（compose 的 TZ）；统计桶按它切日/小时。
TIMEZONE = 'Asia/Shanghai'

_STAGE_COLUMNS = (
    ('understanding_ms', 'understanding'),
    ('retrieval_ms', 'retrieval'),
    ('rerank_ms', 'rerank'),
    ('generate_ms', 'generate'),
    ('first_token_ms', 'first_token'),
    ('total_ms', 'total'),
)

_INSERT_SQL = (
    f'INSERT INTO {schema.TABLE} ({", ".join(schema.COLUMN_NAMES)}) '
    f'VALUES ({", ".join(["%s"] * len(schema.COLUMN_NAMES))})'
)

_SELECT_COLUMNS = ', '.join(('id', *schema.COLUMN_NAMES, 'created_at'))

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_SCHEMA_SKIP_UNTIL = 0.0
_SCHEMA_ERROR_LOGGED = False


# ── 值清洗 ─────────────────────────────────────────────────────────────
def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _ms(value: Any) -> Optional[float]:
    number = _finite(value)
    return round(number, 1) if number is not None and number >= 0 else None


def _score(value: Any) -> Optional[float]:
    number = _finite(value)
    return round(number, 4) if number is not None else None


def _count(value: Any) -> int:
    number = _finite(value)
    return max(0, int(number)) if number is not None else 0


def _http_status(value: Any) -> Optional[int]:
    number = _finite(value)
    if number is None:
        return None
    status = int(number)
    return status if 100 <= status <= 599 else None


def _clean_text(value: Any, max_length: int) -> str:
    """客户端可控字符串：去 NUL、替换非法代理字符，再按列宽截断。"""
    text = '' if value is None else str(value)
    text = text.replace('\x00', '')
    text = text.encode('utf-8', 'replace').decode('utf-8')
    return text[:max_length]


def _row_values(payload: Mapping[str, Any]) -> Tuple[Any, ...]:
    status = str(payload.get('status') or '')
    if status not in schema.STATUS_VALUES:
        status = schema.STATUS_ERROR
    values = (
        _clean_text(payload.get('trace_id'), 64),
        _clean_text(payload.get('conversation_id'), 128),
        _clean_text(payload.get('workflow_id'), 128),
        _clean_text(payload.get('org_id'), 128),
        bool(payload.get('is_stream')),
        status,
        _clean_text(payload.get('error_code'), 128),
        _http_status(payload.get('http_status')),
        _http_status(payload.get('error_status')),
        _count(payload.get('question_len')),
        _count(payload.get('answer_len')),
        _ms(payload.get('understanding_ms')),
        _ms(payload.get('retrieval_ms')),
        _ms(payload.get('rerank_ms')),
        _ms(payload.get('generate_ms')),
        _ms(payload.get('first_token_ms')),
        _ms(payload.get('total_ms')),
        _count(payload.get('hit_count')),
        _count(payload.get('source_count')),
        _count(payload.get('kb_count')),
        _score(payload.get('top_score')),
    )
    assert len(values) == len(schema.COLUMN_NAMES)
    return values


# ── 建表兜底 ───────────────────────────────────────────────────────────
def ensure_table(conn) -> bool:
    """表已存在就只置 ready；缺表才建。DDL 失败后 30s 内不再重试。"""
    global _SCHEMA_READY, _SCHEMA_SKIP_UNTIL, _SCHEMA_ERROR_LOGGED
    if _SCHEMA_READY:
        return True
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return True
        if time.monotonic() < _SCHEMA_SKIP_UNTIL:
            return False
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT to_regclass(%s)', (schema.TABLE,))
                row = cursor.fetchone()
                if row and row[0] is not None:
                    _SCHEMA_READY = True
                    return True
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SET LOCAL lock_timeout = '2s'")
                for statement in schema.SCHEMA_STATEMENTS:
                    cursor.execute(statement)
            # 先提交 DDL 再置 ready：否则后续 INSERT 失败会把建表一起回滚，
            # 进程内却仍以为表已存在，writer 会一直失败到重启。
            conn.commit()
            _SCHEMA_READY = True
            return True
        except Exception:                                       # noqa: BLE001
            _SCHEMA_SKIP_UNTIL = time.monotonic() + 30.0
            if not _SCHEMA_ERROR_LOGGED:
                _SCHEMA_ERROR_LOGGED = True
                logger.warning('[query-trace] ensure table failed; '
                               'will retry after 30s', exc_info=True)
            raise


def _reset_schema_for_tests() -> None:
    global _SCHEMA_READY, _SCHEMA_SKIP_UNTIL, _SCHEMA_ERROR_LOGGED
    with _SCHEMA_LOCK:
        _SCHEMA_READY = False
        _SCHEMA_SKIP_UNTIL = 0.0
        _SCHEMA_ERROR_LOGGED = False


# ── 写 ─────────────────────────────────────────────────────────────────
def persist_query_trace(payload: Mapping[str, Any]) -> bool:
    """写一行；任何失败只记 warning，返回 False。"""
    trace_id = _clean_text(payload.get('trace_id'), 64)
    try:
        values = _row_values(payload)
        from infrastructure.db.kb import connection
        with connection() as conn:
            if not ensure_table(conn):
                return False
            with conn.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '2s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute(_INSERT_SQL, values)
        return True
    except Exception:                                           # noqa: BLE001
        logger.warning('[query-trace] persist failed trace_id=%s',
                       trace_id, exc_info=True)
        return False


# ── 读 ─────────────────────────────────────────────────────────────────
def _build_where(filters: Mapping[str, Any]) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    for key, column in (
        ('workflow_id', 'workflow_id'),
        ('conversation_id', 'conversation_id'),
        ('trace_id', 'trace_id'),
        ('org_id', 'org_id'),
        ('status', 'status'),
    ):
        value = filters.get(key)
        if value:
            clauses.append(f'{column} = %s')
            params.append(value)
    if filters.get('from_dt') is not None:
        clauses.append('created_at >= %s')
        params.append(filters['from_dt'])
    if filters.get('to_dt') is not None:
        clauses.append('created_at < %s')
        params.append(filters['to_dt'])
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    return where, params


def _read_connection():
    from infrastructure.db.kb import connection
    return connection()


def _open_reader():
    return _read_connection()


def list_query_traces(filters: Mapping[str, Any], page_no: int,
                      page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    """分页列表；返回 snake_case 行 + total，业务层再映射 camelCase。"""
    where, params = _build_where(filters)
    offset = (page_no - 1) * page_size
    try:
        with _open_reader() as conn:
            with conn.cursor() as cursor:
                # 同一快照里取 total 与当前页，避免并发写入时 total 跳动
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                cursor.execute('SET LOCAL TIME ZONE %s', (TIMEZONE,))
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute(
                    f'SELECT count(*) FROM {schema.TABLE}{where}', params)
                total = int((cursor.fetchone() or [0])[0] or 0)
                cursor.execute(
                    f'SELECT {_SELECT_COLUMNS} FROM {schema.TABLE}{where} '
                    'ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s',
                    params + [page_size, offset])
                return rows(cursor), total
    except Exception as error:                                  # noqa: BLE001
        logger.warning('[query-trace] list failed', exc_info=True)
        raise QueryTraceStoreUnavailable('query trace store unavailable') from error


def get_query_trace(trace_row_id: int) -> Optional[Dict[str, Any]]:
    try:
        with _open_reader() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SET LOCAL TIME ZONE %s', (TIMEZONE,))
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute(
                    f'SELECT {_SELECT_COLUMNS} FROM {schema.TABLE} WHERE id = %s',
                    (trace_row_id,))
                result = rows(cursor)
                return result[0] if result else None
    except Exception as error:                                  # noqa: BLE001
        logger.warning('[query-trace] detail failed id=%s', trace_row_id, exc_info=True)
        raise QueryTraceStoreUnavailable('query trace store unavailable') from error


def _stats_select() -> str:
    parts = [
        'count(*) AS count',
        "count(*) FILTER (WHERE status = 'ok') AS ok_count",
        "count(*) FILTER (WHERE status = 'error') AS error_count",
        "count(*) FILTER (WHERE status = 'client_disconnect') AS client_disconnect_count",
        "count(*) FILTER (WHERE status = 'ok' AND hit_count > 0) AS ok_hit_count",
        "avg(hit_count) FILTER (WHERE status = 'ok') AS avg_hit_count",
        "avg(source_count) FILTER (WHERE status = 'ok') AS avg_source_count",
    ]
    for column, alias in _STAGE_COLUMNS:
        parts.append(
            f"count({column}) FILTER (WHERE status = 'ok') AS {alias}_count")
        for percentile, name in ((0.5, 'p50'), (0.95, 'p95'), (0.99, 'p99')):
            parts.append(
                f'percentile_cont({percentile}) WITHIN GROUP (ORDER BY {column}) '
                f"FILTER (WHERE status = 'ok') AS {alias}_{name}")
    return ', '.join(parts)


_STATS_SELECT = _stats_select()


def query_trace_stats(filters: Mapping[str, Any], bucket: str) -> Dict[str, Any]:
    """summary（整段）+ series（按 Asia/Shanghai 切桶）。

    延迟/命中率只统计 status='ok'；count/error/client_disconnect 统计所有行。
    """
    if bucket not in ('hour', 'day'):
        raise ValueError('bucket must be hour or day')
    where, params = _build_where(filters)
    bucket_expr = ('date_trunc(%s, created_at AT TIME ZONE %s) '
                   'AT TIME ZONE %s AS bucket')
    try:
        with _open_reader() as conn:
            with conn.cursor() as cursor:
                # summary 与 series 必须看同一快照，否则并发写入时 count 对不上
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                cursor.execute('SET LOCAL TIME ZONE %s', (TIMEZONE,))
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute(
                    f'SELECT {_STATS_SELECT} FROM {schema.TABLE}{where}', params)
                summary_row = cursor.fetchone()
                summary = dict(zip(
                    [description[0] for description in cursor.description],
                    summary_row)) if summary_row else {}
                cursor.execute(
                    f'SELECT {bucket_expr}, {_STATS_SELECT} FROM {schema.TABLE}'
                    f'{where} GROUP BY 1 ORDER BY 1 ASC',
                    [bucket, TIMEZONE, TIMEZONE] + params)
                series = rows(cursor)
        return {'summary': summary, 'series': series}
    except Exception as error:                                  # noqa: BLE001
        logger.warning('[query-trace] stats failed', exc_info=True)
        raise QueryTraceStoreUnavailable('query trace store unavailable') from error
