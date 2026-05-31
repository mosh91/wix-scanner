from __future__ import annotations

from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Adds an ``X-Response-Time-Ms`` header to every response.

    This provides a general-purpose timing layer for all API requests.
    Scan-specific metric recording (latency, success, error_code, etc.) is
    still handled at the route level because it needs domain context that
    middleware cannot access.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        start = perf_counter()
        response: Response = await call_next(request)  # type: ignore[arg-type]
        duration_ms = int((perf_counter() - start) * 1000)
        response.headers["X-Response-Time-Ms"] = str(duration_ms)
        return response
