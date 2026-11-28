"""生成 SQL 的提取、只读校验与受限执行。

这里是 Text2SQL 的**安全边界**，不是「模型说安全就安全」：

* 结构判定交给 :mod:`text_to_sql.sql_ast`（PostgreSQL 官方语法树）：
  只允许单条 ``SELECT`` / ``WITH ... SELECT``，表/列/函数都走白名单；
* 外部连接使用只读事务 + ``statement_timeout``，结果最多取 ``max_rows + 1``
  （多取一条用于判断截断）、最多 ``max_bytes`` 字节；
* 结果只做 JSON 安全序列化，不把数据库游标或原始对象带到接口层。
"""

from __future__ import annotations

import base64
import datetime
import decimal
import json
import logging
import re
import time
from typing import Any, Callable, Iterable, Optional

import psycopg2
import psycopg2.errors
import psycopg2.extras

from knowledge_engine.policy import ExecutionPolicy, encode_rows
from text_to_sql import context_builder, sql_ast
from text_to_sql.errors import QueryExecutionError, SqlGuardError

log = logging.getLogger(__name__)

__all__ = ['SqlGuardError', 'QueryExecutionError', 'validate_sql',
           'extract_generated', 'execute_readonly', 'build_context',
           'MAX_SQL_LENGTH']

MAX_SQL_LENGTH = 20000
CONNECT_TIMEOUT_SECONDS = 8
APPLICATION_NAME = 'co-knowledge-text2sql-query'


# ---------------------------------------------------------------------------
# 从模型输出里取 SQL
# ---------------------------------------------------------------------------
def extract_generated(text: str) -> dict[str, Any]:
    """从 LLM 输出里提取 ``sql`` / ``explanation``。

    模型被要求只输出 JSON，但真实网关仍可能包 ```json 代码块或前后寒暄。
    先尝试第一个 JSON 对象；失败则把整段当成 SQL（仅在看起来像 SELECT/WITH 时）。
    """
    raw = (text or '').strip()
    if not raw:
        raise SqlGuardError('LLM_EMPTY_OUTPUT', '模型没有返回内容', 'llm')
    cleaned = _strip_code_fence(raw)
    payload = _first_json_object(cleaned)
    if isinstance(payload, dict):
        sql = payload.get('sql') or payload.get('SQL') or payload.get('query')
        if isinstance(sql, str) and sql.strip():
            return {
                'sql': sql.strip(),
                'explanation': str(payload.get('explanation')
                                   or payload.get('reason') or '').strip(),
                'tables': payload.get('tables') or payload.get('tables_used') or [],
                'confidence': payload.get('confidence'),
            }
    if re.match(r'^\s*(SELECT|WITH)\b', cleaned, re.IGNORECASE):
        return {'sql': cleaned, 'explanation': '', 'tables': [], 'confidence': None}
    raise SqlGuardError('LLM_INVALID_OUTPUT', '模型返回的内容不是 SQL', 'llm')


def extract_json_object(text: str) -> dict[str, Any]:
    """从模型输出里取第一个 JSON 对象（容忍代码块与前后寒暄）。

    AI 辅助（表/字段说明、选表、枚举释义）复用同一套容错解析。
    """
    raw = (text or '').strip()
    if not raw:
        raise SqlGuardError('LLM_EMPTY_OUTPUT', '模型没有返回内容', 'llm')
    payload = _first_json_object(_strip_code_fence(raw))
    if payload is None:
        raise SqlGuardError('LLM_INVALID_OUTPUT', '模型返回的内容不是 JSON 对象', 'llm')
    return payload


def _strip_code_fence(text: str) -> str:
    fence = re.match(r'^```(?:sql|json)?\s*(.*?)\s*```$', text, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else text


def _first_json_object(text: str) -> Optional[dict]:
    start = text.find('{')
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 只读校验
# ---------------------------------------------------------------------------
def validate_sql(sql: str, snapshot: dict[str, Any]) -> str:
    """校验并返回去掉尾分号的 SQL；失败抛 :class:`SqlGuardError`。

    结构判定交给 :mod:`text_to_sql.sql_ast`（PostgreSQL 语法树）；这里只做
    长度与去除尾分号这类与语法无关的预处理。
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SqlGuardError('SQL_EMPTY', 'SQL 不能为空')
    if len(sql) > MAX_SQL_LENGTH:
        raise SqlGuardError('SQL_TOO_LONG', f'SQL 超过 {MAX_SQL_LENGTH} 字符')
    normalized = sql.strip()
    if normalized.endswith(';'):
        normalized = normalized[:-1].rstrip()
    sql_ast.validate(normalized, snapshot)
    return normalized


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
def _notify_phase(callback: Optional[Callable[[str, Optional[int]], None]],
                  phase: str, ms: Optional[int] = None) -> None:
    """上报执行阶段起点：进度回调坏掉不能把只读查询带崩。"""
    if callback is None:
        return
    try:
        callback(phase, ms)
    except Exception:                                      # noqa: BLE001
        log.warning('text_to_sql phase callback failed at %s', phase,
                    exc_info=True)


def execute_readonly(connection: dict[str, Any], sql: str,
                     policy: dict[str, Any], snapshot: dict[str, Any],
                     on_phase: Optional[Callable[[str, Optional[int]], None]] = None
                     ) -> dict[str, Any]:
    """在只读事务里执行（已校验的）SQL；返回列/行/截断/执行计划/耗时。

    ``on_phase('explain', None)`` / ``on_phase('execute', explain_ms)`` 只用于
    上报两段执行的位置；回调异常不影响查询本身。
    """
    limits = ExecutionPolicy.from_mapping(policy)
    max_rows = limits.max_rows
    timeout_ms = limits.timeout_ms
    wrapped = f'SELECT * FROM ({sql}) AS t2s_sub LIMIT {max_rows + 1}'
    connect_options = '-c statement_timeout=%d' % timeout_ms
    schemas = snapshot.get('datasource', {}).get('includeSchemas') or ['public']
    if schemas:
        safe_schemas = ','.join('"%s"' % str(name).replace('"', '""')
                                for name in schemas)
        connect_options += ' -c search_path=%s' % safe_schemas
    started = time.perf_counter()
    explain_started = 0.0
    explain = None
    try:
        conn = psycopg2.connect(
            host=connection['host'], port=connection['port'],
            dbname=connection['database'], user=connection['username'],
            password=connection['password'],
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            application_name=APPLICATION_NAME,
            options=connect_options,
        )
    except psycopg2.Error as error:
        raise QueryExecutionError('DATASOURCE_UNAVAILABLE',
                                  _safe_error(error)) from error
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cursor:
            _notify_phase(on_phase, 'explain')
            explain_started = time.perf_counter()
            explain = _explain_plan(cursor, wrapped)
            explain_ms = int((time.perf_counter() - explain_started) * 1000)
            _notify_phase(on_phase, 'execute', explain_ms)
            execute_started = time.perf_counter()
            cursor.execute(wrapped)
            columns = [item[0] for item in (cursor.description or [])]
            raw_rows = cursor.fetchmany(max_rows + 1)
            execute_ms = int((time.perf_counter() - execute_started) * 1000)
        conn.rollback()
    except psycopg2.errors.QueryCanceled as error:
        raise QueryExecutionError('SQL_TIMEOUT', '查询超过时间限制') from error
    except psycopg2.errors.UndefinedColumn as error:
        raise QueryExecutionError('SQL_UNKNOWN_COLUMN', _safe_error(error)) from error
    except psycopg2.errors.UndefinedTable as error:
        raise QueryExecutionError('SQL_UNKNOWN_TABLE', _safe_error(error)) from error
    except psycopg2.errors.InsufficientPrivilege as error:
        raise QueryExecutionError('SQL_PERMISSION_DENIED', _safe_error(error)) from error
    except psycopg2.errors.SyntaxError as error:
        raise QueryExecutionError('SQL_SYNTAX', _safe_error(error)) from error
    except psycopg2.Error as error:
        raise QueryExecutionError('SQL_EXECUTION_FAILED', _safe_error(error)) from error
    finally:
        conn.close()
    rows, byte_truncated = encode_rows(raw_rows, limits, _jsonable_row)
    return {
        'columns': columns,
        'rows': rows,
        'row_count': len(rows),
        'truncated': len(raw_rows) > max_rows or byte_truncated,
        'byte_truncated': byte_truncated,
        'explain': explain,
        'explain_ms': explain_ms if explain is not None else 0,
        'execute_ms': execute_ms,
        'total_ms': int((time.perf_counter() - started) * 1000),
    }


def _jsonable_row(raw: tuple) -> list[Any]:
    return [_jsonable(value) for value in raw]


def _explain_plan(cursor, sql: str) -> Optional[dict[str, Any]]:
    """在保存点里执行 ``EXPLAIN``。

    PostgreSQL 里任何语句错误都会把当前事务置为 aborted，后续语句只能拿到
    ``current transaction is aborted``——真正的原因（列不存在、语法错误）被吃掉。
    EXPLAIN 只是展示用，失败必须回滚到保存点，让真正执行的语句报出自己的错误。
    """
    cursor.execute('SAVEPOINT t2s_explain')
    succeeded = False
    plan: Optional[dict[str, Any]] = None
    try:
        cursor.execute('EXPLAIN (FORMAT JSON) ' + sql)
        row = cursor.fetchone()
        plan = _parse_explain(row[0] if row else None)
        succeeded = True
    except psycopg2.Error:
        plan = None
    finally:
        cursor.execute('RELEASE SAVEPOINT t2s_explain' if succeeded
                       else 'ROLLBACK TO SAVEPOINT t2s_explain')
    return plan


def _parse_explain(value: Any) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    try:
        payload = json.loads(value) if isinstance(value, str) else value
        root = payload[0] if isinstance(payload, list) else payload
        plan = root.get('Plan') if isinstance(root, dict) else None
        if not isinstance(plan, dict):
            return None
        return {
            'total_cost': plan.get('Total Cost'),
            'plan_rows': plan.get('Plan Rows'),
            'plan_width': plan.get('Plan Width'),
            'node_type': plan.get('Node Type'),
            'nodes': _flatten_plan(plan),
        }
    except (ValueError, TypeError, KeyError):
        return None


def _flatten_plan(plan: dict[str, Any], depth: int = 0) -> list[dict[str, Any]]:
    node = {
        'node': plan.get('Node Type') or '',
        'detail': plan.get('Relation Name') or plan.get('Join Type') or '',
        'rows': plan.get('Plan Rows'),
        'cost': plan.get('Total Cost'),
        'depth': depth,
    }
    nodes = [node]
    for child in plan.get('Plans') or []:
        if isinstance(child, dict):
            nodes.extend(_flatten_plan(child, depth + 1))
    return nodes


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode('ascii')
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def _safe_error(error: BaseException) -> str:
    text = str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__
    return text[:500]


def build_context(snapshot: dict[str, Any],
                 hits: Optional[Iterable[dict[str, Any]]] = None) -> str:
    """兼容入口：返回上下文文本。需要选表统计时直接用 :func:`text_to_sql.context_builder.build`。"""
    return context_builder.build(snapshot, hits).text
