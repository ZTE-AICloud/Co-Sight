"""Text2SQL 作为 Query Operator 的适配层。

它不复制查询编排的逻辑——四段分别调用**同一批函数**，只是把它们摆到引擎的
契约上，让调用方（未来的 Agent / MCP、跨算子路由）不必知道 Text2SQL 的内部结构：

| 阶段 | 调用 | 说明 |
|---|---|---|
| retrieve | ``context_builder.build`` | 检索命中选表 + 关系扩展 + 预算裁剪 |
| plan | 注入的 ``llm``（默认 ``query_service._generate_sql``） | 产出 SQL 与解释 |
| validate | ``sql_guard.validate_sql`` | PostgreSQL 语法树白名单 |
| execute | ``sql_guard.execute_readonly`` | 只读事务 + 行/字节上限 |

``params`` 里需要 ``snapshot``；``plan``/``execute`` 另需 ``connection``，
``execute`` 还需要 ``policy``。这样同一个算子既能跑在同步接口里，也能被
流式接口按阶段驱动。
"""

from __future__ import annotations

from typing import Any, Optional

from knowledge_engine.operator import (OperatorContext, QueryPlan, ResultSet,
                                       ValidatedPlan)
from text_to_sql import context_builder, sql_guard


class Text2SqlOperator:
    name = 'nl2sql'
    knowledge_types = ('TABLE', 'COLUMN', 'RELATION', 'VALUE', 'METRIC')

    def __init__(self, llm=None):
        self._llm = llm

    # -- retrieve -----------------------------------------------------------
    def retrieve(self, question: str, *, datasource_id: str,
                 params: dict[str, Any]) -> OperatorContext:
        snapshot = params['snapshot']
        result = context_builder.build(snapshot, params.get('hits') or [])
        return OperatorContext(
            text=result.text,
            objects=[{'type': 'TABLE', 'name': name} for name in result.tables],
            sources={'tables': len(result.tables),
                     'omitted': len(result.omitted_tables)},
            fallback=result.fallback,
            truncated=result.truncated,
        )

    # -- plan ---------------------------------------------------------------
    def plan(self, question: str, context: OperatorContext, *,
             params: dict[str, Any]) -> QueryPlan:
        llm = self._llm or _default_llm()
        generated = llm(
            question=question,
            snapshot=params['snapshot'],
            schema_context=context.text,
            value_hints=params.get('value_hints') or [],
            date_policy=params.get('date_policy') or 'relative',
            resolved_time_range=params.get('resolved_time_range') or {},
            reference_date=params.get('reference_date') or '',
            model=params.get('model'),
            feedback=params.get('feedback') or '')
        return QueryPlan(
            query=generated.get('sql') or '',
            language='sql',
            explanation=generated.get('explanation') or '',
            confidence=generated.get('confidence'),
            usage=generated.get('usage') or {},
        )

    # -- validate -----------------------------------------------------------
    def validate(self, plan: QueryPlan, *,
                 params: dict[str, Any]) -> ValidatedPlan:
        return ValidatedPlan(query=sql_guard.validate_sql(plan.query,
                                                          params['snapshot']))

    # -- execute ------------------------------------------------------------
    def execute(self, plan: ValidatedPlan, *,
                params: dict[str, Any]) -> ResultSet:
        executed = sql_guard.execute_readonly(
            params['connection'], plan.query,
            params.get('policy') or {}, params['snapshot'])
        return ResultSet(
            columns=executed['columns'],
            rows=executed['rows'],
            truncated=executed['truncated'],
            byte_truncated=executed.get('byte_truncated', False),
            extra={'explain': executed.get('explain'),
                   'explain_ms': executed.get('explain_ms'),
                   'execute_ms': executed.get('execute_ms')},
        )


def _default_llm():
    from text_to_sql.query_service import _generate_sql

    return _generate_sql


_operator: Optional[Text2SqlOperator] = None


def get_operator() -> Text2SqlOperator:
    global _operator
    if _operator is None:
        _operator = Text2SqlOperator()
    return _operator
