"""Route-table traversal that works across FastAPI versions.

FastAPI 0.140+ keeps included routers as ``_IncludedRouter`` objects instead of
flattening them into ``app.routes``.  Their effective routes are exposed via
``effective_candidates()``; this helper yields direct routes and included ones
in registration order, so the route-order guards stay meaningful.
"""

from __future__ import annotations

from fastapi.routing import APIRoute, Mount


def _walk(routes):
    for route in routes:
        if isinstance(route, (APIRoute, Mount)):
            yield route
        elif hasattr(route, 'effective_candidates'):
            # Included routers can be nested; recurse until real routes.
            yield from _walk(route.effective_candidates())
        else:
            yield route


def iter_routes(app):
    yield from _walk(app.routes)


def route_paths(app) -> list[str]:
    return [getattr(route, 'path', '') for route in iter_routes(app)]


def api_routes(app) -> list:
    """Direct ``APIRoute`` objects and their ``_EffectiveRouteContext`` peers."""
    return [route for route in iter_routes(app)
            if hasattr(route, 'methods') and hasattr(route, 'path_format')]
