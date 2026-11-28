"""NL2API 算子：spec 知识 → 检索 → 生成调用计划 → 校验 → 执行。

安全边界有三条，都在 ``validate`` 里：

1. **只允许 spec 里声明过的 method + path**——不是「以 server 开头」就算数；
2. **URL 只能由 spec 的 server 前缀 + 已声明的 path 拼出**，且拼完必须仍以该前缀
   开头（挡住 ``//evil`` / ``..`` / ``@evil`` 这类路径注入）；
3. **参数只允许 spec 声明的名字**，query 参数不得覆盖 path 占位符。

执行用注入的 HTTP 客户端，单测不联网。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from api_operator import knowledge as spec_knowledge
from knowledge_engine import retrieval
from knowledge_engine.operator import (OperatorContext, OperatorError,
                                       QueryPlan, ResultSet, ValidatedPlan)

MAX_BODY_CHARS = 64 * 1024


class Nl2ApiOperator:
    name = 'nl2api'
    knowledge_types = ('API', 'ENDPOINT')

    def __init__(self, llm: Optional[Callable[..., dict]] = None,
                 spec_loader: Optional[Callable[[str], dict]] = None,
                 http_call: Optional[Callable[..., dict]] = None):
        self._llm = llm
        self._spec_loader = spec_loader
        self._http_call = http_call

    # -- retrieve -----------------------------------------------------------
    def retrieve(self, question: str, *, datasource_id: str,
                 params: dict[str, Any]) -> OperatorContext:
        spec = self._spec(datasource_id, params)
        objects = spec_knowledge.build_objects(datasource_id, spec)
        rows = [{'object_type': item.object_type, 'object_key': item.object_key,
                 'title': item.title, 'content': item.content} for item in objects]
        hits = retrieval.lexical_search(
            question=question, corpus_loader=lambda _key: rows,
            corpus_key=f'spec:{datasource_id}:{len(rows)}',
            limit=params.get('limit') or 24)
        return OperatorContext(
            text='\n'.join([f'接口集合：{datasource_id}']
                           + [f"- {hit['content']}" for hit in hits]),
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
        call = {
            'method': str(generated.get('method') or '').upper(),
            'path': generated.get('path') or '',
            'pathParams': generated.get('pathParams') or {},
            'query': generated.get('query') or {},
            'body': generated.get('body'),
        }
        return QueryPlan(query=json.dumps(call, ensure_ascii=False, sort_keys=True),
                         language='http', explanation=generated.get('explanation') or '',
                         usage=generated.get('usage') or {})

    # -- validate -----------------------------------------------------------
    def validate(self, plan: QueryPlan, *,
                 params: dict[str, Any]) -> ValidatedPlan:
        try:
            call = json.loads(plan.query)
        except (TypeError, ValueError) as error:
            raise OperatorError('API_PLAN_INVALID', '调用计划不是合法 JSON',
                                'validation') from error
        spec = self._spec(params.get('api') or params.get('datasource_id'), params)
        operation = _find_operation(spec, call.get('method'), call.get('path'))
        if operation is None:
            raise OperatorError(
                'API_ENDPOINT_NOT_ALLOWED',
                f"接口 {call.get('method')} {call.get('path')} 不在该 spec 内",
                'validation')

        declared = {item.get('name') for item in operation['parameters']
                    if isinstance(item, dict)}
        declared |= {item.get('name') for item in
                     (operation.get('requestBody') or {}).get('parameters') or []
                     if isinstance(item, dict)}
        for name in list(call.get('query') or {}) + list(call.get('pathParams') or {}):
            if declared and name not in declared:
                raise OperatorError('API_PARAM_NOT_ALLOWED',
                                    f'参数 {name} 不在接口声明里', 'validation')
        for item in operation['parameters']:
            if isinstance(item, dict) and item.get('required') and item.get('in') == 'path':
                if item['name'] not in (call.get('pathParams') or {}):
                    raise OperatorError('API_PARAM_MISSING',
                                        f"缺少路径参数 {item['name']}", 'validation')

        url = _build_url(spec, operation['path'], call.get('pathParams') or {})
        body = call.get('body')
        if body is not None and len(json.dumps(body, ensure_ascii=False)) > MAX_BODY_CHARS:
            raise OperatorError('API_BODY_TOO_LARGE', '请求体过大', 'validation')
        return ValidatedPlan(query=json.dumps(call, ensure_ascii=False, sort_keys=True),
                             details={'url': url, 'method': operation['method']})

    # -- execute ------------------------------------------------------------
    def execute(self, plan: ValidatedPlan, *,
                params: dict[str, Any]) -> ResultSet:
        call = json.loads(plan.query)
        caller = self._http_call or _default_http_call
        response = caller(method=plan.details['method'], url=plan.details['url'],
                          params=call.get('query') or {}, json_body=call.get('body'),
                          timeout=params.get('timeout') or 30)
        payload = response.get('json')
        rows = [[payload]] if payload is not None else []
        return ResultSet(columns=['response'], rows=rows,
                         extra={'status': response.get('status')})

    # -- 依赖 ---------------------------------------------------------------
    def _spec(self, key: str, params: dict[str, Any]) -> dict[str, Any]:
        if isinstance(params.get('spec'), dict):
            return params['spec']
        loader = self._spec_loader or _default_spec_loader
        spec = loader(key) or {}
        if not spec.get('paths'):
            raise OperatorError('API_SPEC_NOT_FOUND', f'找不到接口集合 {key}',
                                'retrieval')
        return spec


def _find_operation(spec: dict[str, Any], method: Any,
                    path: Any) -> Optional[dict[str, Any]]:
    method = str(method or '').upper()
    path = str(path or '')
    for operation in spec_knowledge.operations(spec):
        if operation['method'] == method and operation['path'] == path:
            return operation
    return None


def _build_url(spec: dict[str, Any], path: str,
               path_params: dict[str, Any]) -> str:
    servers = spec.get('servers') or [{}]
    base = str((servers[0] or {}).get('url') or '').rstrip('/')
    if not base.startswith(('http://', 'https://')):
        raise OperatorError('API_SPEC_INVALID', 'spec 缺少合法的 server 前缀',
                            'validation')
    filled = path
    for name, value in (path_params or {}).items():
        if any(char in str(value) for char in ('/', '..', '@', '\\')):
            raise OperatorError('API_PARAM_NOT_ALLOWED',
                                f'路径参数 {name} 含非法字符', 'validation')
        filled = filled.replace('{' + str(name) + '}', str(value))
    if '{' in filled:
        raise OperatorError('API_PARAM_MISSING', '仍有未替换的路径参数', 'validation')
    url = f'{base}{filled}'
    if not url.startswith(base + '/') and url != base:
        raise OperatorError('API_ENDPOINT_NOT_ALLOWED', 'URL 越出 spec 的 server 前缀',
                            'validation')
    return url


def _default_spec_loader(key: str) -> dict[str, Any]:
    raise OperatorError('API_SPEC_NOT_FOUND',
                        f'未配置接口集合 {key}；请通过 params.spec 或注册 loader',
                        'retrieval')


def _default_http_call(*, method: str, url: str, params: dict[str, Any],
                       json_body: Any, timeout: int) -> dict[str, Any]:
    from infrastructure.http import egress

    if params:
        url = f'{url}?{urlencode(params)}'
    response = egress.request(method, url, json=json_body, timeout=timeout)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return {'status': response.status_code, 'json': payload}


def _default_llm(**kwargs) -> dict[str, Any]:
    from model.operator_client import invoke_llm
    from model.resolver import resolve

    target = resolve('llm', kwargs.get('model'))
    endpoint = {'url': target.url, 'model': target.api_model,
                'api_key': target.api_key,
                'thinking_payload': target.thinking_payload,
                'timeout': target.timeout}
    system = ('你是 API 调用规划器。只输出 JSON：{"method","path","pathParams",'
              '"query","body"}。method+path 必须取自给定接口列表。')
    content, usage = invoke_llm(
        [{'role': 'system', 'content': system},
         {'role': 'user', 'content': f"问题：{kwargs.get('question')}\n{kwargs.get('context')}"}],
        model=target.api_model, temperature=0.0, endpoint=endpoint, with_usage=True)
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as error:
        raise OperatorError('API_PLAN_INVALID', '模型没有返回可解析的 JSON',
                            'llm') from error
    return {**payload, 'usage': usage}


_operator: Optional[Nl2ApiOperator] = None


def get_operator() -> Nl2ApiOperator:
    global _operator
    if _operator is None:
        _operator = Nl2ApiOperator()
    return _operator
