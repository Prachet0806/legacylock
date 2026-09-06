"""Rate limiting middleware (in-process, per-route buckets)."""

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from config import get_settings


# Stricter buckets for sensitive routes: (per-minute, per-hour)
_ROUTE_LIMITS: dict[str, tuple[int, int]] = {
    "/auth/login": (5, 60),
    "/auth/refresh": (10, 120),
    "/access/invite": (10, 100),
    "/vault/trigger": (5, 30),
    "/vault/reset-status": (5, 30),
}


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter with per-route buckets and bounded memory."""

    def __init__(self, app, requests_per_minute: int = 60, requests_per_hour: int = 1000, max_keys: int = 10000):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.max_keys = max_keys
        self.minute_buckets: dict[str, list[float]] = defaultdict(list)
        self.hour_buckets: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        # Only trust X-Forwarded-For when request comes from a configured trusted proxy.
        try:
            trusted = get_settings().trusted_proxy_list()
        except Exception:
            trusted = []
        client_host = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded and client_host in trusted:
            return forwarded.split(",")[0].strip()
        return client_host

    def _limits_for(self, path: str) -> tuple[int, int]:
        for prefix, limits in _ROUTE_LIMITS.items():
            if path.startswith(prefix):
                return limits
        return (self.requests_per_minute, self.requests_per_hour)

    def _cleanup_old_entries(self, bucket: list[float], window_seconds: int) -> None:
        now = time.time()
        cutoff = now - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)

    def _evict_if_needed(self) -> None:
        # Bound memory: drop oldest keys when exceeding max_keys
        if len(self.minute_buckets) > self.max_keys:
            for key in list(self.minute_buckets.keys())[: len(self.minute_buckets) - self.max_keys]:
                self.minute_buckets.pop(key, None)
                self.hour_buckets.pop(key, None)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in ("/health", "/health/", "/healthz", "/ready", "/readyz"):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        per_min, per_hour = self._limits_for(request.url.path)
        key_min = f"{client_ip}:{request.url.path.split('/')[1] if len(request.url.path.split('/')) > 1 else ''}"
        now = time.time()

        # Clean up old entries
        self._cleanup_old_entries(self.minute_buckets[key_min], 60)
        self._cleanup_old_entries(self.hour_buckets[key_min], 3600)
        self._evict_if_needed()

        # Check minute limit
        if len(self.minute_buckets[key_min]) >= per_min:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": "60"},
            )

        # Check hour limit
        if len(self.hour_buckets[key_min]) >= per_hour:
            return JSONResponse(
                status_code=429,
                content={"detail": "Hourly rate limit exceeded. Try again later."},
                headers={"Retry-After": "3600"},
            )

        # Record this request
        self.minute_buckets[key_min].append(now)
        self.hour_buckets[key_min].append(now)

        return await call_next(request)