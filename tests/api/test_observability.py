"""Tests for issue #28: metrics and tracing gates."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import ApiSettings

SETTINGS = ApiSettings(
    database_url="postgresql+psycopg://x:x@localhost:5/x",
    redis_url="redis://localhost:6379/0",
    default_role="admin",
    default_user="local",
)


def test_metrics_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    with TestClient(create_app(SETTINGS)) as client:
        assert client.get("/metrics").status_code == 404


def test_metrics_on_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "1")
    with TestClient(create_app(SETTINGS)) as client:
        client.get("/health")
        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        assert "arena_api_requests_total" in body
        # Route template labels, not raw paths, and /metrics is not counted.
        assert 'route="/health"' in body
        assert 'route="/metrics"' not in body


def test_runner_metrics_record() -> None:
    from apps.runner.observability import RUNS_TOTAL, record_run

    before = RUNS_TOTAL.labels("complete", "success")._value.get()
    record_run("complete", "success", 1.5)
    assert RUNS_TOTAL.labels("complete", "success")._value.get() == before + 1


def test_tracing_noop_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    from apps.runner.observability import run_span, setup_tracing

    setup_tracing()
    with run_span("run-1"):
        pass
