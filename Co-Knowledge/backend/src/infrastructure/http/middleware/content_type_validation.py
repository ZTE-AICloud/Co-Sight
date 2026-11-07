"""
Content-Type validation middleware for RAG Knowledge Base Service.

This middleware validates the Content-Type header for incoming requests to prevent
content-type based attacks and ensure proper request handling.
"""
from typing import Callable, List

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from infrastructure.logging.logutil import log


from shared.prefixes import RKB_PREFIX

class ContentTypeValidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate Content-Type header for incoming requests.

    This middleware checks the Content-Type header and ensures it matches
    expected types for the request method and endpoint.
    """

    # Allowed Content-Type patterns for each HTTP method
    # GET/HEAD: typically no body, but some clients may send Content-Type header
    ALLOWED_CONTENT_TYPES = {
        'GET': ['application/json', 'application/x-www-form-urlencoded', 'multipart/form-data', 'text/plain', 'text/html'],
        'HEAD': ['application/json', 'application/x-www-form-urlencoded', 'multipart/form-data', 'text/plain', 'text/html'],
        'DELETE': ['application/json', 'application/x-www-form-urlencoded', 'multipart/form-data'],
        'POST': ['application/json', 'application/x-www-form-urlencoded', 'multipart/form-data'],
        'PUT': ['application/json', 'application/x-www-form-urlencoded', 'multipart/form-data'],
        'PATCH': ['application/json', 'application/x-www-form-urlencoded', 'multipart/form-data'],
    }

    # 这些前缀下的请求体 Content-Type 由路由层按请求体/部件的
    # 判定表接管（见 ``infrastructure/http/content_type.py``），中间件必须整体放行 ——
    # 它的「POST 只允许 json/form/multipart」规则会把「无 Content-Type」「text/plain」
    # 在路由之前截成 415 裸 JSON。
    ROUTE_VALIDATED_PREFIXES = [
        RKB_PREFIX,
    ]

    # Content-Type header name
    CONTENT_TYPE_HEADER = 'content-type'

    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        """
        Validate Content-Type header before processing the request.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            JSONResponse with error or the response from the next handler
        """
        # Skip validation for route-validated prefixes (see ROUTE_VALIDATED_PREFIXES)
        if self._is_route_validated_prefix(self._route_path(request)):
            return await call_next(request)

        method = request.method
        content_type = request.headers.get(self.CONTENT_TYPE_HEADER, '').lower()

        # Extract the content-type without parameters (e.g., charset)
        if ';' in content_type:
            content_type = content_type.split(';')[0].strip()

        # Check if Content-Type is allowed for this method
        if method in self.ALLOWED_CONTENT_TYPES:
            allowed_types = self.ALLOWED_CONTENT_TYPES[method]

            # Allow any content type for methods that don't typically have bodies
            if method in ['GET', 'HEAD'] and not content_type:
                return await call_next(request)

            if content_type and not self._is_content_type_allowed(content_type, allowed_types):
                log.warning(
                    f"[ContentTypeValidation] Invalid Content-Type '{content_type}' "
                    f"for {method} request to {request.url.path}"
                )
                return JSONResponse(
                    status_code=415,
                    content={
                        'code': -1,
                        'message': f'Unsupported Content-Type: {content_type}. '
                                   f'Allowed types for {method}: {", ".join(allowed_types)}'
                    }
                )

        return await call_next(request)

    def _is_route_validated_prefix(self, path: str) -> bool:
        """
        Check if the path belongs to a route-validated prefix.

        Args:
            path: The request path (without root_path)

        Returns:
            True if the path is under one of the route-validated prefixes
        """
        for prefix in self.ROUTE_VALIDATED_PREFIXES:
            if path == prefix or path.startswith(prefix + '/'):
                return True
        return False

    def _route_path(self, request: Request) -> str:
        """
        Request path with the gateway root_path (URL_CONTEXT_PATH) stripped.

        Middleware runs **before** routing, so ``scope['route']`` is not available here;
        the root_path prefix has to be stripped manually or the prefix checks break
        under a gateway prefix.
        """
        path = request.url.path
        root_path = request.scope.get('root_path') or ''
        if root_path and path.startswith(root_path):
            return path[len(root_path):] or '/'
        return path

    def _is_content_type_allowed(self, content_type: str, allowed_types: List[str]) -> bool:
        """
        Check if the content type matches any of the allowed types.

        Args:
            content_type: The request content type
            allowed_types: List of allowed content types

        Returns:
            True if allowed, False otherwise
        """
        for allowed in allowed_types:
            if content_type == allowed or content_type.startswith(allowed + ';'):
                return True
        return False


def get_content_type_validation_middleware() -> type:
    """
    Factory function to get the ContentTypeValidationMiddleware class.

    Returns:
        ContentTypeValidationMiddleware class
    """
    return ContentTypeValidationMiddleware
