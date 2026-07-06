"""Runner observability: Prometheus metrics and OpenTelemetry tracing.

Celery prefork workers are separate processes, so the metrics use the
prometheus_client multiprocess mode when PROMETHEUS_MULTIPROC_DIR is set
(the Compose and K8s deployments set it to a per-pod tmp directory); the
exposition server starts in the main worker process on METRICS_PORT.

Off by default in Compose, on by default in the K8s values. Tracing gates
on OTEL_EXPORTER_OTLP_ENDPOINT; each run executes inside one span.
"""

from __future__ import annotations

import os

from prometheus_client import Counter, Histogram

RUNS_TOTAL = Counter(
    "arena_runner_runs_total",
    "Runs finished, by terminal status and attempt outcome.",
    ["status", "outcome"],
)

RUN_DURATION = Histogram(
    "arena_runner_run_duration_seconds",
    "Wall clock duration of run execution.",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)


def metrics_enabled() -> bool:
    return os.environ.get("METRICS_ENABLED", "0").lower() in ("1", "true", "yes")


def start_metrics_server() -> None:
    """Start the exposition endpoint; called from the worker init signal."""
    if not metrics_enabled():
        return
    from prometheus_client import REGISTRY, CollectorRegistry, start_http_server

    port = int(os.environ.get("METRICS_PORT", "9100"))
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiproc_dir:
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        start_http_server(port, registry=registry)
    else:
        start_http_server(port, registry=REGISTRY)


def record_run(status: str, outcome: str | None, duration_seconds: float) -> None:
    RUNS_TOTAL.labels(status, outcome or "none").inc()
    RUN_DURATION.observe(duration_seconds)


def setup_tracing() -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "agent-arena-runner"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def run_span(run_id: str):  # noqa: ANN201 - context manager
    """A span around one run; a no-op tracer when tracing is off."""
    from opentelemetry import trace

    tracer = trace.get_tracer("agent_arena.runner")
    return tracer.start_as_current_span("execute_run", attributes={"arena.run_id": run_id})
