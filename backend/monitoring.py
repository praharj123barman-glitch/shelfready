"""Lightweight request monitoring: one log line per request and a short in-memory history.

Every response gets an ``X-Request-ID`` header (the same id is in the log line)
and a ``Server-Timing`` header with its duration, so slow requests show up in
the browser's network panel. ``RequestMonitor.recent()`` returns the last
requests for the local metrics endpoint. Nothing is stored on disk and no
request bodies are logged.

``is_local`` tells requests made on this machine from ones forwarded by the
demo's tunnel, and ``RateLimiter`` caps how often one internet visitor can
start reviews or ask the AI.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("api.requests")
HISTORY = 100  # requests kept in memory


class RequestRecord(BaseModel):
    request_id: str
    method: str
    path: str
    status: int
    duration_ms: float
    at: str
    error: str | None = None  # exception class name for unhandled errors


class RequestMonitor:
    def __init__(self, size: int = HISTORY) -> None:
        self._records: deque[RequestRecord] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, record: RequestRecord) -> None:
        with self._lock:
            self._records.append(record)

    def recent(self) -> list[RequestRecord]:
        with self._lock:
            return list(reversed(self._records))


LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
# Headers a tunnel or reverse proxy adds. The live demo's tunnel (cloudflared) connects from 127.0.0.1,
# so a request carrying any of these came from the internet even though its address looks local.
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip", "forwarded")


def is_local(request: Request) -> bool:
    """True only for a request made on this machine itself, not one forwarded by the tunnel."""
    host = request.client.host if request.client else ""
    return host in LOCAL_CLIENTS and not any(header in request.headers for header in PROXY_HEADERS)


def visitor(request: Request) -> str:
    """Who is asking: the address the tunnel reports for the visitor, else the connection's address."""
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
    return forwarded.strip() or (request.client.host if request.client else "unknown")


class RateLimiter:
    """At most ``limit`` requests per visitor in any ``window`` seconds, kept in memory.

    Protects a public demo from one visitor using up the AI quota or the machine (each review
    can take a 25 MB upload, OCR and several model calls). Requests made on this machine are
    never limited."""

    def __init__(self, limit: int, window: float, what: str) -> None:
        self.limit, self.window, self.what = limit, window, what
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:  # used as a FastAPI dependency
        if is_local(request):
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(visitor(request), deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                wait = int(self.window - (now - hits[0])) + 1
                raise HTTPException(429, f"Too many {self.what} from your address. Please try again in {wait} s.")
            hits.append(now)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, monitor: RequestMonitor) -> None:
        super().__init__(app)
        self.monitor = monitor

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:8]
        start = time.perf_counter()
        status, error = 500, None
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as exc:  # recorded, then re-raised for FastAPI's normal 500 handling
            error = type(exc).__name__
            raise
        finally:
            ms = round((time.perf_counter() - start) * 1000, 1)
            self.monitor.add(RequestRecord(
                request_id=request_id, method=request.method, path=request.url.path, status=status,
                duration_ms=ms, at=datetime.now(timezone.utc).isoformat(timespec="seconds"), error=error,
            ))
            log.info("%s %s %s %d %.0fms%s", request_id, request.method, request.url.path, status, ms,
                     f" {error}" if error else "")
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={ms}"
        return response
