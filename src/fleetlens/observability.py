"""Structured JSON logging, request-ID propagation and Prometheus metrics."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter(
    "fleetlens_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "fleetlens_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)
PREDICTIONS = Counter("fleetlens_predictions_total", "MPG predictions served", ["model_version"])

_STD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates X-Request-ID, records latency and status per route template."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            # label by route template, not raw path, so metric cardinality stays bounded
            route_label = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, route_label, str(status)).inc()
            HTTP_LATENCY.labels(request.method, route_label).observe(elapsed)
            logging.getLogger("fleetlens.access").info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )
            request_id_var.reset(token)
