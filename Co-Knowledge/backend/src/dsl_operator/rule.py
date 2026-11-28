"""告警规则 DSL：类型化 AST + 校验 + 编译成只读 SQL。

场景（本仓自己造的一个）：运营想表达「西安市近 30 天支付金额低于 10 万就告警」，
这是一个**规则**——有指标、有过滤、有窗口、有阈值、有严重级别——不是一次临时查询。
把它做成 DSL 而不是自由 SQL，好处是：规则可以被校验、可以落库复用、可以定时跑。

语法（文本形态，供人读与日志）：

    WHEN paid_amount WHERE region.city_name = '西安市' LAST 30d < 100000 THEN warning

模型产出的是结构化 JSON，本模块负责：

* :func:`parse` —— 把 JSON 变成类型化 AST，字段/算子/窗口/严重级别全部白名单；
* :func:`compile_sql` —— 把 AST 编译成只读聚合 SQL（指标表达式来自指标注册表）。

编译出来的 SQL 仍然要过 ``sql_guard`` 的 AST 白名单，所以 DSL 这一层不是安全边界，
而是**语义边界**：它保证「规则」这个词只表达规则该有的东西。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from knowledge_engine.operator import OperatorError

OPERATORS = {'>', '>=', '<', '<=', '=', '!='}
SEVERITIES = {'info', 'warning', 'critical'}
MAX_WINDOW_DAYS = 365
MAX_FILTERS = 8


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: Any

    def to_sql(self) -> str:
        literal = _literal(self.value)
        return f'{_identifier(self.column)} {self.op} {literal}'


@dataclass(frozen=True)
class Rule:
    metric: str
    condition: str
    threshold: float
    window_days: int = 0
    severity: str = 'warning'
    filters: list[Filter] = field(default_factory=list)
    name: str = ''

    def to_text(self) -> str:
        parts = [f'WHEN {self.metric}']
        if self.filters:
            parts.append('WHERE ' + ' AND '.join(
                f"{item.column} {item.op} {item.value!r}" for item in self.filters))
        if self.window_days:
            parts.append(f'LAST {self.window_days}d')
        parts.append(f'{self.condition} {self.threshold:g}')
        parts.append(f'THEN {self.severity}')
        return ' '.join(parts)


def parse(payload: Any) -> Rule:
    """把模型产出的 JSON 解析成 :class:`Rule`；非法内容抛 ``OperatorError``。"""
    if not isinstance(payload, dict):
        raise OperatorError('DSL_INVALID', '规则必须是 JSON 对象', 'validation')
    metric = str(payload.get('metric') or '').strip()
    if not metric:
        raise OperatorError('DSL_INVALID', '规则缺少 metric', 'validation')
    condition = str(payload.get('condition') or '').strip()
    if condition not in OPERATORS:
        raise OperatorError('DSL_INVALID',
                            f'比较算子必须是 {"/".join(sorted(OPERATORS))}',
                            'validation')
    threshold = _number(payload.get('threshold'))
    severity = str(payload.get('severity') or 'warning').lower()
    if severity not in SEVERITIES:
        raise OperatorError('DSL_INVALID',
                            f'严重级别必须是 {"/".join(sorted(SEVERITIES))}',
                            'validation')
    window_days = payload.get('windowDays') or 0
    if not isinstance(window_days, int) or isinstance(window_days, bool) \
            or window_days < 0 or window_days > MAX_WINDOW_DAYS:
        raise OperatorError('DSL_INVALID', f'窗口必须在 0–{MAX_WINDOW_DAYS} 天',
                            'validation')
    raw_filters = payload.get('filters') or []
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_FILTERS:
        raise OperatorError('DSL_INVALID', f'过滤条件最多 {MAX_FILTERS} 条',
                            'validation')
    filters = [_parse_filter(item) for item in raw_filters]
    return Rule(metric=metric, condition=condition, threshold=threshold,
                window_days=window_days, severity=severity, filters=filters,
                name=str(payload.get('name') or ''))


def _parse_filter(item: Any) -> Filter:
    if not isinstance(item, dict):
        raise OperatorError('DSL_INVALID', '过滤条件必须是对象', 'validation')
    column = str(item.get('column') or '').strip()
    if not column or '.' not in column:
        raise OperatorError('DSL_INVALID',
                            '过滤字段必须写成 表.字段（如 region.city_name）',
                            'validation')
    op = str(item.get('op') or '=').strip()
    if op not in OPERATORS:
        raise OperatorError('DSL_INVALID', f'过滤算子不支持：{op}', 'validation')
    if 'value' not in item:
        raise OperatorError('DSL_INVALID', '过滤条件缺少 value', 'validation')
    return Filter(column=column, op=op, value=item['value'])


def compile_sql(rule: Rule, snapshot: dict[str, Any]) -> str:
    """把规则编译成只读聚合 SQL。

    指标表达式与基础表来自冻结快照的指标注册表；时间字段用于窗口过滤。
    """
    metric = _metric(rule.metric, snapshot)
    expression = metric.get('expressionSql') or ''
    base_table = _table_name(metric.get('baseTableId'), snapshot)
    if not expression or not base_table:
        raise OperatorError('DSL_METRIC_INVALID',
                            f'指标 {rule.metric} 缺少表达式或基础表', 'validation')

    where: list[str] = []
    if metric.get('filterDefinition'):
        where.append(f"({metric['filterDefinition']})"
                     if isinstance(metric['filterDefinition'], str) else '')
    where.extend(item.to_sql() for item in rule.filters)
    if rule.window_days and metric.get('timeColumnId'):
        column = _column_name(metric['timeColumnId'], snapshot)
        if column:
            where.append(f"{column} >= now() - interval '{rule.window_days} days'")

    sql = (f"SELECT {expression} AS value FROM {base_table}")
    if where:
        sql += ' WHERE ' + ' AND '.join(part for part in where if part)
    return sql


def _metric(key: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    for metric in snapshot.get('metrics') or []:
        if str(metric.get('key')) == key:
            return metric
    raise OperatorError('DSL_METRIC_NOT_FOUND',
                        f'指标 {key} 不在当前发布版本里', 'validation')


def _table_name(table_id: Any, snapshot: dict[str, Any]) -> Optional[str]:
    for table in snapshot.get('tables') or []:
        if str(table.get('id')) == str(table_id):
            return _identifier(f"{table.get('schema')}.{table.get('name')}")
    return None


def _column_name(column_id: Any, snapshot: dict[str, Any]) -> Optional[str]:
    for table in snapshot.get('tables') or []:
        for column in table.get('columns') or []:
            if str(column.get('id')) == str(column_id):
                return _identifier(
                    f"{table.get('schema')}.{table.get('name')}.{column.get('name')}")
    return None


def _identifier(value: str) -> str:
    parts = [part for part in str(value).split('.') if part]
    if not parts or any(not _safe(part) for part in parts):
        raise OperatorError('DSL_INVALID', f'非法标识符：{value}', 'validation')
    return '.'.join(f'"{part}"' for part in parts)


def _safe(part: str) -> bool:
    return part.replace('_', '').isalnum() and not part[0].isdigit()


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OperatorError('DSL_INVALID', '阈值必须是数字', 'validation')
    return float(value)
