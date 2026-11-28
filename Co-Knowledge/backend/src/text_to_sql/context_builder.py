"""Schema 上下文构建：从检索命中挑选「本次可能的表」，再按预算拼提示词。

替换原先「把整份快照塞进去、超 24000 字符就截断」的做法。三个阶段：

1. **选表**：向量命中（TABLE / COLUMN / VALUE / METRIC / RELATION）指向的表是种子；
2. **扩展关系**：从种子表出发做 ≤2 跳 BFS，把 JOIN 必需的中转表补进来；
3. **按预算渲染**：逐表累加，超预算就停，并**显式列出被省略的表**——
   绝不出现「截断点落在某列定义中间」这种静默丢表。

预算用字符数近似 token：中文按 1 字 ≈ 1 token 估算，够用且无需引入分词器。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

DEFAULT_MAX_CHARS = 24000
DEFAULT_MAX_TABLES = 12
MAX_RELATION_HOPS = 2


@dataclass(frozen=True)
class ContextBudget:
    max_chars: int = DEFAULT_MAX_CHARS
    max_tables: int = DEFAULT_MAX_TABLES
    max_values: int = 80


@dataclass
class ContextResult:
    text: str
    tables: list[str] = field(default_factory=list)
    omitted_tables: list[str] = field(default_factory=list)
    relation_tables: list[str] = field(default_factory=list)
    truncated: bool = False
    fallback: bool = False
    #: 选表（含关系扩展）与渲染的耗时，用于把「字段检索 / 关系补全」两段如实上报。
    select_ms: int = 0
    render_ms: int = 0


class _Index:
    """快照的一次性索引：表、列、关系、值、指标之间的相互映射。"""

    def __init__(self, snapshot: dict[str, Any]):
        self.tables: dict[str, dict[str, Any]] = {}
        self.table_name: dict[str, str] = {}
        self.column_table: dict[str, str] = {}
        self.column_name: dict[str, str] = {}
        for table in snapshot.get('tables') or []:
            table_id = str(table.get('id'))
            self.tables[table_id] = table
            self.table_name[table_id] = f"{table.get('schema')}.{table.get('name')}"
            for column in table.get('columns') or []:
                column_id = str(column.get('id'))
                self.column_table[column_id] = table_id
                self.column_name[column_id] = (
                    f"{table.get('schema')}.{table.get('name')}.{column.get('name')}")
        self.relations: list[dict[str, Any]] = list(snapshot.get('relations') or [])
        self.values: list[dict[str, Any]] = list(snapshot.get('values') or [])
        self.metrics: list[dict[str, Any]] = list(snapshot.get('metrics') or [])
        self.metric_table: dict[str, str] = {
            str(metric.get('id')): str(metric.get('baseTableId'))
            for metric in self.metrics
        }
        #: 指标依赖的字段：指标被选中时，这些列即使不是 JOIN 键也要进上下文，
        #: 否则模型知道「怎么算」却找不到「算谁」。
        self.metric_columns: dict[str, set[str]] = {
            str(metric.get('id')): {
                str(item.get('columnId'))
                for item in metric.get('columnDependencies') or []
                if item.get('columnId')
            }
            for metric in self.metrics
        }
        self.metric_relations: dict[str, set[str]] = {
            str(metric.get('id')): {str(item) for item in
                                    metric.get('relationDependencies') or []}
            for metric in self.metrics
        }
        #: 关系端点列：JOIN 必需，预算紧张时优先保留。
        self.join_columns: set[str] = {
            str(pair.get(key))
            for relation in self.relations
            for pair in relation.get('columnPairs') or []
            for key in ('sourceColumnId', 'targetColumnId')
            if pair.get(key)
        }

    def neighbours(self, table_id: str) -> list[str]:
        """相邻表，按关系可信度排序：已验证 > 外键 > 人工/推断。"""
        scored: list[tuple[int, str]] = []
        for relation in self.relations:
            source = str(relation.get('sourceTableId'))
            target = str(relation.get('targetTableId'))
            if source == table_id and target in self.tables:
                scored.append((_trust(relation), target))
            elif target == table_id and source in self.tables:
                scored.append((_trust(relation), source))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [table_id for _trust, table_id in scored]


def build(snapshot: dict[str, Any], hits: Optional[Iterable[dict[str, Any]]] = None,
          *, budget: Optional[ContextBudget] = None) -> ContextResult:
    """按检索命中与预算构建上下文；``hits`` 为空时退化为全量快照。"""
    budget = budget or ContextBudget()
    index = _Index(snapshot)
    scored = _score_tables(index, list(hits or []))
    fallback = not scored
    seeds = list(scored) or [str(table.get('id')) for table in
                             snapshot.get('tables') or []]

    select_started = time.perf_counter()
    selected, expanded, dropped = _select_tables(index, seeds, budget.max_tables)
    select_ms = int((time.perf_counter() - select_started) * 1000)
    render_started = time.perf_counter()
    required_columns = _required_columns(index, selected)
    renderer = _Renderer(index, snapshot, budget,
                         {**_hit_columns(index, hits or []), **required_columns})
    for table_id in selected:
        if not renderer.render_table(table_id):
            break
    rendered = renderer.rendered
    renderer.render_relations(rendered)
    renderer.render_values(rendered)
    renderer.render_metrics(rendered)

    # 被表数预算挡掉的 + 被字符预算挡掉的，都要显式列出来。
    omitted_ids = dropped + [table_id for table_id in selected
                             if table_id not in rendered]
    return ContextResult(
        text=renderer.finish(),
        tables=[index.table_name[table_id] for table_id in rendered],
        omitted_tables=[index.table_name[table_id] for table_id in omitted_ids],
        relation_tables=[index.table_name[table_id] for table_id in expanded
                         if table_id in rendered],
        truncated=bool(omitted_ids) or renderer.truncated,
        fallback=fallback,
        select_ms=select_ms,
        render_ms=max(int((time.perf_counter() - render_started) * 1000), 0),
    )


# ---------------------------------------------------------------------------
# 选表
# ---------------------------------------------------------------------------
def _score_tables(index: _Index,
                  hits: list[dict[str, Any]]) -> dict[str, float]:
    """把各类命中折算成表级分数；返回按分数降序的 {table_id: score}。"""
    scores: dict[str, float] = {}
    for hit in hits:
        table_id = _hit_table(index, hit)
        if table_id is None or table_id not in index.tables:
            continue
        score = float(hit.get('score') or 0.0)
        # 表级命中权重最高：它就是用户问题的目标；列/值/指标命中只是佐证。
        weight = 1.0 if hit.get('object_type') == 'TABLE' else 0.6
        scores[table_id] = max(scores.get(table_id, 0.0), score * weight)
    return dict(sorted(scores.items(), key=lambda item: (-item[1], item[0])))


def _hit_table(index: _Index, hit: dict[str, Any]) -> Optional[str]:
    object_type = hit.get('object_type')
    if object_type == 'TABLE':
        return _text_id(hit.get('table_id') or hit.get('object_key'))
    if object_type == 'COLUMN':
        return index.column_table.get(_text_id(hit.get('column_id') or hit.get('object_key')))
    if object_type == 'VALUE':
        return index.column_table.get(_text_id(hit.get('column_id')))
    if object_type == 'METRIC':
        return index.metric_table.get(_text_id(hit.get('metric_id') or hit.get('object_key')))
    if object_type == 'RELATION':
        relation_id = _text_id(hit.get('relation_id') or hit.get('object_key'))
        for relation in index.relations:
            if str(relation.get('id')) == relation_id:
                return str(relation.get('sourceTableId'))
    return None


def _text_id(value: Any) -> str:
    return str(value).strip() if value else ''


def _required_columns(index: _Index,
                      selected: list[str]) -> dict[str, set[str]]:
    """被选中指标所依赖的字段，按所属表分组。"""
    result: dict[str, set[str]] = {}
    for metric_id, table_id in index.metric_table.items():
        if table_id not in selected:
            continue
        for column_id in index.metric_columns.get(metric_id, set()):
            owner = index.column_table.get(column_id)
            if owner:
                result.setdefault(owner, set()).add(column_id)
    return result


def _hit_columns(index: _Index,
                 hits: list[dict[str, Any]]) -> dict[str, set[str]]:
    """命中列（含值命中所在的列）按所属表分组，预算紧张时优先保留。"""
    result: dict[str, set[str]] = {}
    for hit in hits:
        if hit.get('object_type') not in ('COLUMN', 'VALUE'):
            continue
        column_id = _text_id(hit.get('column_id') or hit.get('object_key'))
        table_id = index.column_table.get(column_id)
        if table_id:
            result.setdefault(table_id, set()).add(column_id)
    return result


def _trust(relation: dict[str, Any]) -> int:
    """关系可信度：人工核对过 > 数据库外键 > 推断。"""
    if relation.get('verified'):
        return 3
    if str(relation.get('type') or '').upper() == 'FOREIGN_KEY':
        return 2
    return 1


def _select_tables(index: _Index, seeds: list[str],
                   max_tables: int) -> tuple[list[str], list[str], list[str]]:
    """返回 ``(入选表, 关系扩展表, 被表数预算挡掉的表)``。"""
    ordered = list(dict.fromkeys(seeds))
    expanded: list[str] = []
    frontier = list(ordered)
    for _hop in range(MAX_RELATION_HOPS):
        next_frontier: list[str] = []
        for table_id in frontier:
            for neighbour in index.neighbours(table_id):
                if neighbour in ordered:
                    continue
                ordered.append(neighbour)
                expanded.append(neighbour)
                next_frontier.append(neighbour)
        if not next_frontier:
            break
        frontier = next_frontier
    return ordered[:max_tables], expanded[:max_tables], ordered[max_tables:]


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
class _Renderer:
    def __init__(self, index: _Index, snapshot: dict[str, Any],
                 budget: ContextBudget,
                 hit_columns: Optional[dict[str, set[str]]] = None):
        self._index = index
        self._budget = budget
        self._hit_columns = hit_columns or {}
        self._lines: list[str] = []
        self._size = 0
        self.rendered: list[str] = []
        self.truncated = False
        self._header(snapshot.get('datasource') or {})

    # -- 基础 ---------------------------------------------------------------
    def _header(self, datasource: dict[str, Any]) -> None:
        self._emit(f"数据库类型：{datasource.get('dbType') or 'postgresql'}")
        self._emit(f"业务时区：{datasource.get('businessTimezone') or 'UTC'}")
        topic = datasource.get('topic') or {}
        label = ' / '.join(str(value) for value in
                           (topic.get('name'), topic.get('description')) if value)
        if label:
            self._emit('业务主题：' + label)
        self._emit('')
        self._emit('可用数据表（只能使用以下表与字段）：')

    def _emit(self, line: str) -> bool:
        size = len(line) + 1
        if self._size + size > self._budget.max_chars:
            self.truncated = True
            return False
        self._lines.append(line)
        self._size += size
        return True

    # -- 表 -----------------------------------------------------------------
    def render_table(self, table_id: str) -> bool:
        """渲染一张表；预算不足时返回 ``False``（该表只算「已省略」）。

        整表放不下时退一步：只渲染 JOIN 必需与度量/时间字段，并明确标注省略了多少列。
        """
        table = self._index.tables.get(table_id)
        if table is None:
            return True
        header = self._table_header(table_id, table)
        columns = list(table.get('columns') or [])
        full = [self._column_line(column) for column in columns]
        if self._fits(header, full):
            return self._write(header, full, table_id)

        essential = [column for column in columns if self._is_essential(table, column)]
        if essential and self._fits(header, [self._column_line(c) for c in essential]):
            lines = [self._column_line(column) for column in essential]
            lines.append(f"    ...（其余 {len(columns) - len(essential)} 个字段已省略）")
            return self._write(header, lines, table_id)
        self.truncated = True
        return False

    def _fits(self, header: str, lines: list[str]) -> bool:
        needed = len(header) + 1 + sum(len(line) + 1 for line in lines)
        return self._size + needed <= self._budget.max_chars

    def _write(self, header: str, lines: list[str], table_id: str) -> bool:
        self._emit(header)
        for line in lines:
            self._emit(line)
        self.rendered.append(table_id)
        return True

    def _is_essential(self, table: dict[str, Any], column: dict[str, Any]) -> bool:
        """JOIN 键、时间字段、度量、语义标识，以及被检索命中的列。"""
        if column.get('primaryKey'):
            return True
        if str(column.get('id')) in self._index.join_columns:
            return True
        if column.get('semanticType') in ('measure', 'time', 'identifier'):
            return True
        data_type = str(column.get('dataType') or '').lower()
        if any(marker in data_type for marker in ('date', 'time', 'timestamp')):
            return True
        return str(column.get('id')) in self._hit_columns.get(str(table.get('id')), set())

    def _table_header(self, table_id: str, table: dict[str, Any]) -> str:
        header = f"- {self._index.table_name[table_id]}"
        extras = [value for value in (table.get('businessName'),
                                      table.get('businessDescription'),
                                      table.get('dbComment')) if value]
        if extras:
            header += '（' + '；'.join(str(value) for value in extras) + '）'
        return header

    @staticmethod
    def _column_line(column: dict[str, Any]) -> str:
        extras = [value for value in (column.get('businessName'),
                                      column.get('businessDescription'),
                                      column.get('dbComment')) if value]
        suffix = ('  -- ' + '；'.join(extras)) if extras else ''
        flags = []
        if column.get('primaryKey'):
            flags.append('PK')
        if column.get('semanticType'):
            flags.append(str(column['semanticType']))
        flag_text = (' [' + ','.join(flags) + ']') if flags else ''
        return (f"    {column.get('name')} {column.get('dataType')}"
                f"{flag_text}{suffix}")

    # -- 关联 ---------------------------------------------------------------
    def render_relations(self, selected: list[str]) -> None:
        """只渲染两端都在上下文里的关系——JOIN 用得到才写。"""
        relations = [relation for relation in self._index.relations
                     if str(relation.get('sourceTableId')) in selected
                     and str(relation.get('targetTableId')) in selected]
        if not relations or not self._emit_block_title('表关联：'):
            return
        for relation in relations:
            if not self._emit(self._relation_line(relation)):
                return

    def _relation_line(self, relation: dict[str, Any]) -> str:
        pairs = []
        for pair in relation.get('columnPairs') or []:
            source = self._index.column_name.get(str(pair.get('sourceColumnId')))
            target = self._index.column_name.get(str(pair.get('targetColumnId')))
            if source and target:
                pairs.append(f'{source} = {target}')
        detail = f"- {relation.get('name')}"
        if relation.get('cardinality'):
            detail += f"（{relation['cardinality']}）"
        if pairs:
            detail += '：' + '；'.join(pairs)
        if relation.get('description'):
            detail += '。' + str(relation['description'])
        return detail

    # -- 值 / 指标 -----------------------------------------------------------
    def render_values(self, selected: list[str]) -> None:
        values = [value for value in self._index.values
                  if self._index.column_table.get(str(value.get('columnId'))) in selected]
        if not values or not self._emit_block_title('枚举值（业务名称/同义词可用于匹配）：'):
            return
        for value in values[:self._budget.max_values]:
            if not self._emit(self._value_line(value)):
                return

    def _value_line(self, value: dict[str, Any]) -> str:
        label = value.get('businessName')
        aliases = value.get('aliases') or []
        extra = ''
        if label:
            extra = f'（{label}'
            if aliases:
                extra += '，同义词：' + '、'.join(aliases)
            extra += '）'
        column_name = self._index.column_name.get(
            str(value.get('columnId')), str(value.get('columnId')))
        return f"- 字段 {column_name} = {value.get('rawValue')}{extra}"

    def render_metrics(self, selected: list[str]) -> None:
        metrics = [metric for metric in self._index.metrics
                   if str(metric.get('baseTableId') or '') in selected
                   or not metric.get('baseTableId')]
        if not metrics or not self._emit_block_title(
                '指标定义（优先复用；NON_ADDITIVE 表示不可跨期直接相加）：'):
            return
        for metric in metrics:
            if not self._emit(self._metric_line(metric)):
                return

    def _metric_line(self, metric: dict[str, Any]) -> str:
        detail = [f"表达式：{metric.get('expressionSql')}"]
        if metric.get('aggregationBehavior'):
            detail.append(f"可加性：{metric['aggregationBehavior']}")
        if metric.get('unit'):
            detail.append(f"单位：{metric['unit']}")
        if metric.get('timeColumnId'):
            time_column = self._index.column_name.get(str(metric['timeColumnId']))
            if time_column:
                detail.append(f"时间字段：{time_column}")
        if metric.get('businessTimezone'):
            detail.append(f"时区：{metric['businessTimezone']}")
        if metric.get('filterDefinition'):
            detail.append('过滤条件：' + json.dumps(
                metric['filterDefinition'], ensure_ascii=False))
        if metric.get('attributionDescription'):
            detail.append(f"统计归属：{metric['attributionDescription']}")
        return (f"- {metric.get('key')} {metric.get('businessName')}："
                + '；'.join(detail))

    def _emit_block_title(self, title: str) -> bool:
        return self._emit('') and self._emit(title)

    # -- 收尾 ---------------------------------------------------------------
    def finish(self) -> str:
        if self.truncated:
            self._lines.append('...（上下文超出预算，已按相关度取舍；'
                               '如需其他表请缩小问题范围）')
        return '\n'.join(self._lines)
