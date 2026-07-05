"""Contract tests for issue #17: trace endpoints and re-scoring.

A real run executes through the runner orchestration with a scripted
adapter and a local trace store; the API then browses the trace and
re-scores it under a new rubric with no LLM involvement.
"""

from __future__ import annotations

import uuid

import pytest
from agent_arena.trace_store import LocalTraceStore
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from apps.api.db import get_session
from apps.api.main import create_app
from apps.api.queue import get_queue
from apps.api.settings import ApiSettings
from apps.api.trace_store import get_trace_store
from apps.runner.execution import execute_run_sync
from tests.runner.fakes import FakeAdapter, response

pytestmark = pytest.mark.integration

RUNNER = {"X-Forwarded-User": "bob", "X-Forwarded-User-Role": "runner"}
VIEWER = {"X-Forwarded-User": "alice", "X-Forwarded-User-Role": "viewer"}


class _NullQueue:
    def enqueue_run(self, run_id: uuid.UUID) -> None:
        pass

    def request_cancellation(self, run_id: uuid.UUID) -> None:
        pass


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
def store(tmp_path_factory: pytest.TempPathFactory) -> LocalTraceStore:
    return LocalTraceStore(tmp_path_factory.mktemp("traces"))


@pytest.fixture(scope="module")
def client(migrated_url: str, store: LocalTraceStore):  # type: ignore[no-untyped-def]
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
    app.dependency_overrides[get_queue] = lambda: _NullQueue()
    app.dependency_overrides[get_trace_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def completed_trace(client: TestClient, migrated_url: str, store: LocalTraceStore) -> dict:  # type: ignore[type-arg]
    """Create a catalog, a run, and execute it for real against the fake adapter."""
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
        "/api/v1/agents", json={"slug": f"agent-{unique}", "version": "1", "definition": {}}
    ).json()
    rubric = client.post(
        "/api/v1/rubrics",
        json={
            "slug": f"rubric-{unique}",
            "version": "1",
            "definition": {"type": "exact_match", "salt": unique},
        },
    ).json()
    created = client.post(
        "/api/v1/runs",
        json={
            "task_id": task["id"],
            "agent_id": agent["id"],
            "rubric_id": rubric["id"],
            "providers": [{"provider": "fake", "model": "fake-model"}],
        },
        headers=RUNNER,
    ).json()
    run_id = uuid.UUID(created["runs"][0]["id"])

    from agent_arena.adapters import AdapterRegistry

    registry = AdapterRegistry()
    registry.register("fake", FakeAdapter(responses=[response("42")]))
    sync_engine = create_engine(migrated_url)
    outcome = execute_run_sync(
        run_id,
        session_factory=sessionmaker(bind=sync_engine, expire_on_commit=False),
        registry=registry,
        trace_store=store,
    )
    sync_engine.dispose()
    assert outcome.run_status == "complete"

    traces = client.get("/api/v1/traces", params={"run_id": str(run_id)}).json()
    assert len(traces) == 1
    return {"unique": unique, "run_id": str(run_id), "trace": traces[0]}


def test_trace_browse_detail_and_body(client: TestClient, completed_trace: dict) -> None:  # type: ignore[type-arg]
    trace = completed_trace["trace"]
    assert trace["body_uri"].startswith("file://")

    detail = client.get(f"/api/v1/traces/{trace['hash']}").json()
    assert detail["hash"] == trace["hash"]
    assert len(detail["scores"]) == 1
    assert detail["scores"][0]["is_correct"] is True

    body = client.get(f"/api/v1/traces/{trace['hash']}/body")
    assert body.status_code == 200
    document = body.json()
    assert document["final_answer"] == "42"
    assert document["steps"][0]["response"]["content"] == "42"

    assert client.get(f"/api/v1/traces/{'0' * 64}").status_code == 404


def test_rescore_under_new_rubric_is_idempotent(
    client: TestClient,
    completed_trace: dict,  # type: ignore[type-arg]
) -> None:
    unique = completed_trace["unique"]
    trace_hash = completed_trace["trace"]["hash"]
    relaxed = client.post(
        "/api/v1/rubrics",
        json={
            "slug": f"relaxed-{unique}",
            "version": "1",
            "definition": {"type": "exact_match", "case_insensitive": True, "salt": unique},
        },
    ).json()

    first = client.post(
        f"/api/v1/traces/{trace_hash}/score",
        json={"rubric_id": relaxed["id"]},
        headers=RUNNER,
    )
    assert first.status_code == 201, first.text
    assert first.json()["is_correct"] is True
    assert first.json()["rubric_hash"] == relaxed["definition_hash"]

    second = client.post(
        f"/api/v1/traces/{trace_hash}/score",
        json={"rubric_id": relaxed["id"]},
        headers=RUNNER,
    )
    assert second.status_code == 200
    assert second.json()["scored_at"] == first.json()["scored_at"]

    detail = client.get(f"/api/v1/traces/{trace_hash}").json()
    assert len(detail["scores"]) == 2


def test_rescore_rejects_judge_rubrics_for_now(
    client: TestClient,
    completed_trace: dict,  # type: ignore[type-arg]
) -> None:
    unique = completed_trace["unique"]
    judge = client.post(
        "/api/v1/rubrics",
        json={
            "slug": f"judge-{unique}",
            "version": "1",
            "definition": {"type": "exact_match", "judge": True, "salt": unique},
            "judge_required": True,
        },
    ).json()
    denied = client.post(
        f"/api/v1/traces/{completed_trace['trace']['hash']}/score",
        json={"rubric_id": judge["id"]},
        headers=RUNNER,
    )
    assert denied.status_code == 422
    assert "issue #19" in denied.json()["detail"]


def test_rescore_requires_runner_role(
    client: TestClient,
    completed_trace: dict,  # type: ignore[type-arg]
) -> None:
    denied = client.post(
        f"/api/v1/traces/{completed_trace['trace']['hash']}/score",
        json={"rubric_id": str(uuid.uuid4())},
        headers=VIEWER,
    )
    assert denied.status_code == 403
