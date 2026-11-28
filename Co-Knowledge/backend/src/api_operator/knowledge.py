"""OpenAPI spec → 知识对象。

一个 spec 的「结构」就是它的 paths：每个 ``METHOD /path`` 是一条能力，
参数、请求体、鉴权方式决定了它能不能被这条自然语言问题用上。
"""

from __future__ import annotations

from typing import Any

from knowledge_engine.object import KnowledgeObject

HTTP_METHODS = ('get', 'post', 'put', 'patch', 'delete', 'head')


def operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """把 spec 摊平成 ``[{method, path, operation_id, ...}]``。"""
    result: list[dict[str, Any]] = []
    for path, item in (spec.get('paths') or {}).items():
        if not isinstance(item, dict):
            continue
        shared = item.get('parameters') or []
        for method in HTTP_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            result.append({
                'method': method.upper(),
                'path': path,
                'operationId': operation.get('operationId') or f'{method}_{path}',
                'summary': operation.get('summary') or '',
                'description': operation.get('description') or '',
                'parameters': list(shared) + list(operation.get('parameters') or []),
                'requestBody': operation.get('requestBody') or {},
            })
    return result


def build_objects(title: str, spec: dict[str, Any]) -> list[KnowledgeObject]:
    objects = [KnowledgeObject(
        object_type='API',
        object_key=title,
        title=title,
        content=f'接口集合 {title}。{spec.get("info", {}).get("description") or ""}',
        metadata={'title': title},
    )]
    for operation in operations(spec):
        objects.append(KnowledgeObject(
            object_type='ENDPOINT',
            object_key=f"{operation['method']} {operation['path']}",
            title=f"{operation['method']} {operation['path']}",
            content=_describe(operation),
            metadata={key: operation[key]
                      for key in ('method', 'path', 'operationId')},
        ))
    return objects


def _describe(operation: dict[str, Any]) -> str:
    lines = [f"{operation['method']} {operation['path']}"
             f"（{operation['operationId']}）。"]
    if operation['summary']:
        lines.append(operation['summary'] + '。')
    if operation['description']:
        lines.append(operation['description'] + '。')
    params = [_param_text(item) for item in operation['parameters']]
    params = [item for item in params if item]
    if params:
        lines.append('参数：' + '；'.join(params) + '。')
    if operation['requestBody']:
        lines.append('支持请求体。')
    return ''.join(lines)


def _param_text(param: dict[str, Any]) -> str:
    if not isinstance(param, dict) or not param.get('name'):
        return ''
    required = '必填' if param.get('required') else '可选'
    location = param.get('in') or 'query'
    return f"{param['name']}（{location}，{required}）"
