"""NL2DSL 算子：告警规则的四段实现。

retrieve → 把指标注册表投影成可选指标（BM25 挑相关指标）；
plan     → 模型产出规则 JSON；
validate → :func:`dsl_operator.rule.parse` + 编译 + ``sql_guard`` 白名单；
execute  → 复用只读执行器（与 NL2SQL 同一个运行时，不另建）。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from dsl_operator import rule as rule_dsl
from knowledge_engine import retrieval
from knowledge_engine.operator import (OperatorContext, OperatorError,
                                       QueryPlan, ResultSet, ValidatedPlan)
from text_to_sql import sql_guard


class Nl2DslOperator:
    name = 'nl2dsl'
    knowledge_types = ('METRIC',)

    def __init__(self, llm: Optional[Callable[..., dict]] = None):
        self._llm = llm

    def retrieve(self, question: str, *, datasource_id: str,
                 params: dict[str, Any]) -> OperatorContext:
        metrics = params['snapshot'].get('metrics') or []
        rows = [{'object_type': 'METRIC', 'object_key': str(item.get('key')),
                 'title': str(item.get('businessName') or item.get('key')),
                 'content': f"指标 {item.get('key')}（{item.get('businessName')}）："
                            f"{item.get('expressionSql')}；单位 {item.get('unit') or '-'}"}
                for item in metrics]
        hits = retrieval.lexical_search(
            question=question, corpus_loader=lambda _key: rows,
            corpus_key=f'metrics:{datasource_id}:{len(rows)}',
            limit=params.get('limit') or 12)
        return OperatorContext(
            text='\n'.join([f'可用指标（{len(rows)} 个）：']
                           + [f"- {hit['content']}" for hit in hits]),
            objects=[{'type': 'METRIC', 'name': hit['object_key']} for hit in hits],
            sources={'lexical': len(hits)}, fallback=not hits)

    def plan(self, question: str, context: OperatorContext, *,
             params: dict[str, Any]) -> QueryPlan:
        llm = self._llm or _default_llm()
        generated = llm(question=question, context=context.text,
                        model=params.get('model'))
        return QueryPlan(query=json.dumps(generated, ensure_ascii=False, sort_keys=True),
                         language='alert_rule',
                         explanation=generated.get('explanation') or '',
                         usage=generated.get('usage') or {})

    def validate(self, plan: QueryPlan, *,
                 params: dict[str, Any]) -> ValidatedPlan:
        try:
            payload = json.loads(plan.query)
        except (TypeError, ValueError) as error:
            raise OperatorError('DSL_INVALID', '规则不是合法 JSON', 'validation') from error
        parsed = rule_dsl.parse(payload)
        sql = rule_dsl.compile_sql(parsed, params['snapshot'])
        # 编译结果仍要过 SQL 白名单：DSL 是语义边界，不是安全边界。
        checked = sql_guard.validate_sql(sql, params['snapshot'])
        return ValidatedPlan(query=checked,
                             details={'rule': parsed.to_text(),
                                      'severity': parsed.severity})

    def execute(self, plan: ValidatedPlan, *,
                params: dict[str, Any]) -> ResultSet:
        executed = sql_guard.execute_readonly(
            params['connection'], plan.query,
            params.get('policy') or {}, params['snapshot'])
        value = (executed['rows'] or [[None]])[0][0]
        return ResultSet(columns=['value'], rows=executed['rows'],
                         truncated=executed['truncated'],
                         byte_truncated=executed.get('byte_truncated', False),
                         extra={'rule': plan.details.get('rule'),
                                'severity': plan.details.get('severity'),
                                'value': value})


def _default_llm(**kwargs) -> dict[str, Any]:
    from model.operator_client import invoke_llm
    from model.resolver import resolve

    target = resolve('llm', kwargs.get('model'))
    system = ('你是经营告警规则生成器。只输出 JSON：'
              '{"metric","filters":[{"column":"表.字段","op","value"}],'
              '"windowDays","condition","threshold","severity","name"}。'
              'condition ∈ > >= < <= = !=；severity ∈ info/warning/critical。')
    content, usage = invoke_llm(
        [{'role': 'system', 'content': system},
         {'role': 'user', 'content': f"问题：{kwargs.get('question')}\n{kwargs.get('context')}"}],
        model=target.api_model, temperature=0.0,
        endpoint={'url': target.url, 'model': target.api_model,
                  'api_key': target.api_key,
                  'thinking_payload': target.thinking_payload,
                  'timeout': target.timeout},
        with_usage=True)
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as error:
        raise OperatorError('DSL_INVALID', '模型没有返回可解析的规则 JSON',
                            'llm') from error
    return {**payload, 'usage': usage}


_operator: Optional[Nl2DslOperator] = None


def get_operator() -> Nl2DslOperator:
    global _operator
    if _operator is None:
        _operator = Nl2DslOperator()
    return _operator
