"""``contracts/openapi/rkb-api.yaml`` 必须与运行时路由全量一致。

主应用刻意不暴露 Swagger；这份静态 OpenAPI 是对外契约。测试钉住：
1. 文件内容 == ``build_rkb_openapi(app, version=contracts/VERSION)``；
2. 运行时每一条 REST 路由（除兜底与协议端点）都出现在契约里，反向也成立；
3. 契约自身没有悬空 ``$ref``，所有非 2xx 都引用 RFC 9457 ``Problem``。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app import app
from infrastructure.http.openapi_contract import (build_rkb_openapi,
                                                   normalize_object_schemas)
from route_helpers import api_routes as iter_api_routes
from shared.prefixes import RKB_PREFIX

CONTRACTS = Path(__file__).resolve().parents[2] / 'contracts'
SNAPSHOT = CONTRACTS / 'openapi' / 'rkb-api.yaml'
VERSION = (CONTRACTS / 'VERSION').read_text(encoding='utf-8').strip()


def _short(path: str) -> str:
    return path[len(RKB_PREFIX):] or '/'


def _runtime_operations() -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for route in iter_api_routes(app):
        path = getattr(route, 'path', '')
        if not path.startswith(RKB_PREFIX) or '{unknown_path:path}' in path:
            continue
        for method in route.methods or ():
            if method in {'HEAD', 'OPTIONS'}:
                continue
            operations.add((method.lower(), _short(path)))
    return operations


def _snapshot() -> dict:
    return yaml.safe_load(SNAPSHOT.read_text(encoding='utf-8'))


def test_snapshot_matches_runtime_schema():
    snapshot = _snapshot()
    assert build_rkb_openapi(app, version=VERSION) == snapshot
    assert snapshot['info']['version'] == VERSION


def test_every_rest_route_is_documented_and_vice_versa():
    snapshot = _snapshot()
    documented = {
        (method, path)
        for path, operations in snapshot['paths'].items()
        for method in operations
    }
    assert _runtime_operations() == documented


def _walk_refs(node):
    if isinstance(node, dict):
        ref = node.get('$ref')
        if isinstance(ref, str):
            yield ref
        for value in node.values():
            yield from _walk_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_refs(value)


def _resolve_pointer(schema: dict, ref: str):
    assert ref.startswith('#/'), f'只支持本地引用：{ref}'
    current = schema
    for part in ref[2:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        assert isinstance(current, dict) and part in current, f'悬空 $ref：{ref}'
        current = current[part]
    return current


def test_free_form_mapping_schemas_are_pydantic_version_stable():
    """The contract must be identical on Pydantic 2.9 and 2.11.

    2.11 adds ``additionalProperties: true`` to free-form mappings; 2.9 omits it.
    Normalization must add it exactly once, in the key order used by the
    committed YAML, and must not touch explicit models or constrained maps.
    """
    schema = {
        'free': {'type': 'object', 'title': 'Free', 'default': {}},
        'model': {'type': 'object', 'title': 'Model', 'properties': {}},
        'mapped': {'type': 'object', 'additionalProperties': {'type': 'string'}},
    }

    normalize_object_schemas(schema)

    assert list(schema['free']) == ['additionalProperties', 'type', 'title', 'default']
    assert schema['free']['additionalProperties'] is True
    assert 'additionalProperties' not in schema['model']
    assert schema['mapped']['additionalProperties'] == {'type': 'string'}


def test_all_refs_resolve_and_non_2xx_are_problem():
    snapshot = _snapshot()
    for ref in _walk_refs(snapshot):
        _resolve_pointer(snapshot, ref)

    for path, operations in snapshot['paths'].items():
        for method, operation in operations.items():
            responses = operation['responses']
            assert any(str(code).startswith('2') for code in responses), (method, path)
            for code in ('4XX', '5XX'):
                assert responses[code] == {'$ref': '#/components/responses/Problem'}, \
                    (method, path, code)
            assert '422' not in responses, (method, path)
            assert 'HTTPValidationError' not in str(responses), (method, path)
            assert operation.get('summary'), (method, path)
            assert operation.get('tags'), (method, path)
