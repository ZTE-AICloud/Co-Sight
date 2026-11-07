"""Golden route census for the public API.

The architecture refactor moves router files and handler functions around.
Two things must not drift while doing that:

1. the ordered ``(method, path, operationId)`` census of the FastAPI app;
2. the operationIds recorded in ``contracts/openapi/rkb-api.yaml``.

FastAPI derives a default operationId from the handler function name, so a
seemingly harmless rename silently changes the published contract.  The
golden file is intentionally checked in; regenerate it deliberately with::

    UPDATE_ROUTE_CENSUS=1 python -m pytest tests/test_route_census.py

The census includes the catch-all route on purpose: it must stay last.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml
from fastapi.routing import APIRoute, Mount

from app import app
from route_helpers import api_routes as iter_api_routes, iter_routes
from shared.prefixes import RKB_PREFIX

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
GOLDEN = Path(__file__).with_name('fixtures') / 'route_census.json'
OPENAPI = REPO_ROOT / 'contracts' / 'openapi' / 'rkb-api.yaml'

#: FastAPI's own default; duplicated here to avoid the deprecated helper.
def _operation_id(route: APIRoute, method: str) -> str:
    if route.operation_id:
        return route.operation_id
    return re.sub(r'\W', '_', f'{route.name}{route.path_format}_{method.lower()}')


def _census() -> list[dict]:
    items: list[dict] = []
    for route in iter_routes(app):
        if hasattr(route, 'methods') and hasattr(route, 'path_format'):
            for method in sorted(route.methods or []):
                items.append({
                    'method': method,
                    'path': route.path_format,
                    'operation_id': _operation_id(route, method),
                })
        elif isinstance(route, Mount):
            items.append({
                'method': 'MOUNT',
                'path': route.path,
                'operation_id': route.name or '',
            })
    return sorted(items, key=lambda item: (item['path'], item['method']))


def _load_golden() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding='utf-8'))


def test_route_census_matches_golden():
    current = _census()
    if os.environ.get('UPDATE_ROUTE_CENSUS') == '1':
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')
    golden = _load_golden()
    assert current == golden, (
        'Route census changed. If this is intentional, regenerate with '
        'UPDATE_ROUTE_CENSUS=1 and review the diff.'
    )


def test_catch_all_is_registered_last():
    api_routes = iter_api_routes(app)
    # ``path_format`` strips the ``:path`` converter, so match the raw path.
    catch_all = [route for route in api_routes
                 if route.path == f'{RKB_PREFIX}/{{unknown_path:path}}']
    assert len(catch_all) == 1, 'expected exactly one kb_api catch-all route'
    assert api_routes[-1] is catch_all[0], (
        'the catch-all must be the last APIRoute; otherwise it swallows '
        '/query, /agent, /mcp or /retrieval/graph'
    )


def test_openapi_operation_ids_match_runtime():
    """Every operation in the published contract still maps to the same id."""
    contract = yaml.safe_load(OPENAPI.read_text(encoding='utf-8'))
    by_path: dict[tuple[str, str], object] = {}
    for route in iter_api_routes(app):
        for method in route.methods or []:
            by_path[(route.path_format, method.lower())] = route

    mismatches = []
    for path, operations in contract.get('paths', {}).items():
        for method, operation in operations.items():
            if method not in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}:
                continue
            route = by_path.get((f'{RKB_PREFIX}{path}', method))
            if route is None:
                mismatches.append(f'missing runtime route: {method.upper()} {path}')
                continue
            expected = operation.get('operationId')
            actual = _operation_id(route, method)
            if expected != actual:
                mismatches.append(
                    f'{method.upper()} {path}: contract={expected!r} runtime={actual!r}')

    assert not mismatches, '\n'.join(mismatches)
