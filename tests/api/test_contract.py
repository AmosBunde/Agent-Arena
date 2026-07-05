"""Contract tests for issue #9.

The FastAPI app is exercised through its HTTP surface against a real
migrated Postgres. The run queue is a recording fake; everything else is the
production wiring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from agent_arena.db.models import Attempt, Run, Score, TraceMetadata
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from apps.api.db import get_session
from apps.api.main import create_app
from apps.api.queue import get_queue
from apps.api.settings import ApiSettings

pytestmark = pytest.mark.integration

VIEWER = {"X-Forwarded-User": "alice", "X-Forwarded-User-Role": "viewer"}
RUNNER = {"X-Forwarded-User": "bob", "X-Forwarded-User-Role": "runner"}


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.cancelled: list[uuid.UUID] = []

    def enqueue_run(self, run_id: uuid.UUID) -> None:
        self.enqueued.append(run_id)

    def request_cancellation(self, run_id: uuid.UUID) -> None:
        self.cancelled.append(run_id)


@pytest.fixture(scope="module")
def migrated_url(database_url: str) -> str:
    import os

    from alembic import command
    from alembic.config import Config

    from tests.conftest import REPO_ROOT

    os.environ["DATABASE_URL"] = database_url
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


@pytest.fixture(scope="module")
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture(scope="module")
def client(migrated_url: str, queue: FakeQueue):  # type: ignore[no-untyped-def]
    engine = create_async_engine(migrated_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_session():  # type: ignore[no-untyped-def]
        async with factory() as session:
            yield session

    app = create_app(
        ApiSettings(
            database_url=migrated_url,
            redis_url="redis://localhost:6379/0",
            default_role="admin",
            default_user="local",
        )
    )
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_queue] = lambda: queue
    with TestClient(app) as test_client:
        yield test_client


def _create_catalog(client: TestClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    task = client.post(
        "/api/v1/tasks",
        json={
            "slug": f"task-{unique}",
            "version": "1",
            "domain": "math",
            "definition": {"prompt": "what is 6 * 7?", "expected": "42"},
        },
    ).json()
    agent = client.post(
        "/api/v1/agents",
        json={"slug": f"agent-{unique}", "version": "1", "definition": {}},
    ).json()
    rubric = client.post(
        "/api/v1/rubrics",
        json={
            "slug": f"rubric-{unique}",
            "version": "1",
            "definition": {"type": "exact_match", "salt": unique},
        },
    ).json()
    return {"task_id": task["id"], "agent_id": agent["id"], "rubric_id": rubric["id"]}


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_document_lists_v1_paths(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    for path in ("/api/v1/tasks", "/api/v1/runs", "/api/v1/leaderboard", "/health"):
        assert path in paths


def test_task_crud_roundtrip_and_conflict(client: TestClient) -> None:
    unique = uuid.uuid4().hex[:8]
    payload = {
        "slug": f"crud-{unique}",
        "version": "1",
        "domain": "math",
        "definition": {"prompt": "p"},
    }
    created = client.post("/api/v1/tasks", json=payload)
    assert created.status_code == 201
    task_id = created.json()["id"]

    fetched = client.get(f"/api/v1/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["slug"] == payload["slug"]

    listed = client.get("/api/v1/tasks")
    assert any(row["id"] == task_id for row in listed.json())

    duplicate = client.post("/api/v1/tasks", json=payload)
    assert duplicate.status_code == 409

    assert client.get(f"/api/v1/tasks/{uuid.uuid4()}").status_code == 404


def test_rubric_creation_computes_deterministic_hash(client: TestClient) -> None:
    unique = uuid.uuid4().hex[:8]
    definition = {"type": "exact_match", "case_insensitive": True, "salt": unique}
    created = client.post(
        "/api/v1/rubrics",
        json={"slug": f"hash-{unique}", "version": "1", "definition": definition},
    )
    assert created.status_code == 201
    body = created.json()
    assert len(body["definition_hash"]) == 64
    assert body["judge_required"] is False

    # An identical definition under a different slug violates the definition
    # hash uniqueness from the schema.
    conflict = client.post(
        "/api/v1/rubrics",
        json={"slug": f"hash2-{unique}", "version": "1", "definition": definition},
    )
    assert conflict.status_code == 409


def test_role_enforcement(client: TestClient) -> None:
    payload = {"slug": "forbidden", "version": "1", "domain": "x", "definition": {"prompt": "p"}}
    assert client.post("/api/v1/tasks", json=payload, headers=VIEWER).status_code == 403
    assert client.post("/api/v1/tasks", json=payload, headers=RUNNER).status_code == 403
    assert client.get("/api/v1/tasks", headers=VIEWER).status_code == 200

    # Unknown roles are rejected wherever a role check occurs; reads carry
    # no role gate in M1.
    bogus = {"X-Forwarded-User-Role": "root"}
    assert client.post("/api/v1/tasks", json=payload, headers=bogus).status_code == 403


def test_run_fanout_creates_group_and_enqueues(client: TestClient, queue: FakeQueue) -> None:
    refs = _create_catalog(client)
    before = len(queue.enqueued)
    response = client.post(
        "/api/v1/runs",
        json={
            **refs,
            "providers": [
                {"provider": "openai", "model": "gpt-4o-mini"},
                {"provider": "anthropic", "model": "claude-haiku-4-5"},
            ],
            "run_group_name": "contract-test",
        },
        headers=RUNNER,
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["runs"]) == 2
    statuses = {run["status"] for run in body["runs"]}
    assert statuses == {"queued"}
    assert len(queue.enqueued) == before + 2
    enqueued_ids = {str(run_id) for run_id in queue.enqueued[-2:]}
    assert enqueued_ids == {run["id"] for run in body["runs"]}

    # Run ids are UUIDv7: time-ordered, version nibble 7.
    for run in body["runs"]:
        assert uuid.UUID(run["id"]).version == 7

    detail = client.get(f"/api/v1/runs/{body['runs'][0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["attempts"] == []

    listed = client.get("/api/v1/runs", params={"run_group_id": body["run_group_id"]})
    assert len(listed.json()) == 2


def test_run_creation_validates_references(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs",
        json={
            "agent_id": str(uuid.uuid4()),
            "task_id": str(uuid.uuid4()),
            "rubric_id": str(uuid.uuid4()),
            "providers": [{"provider": "openai", "model": "gpt-4o-mini"}],
        },
        headers=RUNNER,
    )
    assert response.status_code == 422


def test_cancel_queued_run(client: TestClient, queue: FakeQueue) -> None:
    refs = _create_catalog(client)
    created = client.post(
        "/api/v1/runs",
        json={**refs, "providers": [{"provider": "openai", "model": "gpt-4o-mini"}]},
        headers=RUNNER,
    ).json()
    run_id = created["runs"][0]["id"]

    cancelled = client.delete(f"/api/v1/runs/{run_id}", headers=RUNNER)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert uuid.UUID(run_id) in queue.cancelled

    again = client.delete(f"/api/v1/runs/{run_id}", headers=RUNNER)
    assert again.status_code == 409

    forbidden = client.delete(f"/api/v1/runs/{run_id}", headers=VIEWER)
    assert forbidden.status_code == 403


def test_cancel_running_run_requests_cooperative_stop(
    client: TestClient, queue: FakeQueue, migrated_url: str
) -> None:
    refs = _create_catalog(client)
    created = client.post(
        "/api/v1/runs",
        json={**refs, "providers": [{"provider": "openai", "model": "gpt-4o-mini"}]},
        headers=RUNNER,
    ).json()
    run_id = uuid.UUID(created["runs"][0]["id"])

    sync_engine = create_engine(migrated_url)
    with Session(sync_engine) as session:
        run = session.get(Run, run_id)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        session.commit()
    sync_engine.dispose()

    response = client.delete(f"/api/v1/runs/{run_id}", headers=RUNNER)
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert run_id in queue.cancelled


def test_leaderboard_serves_view_rows(client: TestClient, migrated_url: str) -> None:
    refs = _create_catalog(client)
    created = client.post(
        "/api/v1/runs",
        json={**refs, "providers": [{"provider": "fake", "model": "fake-model"}]},
        headers=RUNNER,
    ).json()
    run_id = uuid.UUID(created["runs"][0]["id"])

    now = datetime.now(UTC)
    sync_engine = create_engine(migrated_url)
    with Session(sync_engine) as session:
        run = session.get(Run, run_id)
        run.status = "complete"
        run.started_at = now
        run.finished_at = now
        attempt = Attempt(
            run_id=run_id,
            attempt_number=1,
            adapter_version="fake/test",
            started_at=now,
            finished_at=now,
            outcome="success",
        )
        session.add(attempt)
        session.flush()
        trace_hash = f"api-trace-{run_id}"
        session.add(
            TraceMetadata(
                hash=trace_hash,
                run_id=run_id,
                attempt_id=attempt.id,
                provider="fake",
                model="fake-model",
                total_input_tokens=10,
                total_output_tokens=5,
                estimated_cost_usd=Decimal("0.020000"),
                latency_ms=120,
            )
        )
        session.flush()
        session.add(
            Score(
                trace_hash=trace_hash,
                rubric_hash=f"api-rubric-{run_id}",
                score=Decimal("1.0000"),
                is_correct=True,
                score_detail={"method": "exact_match"},
            )
        )
        session.commit()
    sync_engine.dispose()

    response = client.get("/api/v1/leaderboard", params={"refresh": "true"})
    assert response.status_code == 200
    rows = [row for row in response.json() if row["agent_id"] == refs["agent_id"]]
    assert len(rows) == 1
    assert Decimal(str(rows[0]["cost_per_correct_usd"])) == Decimal("0.02")
    assert rows[0]["correct_count"] == 1


def test_audit_log_records_state_changes(client: TestClient, migrated_url: str) -> None:
    from agent_arena.db.models import AuditLogEntry

    refs = _create_catalog(client)
    client.post(
        "/api/v1/runs",
        json={**refs, "providers": [{"provider": "openai", "model": "gpt-4o-mini"}]},
        headers=RUNNER,
    )
    sync_engine = create_engine(migrated_url)
    with Session(sync_engine) as session:
        operations = set(session.execute(select(AuditLogEntry.operation)).scalars().all())
    sync_engine.dispose()
    assert {"task.create", "rubric.create", "agent.create", "run.create"} <= operations


def test_leaderboard_refresh_requires_runner_role(client: TestClient) -> None:
    assert client.get("/api/v1/leaderboard", headers=VIEWER).status_code == 200
    denied = client.get("/api/v1/leaderboard", params={"refresh": "true"}, headers=VIEWER)
    assert denied.status_code == 403
    allowed = client.get("/api/v1/leaderboard", params={"refresh": "true"}, headers=RUNNER)
    assert allowed.status_code == 200
