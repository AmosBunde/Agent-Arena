"""API observability: Prometheus metrics and OpenTelemetry tracing.

Off by default in Compose, on by default in the K8s values
(system-design.md, Observability): metrics gate on METRICS_ENABLED and
tracing gates entirely on OTEL_EXPORTER_OTLP_ENDPOINT being set. Neither is
required for the service to function.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, make_asgi_app

REQUEST_COUNT_NAME = "arena_api_requests_total"
REQUEST_LATENCY_NAME = "arena_api_request_duration_seconds"


def metrics_enabled() -> bool:
    return os.environ.get("METRICS_ENABLED", "0").lower() in ("1", "true", "yes")


def setup_observability(app: FastAPI) -> None:
    if metrics_enabled():
        _setup_metrics(app)
    _setup_tracing(app)


def _setup_metrics(app: FastAPI) -> None:
    registry = CollectorRegistry()
    request_count = Counter(
        REQUEST_COUNT_NAME,
        "API requests by method, route template, and status code.",
        ["method", "route", "status"],
        registry=registry,
    )
    request_latency = Histogram(
        REQUEST_LATENCY_NAME,
        "API request duration in seconds by method and route template.",
        ["method", "route"],
        registry=registry,
    )

    @app.middleware("http")
    async def record_metrics(request: Request, call_next):  # noqa: ANN001, ANN202
        start = time.monotonic()
        response: Response = await call_next(request)
        route = request.scope.get("route")
        # The route template, not the raw path: bounded label cardinality.
        template = getattr(route, "path", "unmatched")
        if template != "/metrics":
            request_count.labels(request.method, template, str(response.status_code)).inc()
            request_latency.labels(request.method, template).observe(time.monotonic() - start)
        return response

    app.mount("/metrics", make_asgi_app(registry=registry))


def _setup_tracing(app: FastAPI) -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "agent-arena-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("agent_arena.api")

    @app.middleware("http")
    async def trace_requests(request: Request, call_next):  # noqa: ANN001, ANN202
        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
            },
        ) as span:
            response: Response = await call_next(request)
            span.set_attribute("http.response.status_code", response.status_code)
            return response
