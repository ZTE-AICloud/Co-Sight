"""NL2Graph 算子：schema 知识 → 检索 → 生成图查询 → 校验 → 执行。

四段与其它算子同构。安全边界在 validate：

1. ``query_type`` 只允许 entity / edge / path / sub_graph（运行时认的四种）；
2. 实体类型、边类型必须在 schema 里声明过；
3. 深度上限 3；
4. 不接受任何自由查询文本——生成的永远是结构化 payload，由 graph 域的
   唯一入口 ``graph_query_api.query`` 执行，不给模型自由拼查询语言的机会。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from knowledge_engine import retrieval
from knowledge_engine.operator import (OperatorContext, OperatorError,
                                       QueryPlan, ResultSet, ValidatedPlan)

QUERY_TYPES = ('entity', 'edge', 'path', 'sub_graph')
MAX_DEPTH = 3


class Nl2GraphOperator:
    name = 'nl2graph'
    knowledge_types = ('SCHEMA', 'ENTITY_TYPE', 'EDGE_TYPE')

    def __init__(self, llm: Optional[Callable[..., dict]] = None,
                 schema_loader: Optional[Callable[[str], dict]] = None,
                 query_runner: Optional[Callable[[dict], dict]] = None):
        self._llm = llm
        self._schema_loader = schema_loader
        self._query_runner = query_runner

    def retrieve(self, question: str, *, datasource_id: str,
                 params: dict[str, Any]) -> OperatorContext:
        schema = self._schema(datasource_id, params)
        objects = build_objects(datasource_id, schema)
        rows = [{'object_type': item['type'], 'object_key': item['name'],
                 'title': item['name'], 'content': item['content']}
                for item in objects]
        hits = retrieval.lexical_search(
            question=question, corpus_loader=lambda _key: rows,
            corpus_key=f'graph:{datasource_id}:{len(rows)}',
            limit=params.get('limit') or 24)
        return OperatorContext(
            text='\n'.join([f'图谱 {datasource_id}：']
                           + [f"- {hit['content']}" for hit in hits]),
            objects=[{'type': hit['object_type'], 'name': hit['object_key']}
                     for hit in hits],
            sources={'lexical': len(hits)}, fallback=not hits)

    def plan(self, question: str, context: OperatorContext, *,
             params: dict[str, Any]) -> QueryPlan:
        llm = self._llm or _default_llm()
        generated = llm(question=question, context=context.text,
                        model=params.get('model'))
        payload = {key: generated.get(key) for key in
                   ('query_type', 'entityTypes', 'edgeTypes', 'properties', 'depth')
                   if generated.get(key) is not None}
        return QueryPlan(query=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                         language='graph_query',
                         explanation=generated.get('explanation') or '',
                         usage=generated.get('usage') or {})

    def validate(self, plan: QueryPlan, *,
                 params: dict[str, Any]) -> ValidatedPlan:
        try:
            payload = json.loads(plan.query)
        except (TypeError, ValueError) as error:
            raise OperatorError('GRAPH_QUERY_INVALID', '查询体不是合法 JSON',
                                'validation') from error
        query_type = payload.get('query_type')
        if query_type not in QUERY_TYPES:
            raise OperatorError('GRAPH_QUERY_INVALID',
                                f"query_type 必须是 {'/'.join(QUERY_TYPES)}",
                                'validation')
        depth = payload.get('depth', 1)
        if not isinstance(depth, int) or isinstance(depth, bool) \
                or not 1 <= depth <= MAX_DEPTH:
            raise OperatorError('GRAPH_QUERY_INVALID', f'深度必须是 1–{MAX_DEPTH}',
                                'validation')

        schema = self._schema(params.get('graph') or params.get('datasource_id'),
                              params)
        entity_types = set(schema.get('entity_types') or {})
        edge_types = set(schema.get('edge_types') or {})
        for name in payload.get('entityTypes') or []:
            if name not in entity_types:
                raise OperatorError('GRAPH_TYPE_NOT_ALLOWED',
                                    f'实体类型 {name} 不在 schema 里', 'validation')
        for name in payload.get('edgeTypes') or []:
            if name not in edge_types:
                raise OperatorError('GRAPH_TYPE_NOT_ALLOWED',
                                    f'边类型 {name} 不在 schema 里', 'validation')

        graph_payload = {
            'kb_id': params.get('kb_id') or params.get('datasource_id'),
            'query_type': query_type,
            'filters': [{
                'entity_type': payload.get('entityTypes') or None,
                'edge_type': payload.get('edgeTypes') or None,
                'properties': payload.get('properties') or None,
            }],
            'depth': depth,
        }
        return ValidatedPlan(
            query=json.dumps(graph_payload, ensure_ascii=False, sort_keys=True),
            details={'queryType': query_type, 'depth': depth})

    def execute(self, plan: ValidatedPlan, *,
                params: dict[str, Any]) -> ResultSet:
        runner = self._query_runner or _default_query_runner
        result = runner(json.loads(plan.query)) or {}
        entities = result.get('entities') or result.get('nodes') or []
        edges = result.get('edges') or []
        rows = [[item.get('name') or item.get('id'), 'entity'] for item in entities]
        rows += [[item.get('name') or item.get('id'), 'edge'] for item in edges]
        return ResultSet(columns=['name', 'kind'], rows=rows,
                         extra={'entityCount': len(entities),
                                'edgeCount': len(edges)})

    def _schema(self, key: Optional[str],
                params: dict[str, Any]) -> dict[str, Any]:
        if isinstance(params.get('schema'), dict):
            return params['schema']
        loader = self._schema_loader or _default_schema_loader
        schema = loader(key or '') or {}
        if not schema.get('entity_types'):
            raise OperatorError('GRAPH_SCHEMA_NOT_FOUND',
                                f'找不到图谱 {key} 的 schema', 'retrieval')
        return schema


def build_objects(kb_id: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    """schema → 知识对象（SCHEMA / ENTITY_TYPE / EDGE_TYPE）。"""
    objects = [{'type': 'SCHEMA', 'name': kb_id,
                'content': f'图谱 {kb_id}：'
                           f"{len(schema.get('entity_types') or {})} 类实体、"
                           f"{len(schema.get('edge_types') or {})} 类关系"}]
    for name, spec in (schema.get('entity_types') or {}).items():
        props = '、'.join((spec or {}).get('properties') or []) or '无属性'
        objects.append({'type': 'ENTITY_TYPE', 'name': name,
                        'content': f'实体类型 {name}。属性：{props}'})
    for name, spec in (schema.get('edge_types') or {}).items():
        props = '、'.join((spec or {}).get('properties') or []) or '无属性'
        objects.append({'type': 'EDGE_TYPE', 'name': name,
                        'content': f'关系类型 {name}。属性：{props}'})
    return objects


def _default_schema_loader(kb_id: str) -> dict[str, Any]:
    from graph.repository import graph_schema_store

    row = (graph_schema_store.get_schema_by_id(kb_id)
           or graph_schema_store.get_schema_by_name(kb_id))
    if not row:
        return {}
    return normalize(row.get('schemaObj') or row.get('schema_obj') or {})


def normalize(schema: Any) -> dict[str, Any]:
    """把 graph 域的 schema 对象收敛成统一形状（顶点/边 → 类型 + 属性名）。"""
    if not isinstance(schema, dict):
        return {}
    entities = {name: {'properties': _properties(spec)}
                for name, spec in (schema.get('vertices')
                                   or schema.get('entity_types') or {}).items()}
    edges = {name: {'properties': _properties(spec)}
             for name, spec in (schema.get('edges')
                                or schema.get('edge_types') or {}).items()}
    return {'entity_types': entities, 'edge_types': edges}


def _properties(spec: Any) -> list[str]:
    if isinstance(spec, list):
        return [str(item.get('name') if isinstance(item, dict) else item)
                for item in spec]
    if isinstance(spec, dict):
        value = spec.get('properties') or spec.get('attrs') or []
        return [str(item.get('name') if isinstance(item, dict) else item)
                for item in value]
    return []


def _default_query_runner(payload: dict[str, Any]) -> dict[str, Any]:
    from graph.service import graph_query_api

    return graph_query_api.query(payload)


def _default_llm(**kwargs) -> dict[str, Any]:
    from model.operator_client import invoke_llm
    from model.resolver import resolve

    target = resolve('llm', kwargs.get('model'))
    system = ('你是图查询规划器。只输出 JSON：'
              '{"query_type":"entity|edge|path|sub_graph","entityTypes":[],'
              '"edgeTypes":[],"properties":{},"depth":1}。'
              '只能用给定 schema 里的类型名。')
    content, usage = invoke_llm(
        [{'role': 'system', 'content': system},
         {'role': 'user',
          'content': f"问题：{kwargs.get('question')}\n{kwargs.get('context')}"}],
        model=target.api_model, temperature=0.0,
        endpoint={'url': target.url, 'model': target.api_model,
                  'api_key': target.api_key,
                  'thinking_payload': target.thinking_payload,
                  'timeout': target.timeout},
        with_usage=True)
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as error:
        raise OperatorError('GRAPH_QUERY_INVALID', '模型没有返回可解析的 JSON',
                            'llm') from error
    return {**payload, 'usage': usage}


_operator: Optional[Nl2GraphOperator] = None


def get_operator() -> Nl2GraphOperator:
    global _operator
    if _operator is None:
        _operator = Nl2GraphOperator()
    return _operator
