"""
Optional API key authentication middleware.

This middleware is disabled by default. When enabled (via settings.require_api_key),
it validates API keys and scopes requests to specific publishers.

Usage:
    # Enable in settings
    require_api_key: true
    api_keys:
      "key-abc123": 55  # Maps key to publisher_id
      "key-xyz789": 32

    # Request header
    X-API-Key: key-abc123
"""

from typing import Callable, Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from portal.config import settings


class OptionalApiKeyMiddleware(BaseHTTPMiddleware):
    """
    Optional API key authentication middleware.

    When enabled, validates the X-API-Key header and attaches the
    associated publisher_id to the request state.

    Disabled by default - set require_api_key=True in settings to enable.
    """

    # Paths that don't require authentication
    PUBLIC_PATHS = {
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    # Path prefixes that don't require authentication
    PUBLIC_PREFIXES = (
        "/ui/",
        "/docs",
        "/redoc",
    )

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        # Skip if authentication is disabled
        if not settings.require_api_key:
            return await call_next(request)

        # Skip public paths
        path = request.url.path
        if path in self.PUBLIC_PATHS or path.startswith(self.PUBLIC_PREFIXES):
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Missing API key. Include X-API-Key header.",
                    "error_code": "MISSING_API_KEY",
                },
            )

        # Validate API key
        publisher_id = settings.api_keys.get(api_key)

        if publisher_id is None:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Invalid API key.",
                    "error_code": "INVALID_API_KEY",
                },
            )

        # Attach publisher_id to request state for downstream handlers
        request.state.authenticated_publisher_id = publisher_id
        request.state.api_key = api_key

        # Optionally enforce scope (publisher can only access their own data)
        if settings.enforce_api_key_scope:
            # Check if request is for a specific publisher
            path_parts = path.split("/")
            if "publishers" in path_parts:
                try:
                    pub_idx = path_parts.index("publishers")
                    if pub_idx + 1 < len(path_parts):
                        requested_publisher_id = int(path_parts[pub_idx + 1])
                        if requested_publisher_id != publisher_id:
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "detail": f"Access denied. Your API key is scoped to publisher {publisher_id}.",
                                    "error_code": "SCOPE_VIOLATION",
                                },
                            )
                except (ValueError, IndexError):
                    pass  # Not a publisher-scoped request

        return await call_next(request)


def get_authenticated_publisher_id(request: Request) -> Optional[int]:
    """
    Get the authenticated publisher ID from request state.

    Returns None if authentication is disabled or not present.
    """
    return getattr(request.state, "authenticated_publisher_id", None)


def require_authenticated_publisher(request: Request) -> int:
    """
    Require authentication and return the publisher ID.

    Raises HTTPException if not authenticated.
    """
    publisher_id = get_authenticated_publisher_id(request)
    if publisher_id is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )
    return publisher_id
