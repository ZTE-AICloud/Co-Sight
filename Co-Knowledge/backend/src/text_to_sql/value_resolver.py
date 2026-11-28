"""查询时值解析：把生成 SQL 里的文本字面量回查数据库，改写为真实存储值。

只处理 WHERE/HAVING 等位置上的文本列等值（``=``）与 ``IN`` 列表字面量；
``LIKE``、``NOT IN``、``<>``、函数参数等一律不动。开放维度（城市、商品）
不需要提前枚举，解析只在本次查询里做一次带 LIMIT / 超时的只读回查：

- 唯一命中：把字面量改写成数据库里的存储值（西安 → 西安市）；
- 多命中：抛出候选，让用户补充更精确的名称；
- 零命中：明确报错，不再返回误导性的 0；
- 回查超时或失败：保留原字面量继续执行，由调用方记录告警。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

import psycopg2

RESOLUTION_TIMEOUT_MS = 2000
MAX_CANDIDATES = 20
MAX_LITERAL_LENGTH = 200
NAME_SUFFIXES = ('市', '省', '区', '县', '镇', '乡', '街道')

_IDENTIFIER = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)'
_IDENTIFIER_CHAIN = rf'{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})*'
_EQUALITY = re.compile(rf'({_IDENTIFIER_CHAIN})\s*=\s*$', re.IGNORECASE)
_TABLE_REF = re.compile(
    rf'\b(?:FROM|JOIN)\s+({_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})?)'
    rf'(?:\s+(?:AS\s+)?("?[A-Za-z_][A-Za-z0-9_$]*"?))?',
    re.IGNORECASE)
_KEYWORDS = {
    'where', 'on', 'join', 'left', 'right', 'inner', 'outer', 'full', 'cross',
    'group', 'order', 'limit', 'offset', 'union', 'having', 'window', 'fetch',
    'for', 'as', 'using', 'natural', 'lateral', 'tablesample',
}


class ValueResolutionError(RuntimeError):
    def __init__(self, code: str, message: str,
                 candidates: Optional[list[str]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidates = candidates or []


@dataclass(frozen=True)
class SqlLiteral:
    start: int
    end: int
    value: str


@dataclass(frozen=True)
class TextFilter:
    start: int
    end: int
    value: str
    schema: str
    table: str
    column: str
    mode: str  # 'eq' | 'in'


def resolve_and_rewrite(connection: dict[str, Any], sql: str,
                        snapshot: dict[str, Any],
                        policy: Optional[dict[str, Any]] = None
                        ) -> tuple[str, list[dict[str, Any]]]:
    """解析 SQL 中的文本字面量并返回 ``(新 SQL, 解析记录)``。

    没有任何可解析字面量时不建立数据库连接。
    """
    filters = extract_text_filters(sql, snapshot)
    if not filters:
        return sql, []

    timeout_ms = min(RESOLUTION_TIMEOUT_MS,
                     int((policy or {}).get('timeout_ms') or RESOLUTION_TIMEOUT_MS))
    try:
        conn = _open_connection(connection, timeout_ms)
    except psycopg2.Error:
        # 连接失败交给后续执行阶段报错；值解析不额外阻断。
        return sql, []
    datasource = snapshot.get('datasource') or {}
    scope = ' '.join(str(item) for item in (datasource.get('name'),
                                            datasource.get('database')) if item)
    scope_text = f'{scope} 的 ' if scope else ''
    try:
        cache: dict[tuple[str, str, str, str], tuple[str, str]] = {}
        resolutions: list[dict[str, Any]] = []
        replacements: list[tuple[int, int, str]] = []
        for item in filters:
            key = (item.schema, item.table, item.column, item.value)
            if key not in cache:
                try:
                    resolved = _resolve_literal(conn, item, timeout_ms)
                except psycopg2.Error:
                    # 回查失败/超时：保留原值继续执行，由调用方记录告警。
                    resolved = ('skip', '')
                cache[key] = resolved
            status, value = cache[key]
            if status == 'skip':
                resolutions.append({
                    'schema': item.schema, 'table': item.table,
                    'column': item.column, 'from': item.value,
                    'value': item.value, 'match': 'skipped',
                })
                continue
            if status == 'ambiguous':
                raise ValueResolutionError(
                    'VALUE_AMBIGUOUS',
                    f'“{item.value}”在 {scope_text}{item.table}.{item.column} '
                    f"中匹配到多个值：{'、'.join(value.split('|')[:10])}；"
                    '请使用更精确的名称。',
                    value.split('|')[:MAX_CANDIDATES])
            if status == 'missing':
                raise ValueResolutionError(
                    'VALUE_NOT_FOUND',
                    f'未在 {scope_text}{item.table}.{item.column} 中找到'
                    f'“{item.value}”；请确认名称，或在枚举值中补充别名。',
                    [])
            if value == item.value:
                continue
            replacements.append((item.start, item.end, _quote_literal(value)))
            resolutions.append({
                'schema': item.schema, 'table': item.table,
                'column': item.column, 'from': item.value,
                'value': value, 'match': 'resolved',
            })
        if not replacements:
            return sql, resolutions
        rewritten = sql
        for start, end, replacement in sorted(replacements, reverse=True):
            rewritten = rewritten[:start] + replacement + rewritten[end:]
        return rewritten, resolutions
    finally:
        conn.close()


def extract_text_filters(sql: str, snapshot: dict[str, Any]) -> list[TextFilter]:
    """提取可解析的文本列字面量（纯函数，不访问数据库）。"""
    literals, masked = _scan_literals(sql)
    if not literals:
        return []
    tables, bare = _snapshot_tables(snapshot)
    aliases = _alias_map(masked, tables, bare)
    filters: list[TextFilter] = []
    for literal in literals:
        if not literal.value or len(literal.value) > MAX_LITERAL_LENGTH:
            continue
        qualifier = _equality_qualifier(masked, literal.start)
        mode = 'eq'
        if qualifier is None:
            if not _inside_in_list(masked, literal.start):
                continue
            qualifier = _in_list_qualifier(masked, literal.start)
            if qualifier is None:
                continue
            mode = 'in'
        column = _resolve_column(qualifier, aliases, tables, bare)
        if column is None:
            continue
        (schema, table), column_def = column
        if not _is_text_type(column_def.get('dataType')):
            continue
        filters.append(TextFilter(
            start=literal.start, end=literal.end, value=literal.value,
            schema=schema, table=table, column=column_def['name'], mode=mode))
    return filters


# ---------------------------------------------------------------------------
# SQL 扫描
# ---------------------------------------------------------------------------
def _scan_literals(sql: str) -> tuple[list[SqlLiteral], str]:
    """返回单引号字符串字面量与同样长度的“去字面量”文本（保留引号标识符）。"""
    literals: list[SqlLiteral] = []
    masked: list[str] = []
    index = 0
    length = len(sql)
    state = 'normal'
    start = -1
    buffer: list[str] = []
    while index < length:
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < length else ''
        if state == 'normal':
            if char == "'":
                state = 'single'
                start = index
                buffer = []
                masked.append(' ')
            elif char == '"':
                state = 'double'
                masked.append('"')
            elif char == '-' and nxt == '-':
                state = 'line'
                masked.extend('  ')
                index += 1
            elif char == '/' and nxt == '*':
                state = 'block'
                masked.extend('  ')
                index += 1
            else:
                masked.append(char)
        elif state == 'single':
            masked.append(' ')
            if char == "'":
                if nxt == "'":
                    buffer.append("'")
                    masked.append(' ')
                    index += 1
                else:
                    literals.append(SqlLiteral(start, index + 1, ''.join(buffer)))
                    state = 'normal'
            else:
                buffer.append(char)
        elif state == 'double':
            if char == '"':
                if nxt == '"':
                    masked.append('"')
                    index += 1
                else:
                    masked.append('"')
                    state = 'normal'
            else:
                masked.append(char)
        elif state == 'line':
            masked.append('\n' if char == '\n' else ' ')
            if char == '\n':
                state = 'normal'
        elif state == 'block':
            masked.append(' ')
            if char == '*' and nxt == '/':
                masked.append(' ')
                index += 1
                state = 'normal'
        index += 1
    return literals, ''.join(masked)


def _equality_qualifier(masked: str, start: int) -> Optional[str]:
    match = _EQUALITY.search(masked[:start])
    return match.group(1) if match else None


def _inside_in_list(masked: str, start: int) -> bool:
    index = start - 1
    while index >= 0 and masked[index].isspace():
        index -= 1
    return index >= 0 and masked[index] in '(,'


def _in_list_qualifier(masked: str, start: int) -> Optional[str]:
    index = start - 1
    while index >= 0 and masked[index].isspace():
        index -= 1
    depth = 0
    while index >= 0:
        char = masked[index]
        if char == ')':
            depth += 1
        elif char == '(':
            if depth == 0:
                break
            depth -= 1
        index -= 1
    if index < 0:
        return None
    before = masked[:index].rstrip()
    if re.search(r'\bNOT\s+IN\s*$', before, re.IGNORECASE):
        return None
    match = re.search(r'\bIN\s*$', before, re.IGNORECASE)
    if not match:
        return None
    prefix = before[:match.start()].rstrip()
    match = re.search(rf'({_IDENTIFIER_CHAIN})\s*$', prefix, re.IGNORECASE)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# 表/列解析
# ---------------------------------------------------------------------------
def _snapshot_tables(snapshot: dict[str, Any]):
    tables: dict[tuple[str, str], dict[str, Any]] = {}
    bare: dict[str, list[tuple[str, str]]] = {}
    for table in snapshot.get('tables') or []:
        schema = str(table.get('schema') or '').lower()
        name = str(table.get('name') or '').lower()
        if not schema or not name:
            continue
        key = (schema, name)
        tables[key] = table
        bare.setdefault(name, []).append(key)
    return tables, bare


def _clean_identifier(value: str) -> str:
    return value.strip().strip('"').strip()


def _resolve_table_ref(raw: str, tables: dict, bare: dict) -> Optional[tuple[str, str]]:
    cleaned = re.sub(r'\s+', '', raw)
    parts = [_clean_identifier(part) for part in cleaned.split('.')]
    if len(parts) >= 2:
        key = (parts[-2].lower(), parts[-1].lower())
        return key if key in tables else None
    matches = bare.get(parts[-1].lower()) or []
    return matches[0] if len(matches) == 1 else None


def _alias_map(masked: str, tables: dict, bare: dict) -> dict[str, tuple[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for match in _TABLE_REF.finditer(masked):
        key = _resolve_table_ref(match.group(1), tables, bare)
        if key is None:
            continue
        alias = _clean_identifier(match.group(2) or '')
        if alias and alias.lower() not in _KEYWORDS:
            aliases[alias.lower()] = key
        aliases.setdefault(key[1], key)
    return aliases


def _resolve_column(qualifier: str, aliases: dict, tables: dict,
                    bare: dict) -> Optional[tuple[tuple[str, str], dict[str, Any]]]:
    parts = [_clean_identifier(part) for part in re.split(r'\s*\.\s*', qualifier)]
    if not parts:
        return None
    column_name = parts[-1]
    if len(parts) == 1:
        candidates = []
        for key in set(aliases.values()):
            column = _find_column(tables[key], column_name)
            if column is not None:
                candidates.append((key, column))
        return candidates[0] if len(candidates) == 1 else None
    if len(parts) == 2:
        key = aliases.get(parts[0].lower())
        if key is None:
            matches = bare.get(parts[0].lower()) or []
            key = matches[0] if len(matches) == 1 else None
    else:
        key = (parts[-3].lower(), parts[-2].lower())
        if key not in tables:
            key = None
    if key is None:
        return None
    column = _find_column(tables[key], column_name)
    return (key, column) if column is not None else None


def _find_column(table: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
    lowered = name.lower()
    for column in table.get('columns') or []:
        if str(column.get('name') or '').lower() == lowered:
            return column
    return None


def _is_text_type(data_type: Optional[str]) -> bool:
    lowered = str(data_type or '').lower()
    return any(marker in lowered for marker in ('char', 'text', 'citext', 'name'))


# ---------------------------------------------------------------------------
# 数据库回查
# ---------------------------------------------------------------------------
def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _escape_like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _open_connection(connection: dict[str, Any], timeout_ms: int):
    conn = psycopg2.connect(
        host=connection.get('host'),
        port=connection.get('port') or 5432,
        dbname=connection.get('database'),
        user=connection.get('username'),
        password=connection.get('password') or '',
        connect_timeout=5,
        application_name='co-knowledge-text2sql-resolver',
        options=f'-c statement_timeout={timeout_ms}',
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _resolve_literal(conn, item: TextFilter, timeout_ms: int
                     ) -> tuple[str, str]:
    """返回 ``(status, value)``；value 在多命中时用 ``|`` 连接候选。"""
    table = (f'{_quote_identifier(item.schema)}.'
             f'{_quote_identifier(item.table)}')
    column = _quote_identifier(item.column)
    for pattern in _candidate_patterns(item.value):
        rows = _distinct_values(conn, table, column, pattern,
                                limit=MAX_CANDIDATES + 1)
        if rows is None:
            return ('skip', '')
        if len(rows) == 1:
            return ('resolved', rows[0])
        if len(rows) > 1:
            return ('ambiguous', '|'.join(rows))
    return ('missing', '')


def _candidate_patterns(value: str) -> list[tuple[str, str]]:
    """按精确 → 忽略大小写 → 去掉行政区后缀做前缀 → 包含，依次尝试。"""
    normalized = unicodedata.normalize('NFKC', value.strip())
    if not normalized:
        return []
    patterns: list[tuple[str, str]] = [('eq', normalized), ('ilike', normalized)]
    stripped = _strip_suffix(normalized)
    if stripped != normalized:
        patterns.append(('ilike', f'{_escape_like(stripped)}%'))
    if len(normalized) >= 2:
        patterns.append(('ilike', f'%{_escape_like(normalized)}%'))
    return patterns


def _strip_suffix(value: str) -> str:
    result = value
    while len(result) > 2 and result.endswith(NAME_SUFFIXES):
        result = result[:-1]
    return result


def _distinct_values(conn, table: str, column: str, pattern: tuple[str, str],
                     limit: int) -> Optional[list[str]]:
    kind, value = pattern
    operator = '=' if kind == 'eq' else 'ILIKE'
    query = (f'SELECT DISTINCT {column}::text FROM {table} '
             f'WHERE {column} IS NOT NULL AND {column} {operator} %s '
             f'LIMIT {int(limit)}')
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, (value,))
            return [row[0] for row in cursor.fetchall() if row[0] is not None]
    except psycopg2.Error:
        return None
