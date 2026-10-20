"""Lightweight request monitoring: one log line per request and a short in-memory history.

Every response gets an ``X-Request-ID`` header (the same id is in the log line)
and a ``Server-Timing`` header with its duration, so slow requests show up in
the browser's network panel. ``RequestMonitor.recent()`` returns the last
requests for the local metrics endpoint. Nothing is stored on disk and no
request bodies are logged.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

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
