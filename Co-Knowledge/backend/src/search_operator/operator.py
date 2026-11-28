"""NL2Search 算子：mapping → 检索 → 生成 DSL → 校验 → 执行。

四段与其他算子同构，区别只在「查询语言是 ES DSL」：

* retrieve：把索引 mapping 投影成 INDEX/FIELD 知识，用 BM25 挑相关字段；
* plan：模型产出 JSON 查询体；
* validate：结构白名单（子句/字段/size/深度），见 :mod:`search_operator.validator`；
* execute：走既有 ES 客户端，只读检索。

mapping 与搜索都通过构造参数注入，单测不需要真实 ES。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from knowledge_engine import retrieval
from knowledge_engine.operator import (OperatorContext, OperatorError,
                                       QueryPlan, ResultSet, ValidatedPlan)
from search_operator import knowledge as mapping_knowledge
from search_operator import validator


class Nl2SearchOperator:
    name = 'nl2search'
    knowledge_types = ('INDEX', 'FIELD')

    def __init__(self, llm: Optional[Callable[..., dict]] = None,
                 mapping_loader: Optional[Callable[[str], dict]] = None,
                 searcher: Optional[Callable[[str, dict], dict]] = None):
        self._llm = llm
        self._mapping_loader = mapping_loader
        self._searcher = searcher

    # -- retrieve -----------------------------------------------------------
    def retrieve(self, question: str, *, datasource_id: str,
                 params: dict[str, Any]) -> OperatorContext:
        index = params.get('index') or datasource_id
        properties = self._load_properties(index)
        objects = mapping_knowledge.build_objects(index, properties)
        rows = [_as_row(item) for item in objects]
        hits = retrieval.lexical_search(
            question=question,
            corpus_loader=lambda _key: rows,
            corpus_key=f'mapping:{index}:{len(rows)}',
            limit=params.get('limit') or 24)
        return OperatorContext(
            text=_render(index, hits),
            objects=[{'type': hit['object_type'], 'name': hit['object_key']}
                     for hit in hits],
            sources={'lexical': len(hits)},
            fallback=not hits,
        )

    # -- plan ---------------------------------------------------------------
    def plan(self, question: str, context: OperatorContext, *,
             params: dict[str, Any]) -> QueryPlan:
        llm = self._llm or _default_llm()
        generated = llm(question=question, context=context.text,
                        model=params.get('model'))
        body = generated.get('query') if isinstance(generated, dict) else None
        if body is None:
            body = {'query': {'match_all': {}}, 'size': 10}
        return QueryPlan(query=validator.normalize(body), language='es_dsl',
                         explanation=generated.get('explanation') or '',
                         usage=generated.get('usage') or {})

    # -- validate -----------------------------------------------------------
    def validate(self, plan: QueryPlan, *,
                 params: dict[str, Any]) -> ValidatedPlan:
        index = params.get('index') or params.get('datasource_id')
        try:
            body = json.loads(plan.query)
        except (TypeError, ValueError) as error:
            raise OperatorError('SEARCH_DSL_INVALID', '查询体不是合法 JSON',
                                'validation') from error
        fields = mapping_knowledge.field_types(self._load_properties(index))
        validated = validator.validate(body, fields)
        return ValidatedPlan(query=validator.normalize(validated),
                             details={'index': index, 'fields': len(fields)})

    # -- execute ------------------------------------------------------------
    def execute(self, plan: ValidatedPlan, *,
                params: dict[str, Any]) -> ResultSet:
        index = plan.details.get('index') or params.get('index')
        body = json.loads(plan.query)
        result = self._search(index, body)
        hits = ((result.get('hits') or {}).get('hits')) or []
        columns = ['_id', '_score', '_source']
        rows = [[hit.get('_id'), hit.get('_score'), hit.get('_source')]
                for hit in hits]
        total = (result.get('hits') or {}).get('total')
        return ResultSet(columns=columns, rows=rows,
                         truncated=len(rows) >= int(body.get('size') or 10),
                         extra={'total': total})

    # -- 依赖 ---------------------------------------------------------------
    def _load_properties(self, index: str) -> dict[str, Any]:
        loader = self._mapping_loader or _default_mapping_loader
        mapping = loader(index) or {}
        # get_mapping 的返回是 {index: {"mappings": {"properties": {...}}}}
        layer = mapping.get(index) if index in mapping else next(
            (value for value in mapping.values() if isinstance(value, dict)), {})
        return ((layer or {}).get('mappings') or {}).get('properties') or {}

    def _search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        searcher = self._searcher or _default_searcher
        return searcher(index, body) or {}


def _as_row(item) -> dict[str, Any]:
    return {'object_type': item.object_type, 'object_key': item.object_key,
            'title': item.title, 'content': item.content}


def _render(index: str, hits: list[dict[str, Any]]) -> str:
    lines = [f'索引：{index}', '可用字段（只用列出的字段）：']
    for hit in hits:
        lines.append(f"- {hit['object_key']}：{hit['content']}")
    return '\n'.join(lines)


def _default_mapping_loader(index: str) -> dict[str, Any]:
    from infrastructure.search.elasticsearch import ESClientSingleton

    return ESClientSingleton.get_client().indices_get_mapping(index)


def _default_searcher(index: str, body: dict[str, Any]) -> dict[str, Any]:
    from infrastructure.search.elasticsearch import ESClientSingleton

    return ESClientSingleton.get_client().search(index, body)


def _default_llm(**kwargs) -> dict[str, Any]:
    from model.operator_client import invoke_llm
    from model.resolver import resolve

    context = kwargs.get('context') or ''
    target = resolve('llm', kwargs.get('model'))
    endpoint = {'url': target.url, 'model': target.api_model,
                'api_key': target.api_key,
                'thinking_payload': target.thinking_payload,
                'timeout': target.timeout}
    system = ('你是 Elasticsearch 查询专家。只输出一个 JSON 对象，形如'
              ' {"query": {...}, "size": 10}。只能使用给定字段；'
              '禁止 script / function_score / wildcard 等高开销子句。')
    content, usage = invoke_llm(
        [{'role': 'system', 'content': system},
         {'role': 'user', 'content': f"问题：{kwargs.get('question')}\n{context}"}],
        model=target.api_model, temperature=0.0, endpoint=endpoint,
        with_usage=True)
    from text_to_sql.sql_guard import extract_generated

    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        payload = extract_generated(content)
    return {**payload, 'usage': usage}


_operator: Optional[Nl2SearchOperator] = None


def get_operator() -> Nl2SearchOperator:
    global _operator
    if _operator is None:
        _operator = Nl2SearchOperator()
    return _operator
