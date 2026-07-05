"""Acceptance tests for issue #10.

The ``aggregates.leaderboard`` materialised view computes CPCA in SQL with
NULL for groups that have zero correct answers, the presentation query sorts
by CPCA ascending with NULLs last, and refresh is idempotent. Runs against a
real Postgres container, so it is marked ``integration`` and skips when
Docker is absent.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Make the namespace package importable even without an editable install.
sys.path.insert(0, str(REPO_ROOT / "packages" / "db"))

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - dev dependency missing
        pytest.skip("testcontainers is not installed")

    try:
        with PostgresContainer("postgres:16", driver="psycopg") as postgres:
            yield postgres.get_connection_url()
    except Exception as exc:  # pragma: no cover - Docker unavailable
        pytest.skip(f"could not start Postgres container: {exc}")


def _alembic_config(url: str):  # type: ignore[no-untyped-def]
    from alembic.config import Config

    os.environ["DATABASE_URL"] = url
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _seed(engine) -> None:  # type: ignore[no-untyped-def]
    """One agent and task scored under one rubric across three model groups.

    - ``cheap``: two runs, one cent each, both correct. CPCA 0.01.
    - ``pricey``: two runs, five cents each, one correct. CPCA 0.10.
    - ``wrong``: one run, three cents, zero correct. CPCA NULL.
    - ``failed``: a run with status ``failed`` that must not appear at all.
    """
    from agent_arena.db.models import (
        Agent,
        Attempt,
        Rubric,
        Run,
        Score,
        Task,
        TraceMetadata,
    )
    from sqlalchemy.orm import Session

    now = datetime.now(UTC)
    agent = Agent(slug="solver", version="1", definition={"system_prompt": "solve"})
    task = Task(slug="add", version="1", domain="math", definition={"prompt": "1+1"})
    rubric = Rubric(
        slug="exact",
        version="1",
        definition_hash="rubric-exact-1",
        definition={"type": "exact_match"},
    )

    with Session(engine) as session:
        session.add_all([agent, task, rubric])
        session.flush()

        groups = [
            ("cheap", "complete", [(Decimal("0.010000"), True), (Decimal("0.010000"), True)]),
            ("pricey", "complete", [(Decimal("0.050000"), True), (Decimal("0.050000"), False)]),
            ("wrong", "complete", [(Decimal("0.030000"), False)]),
            ("failed", "failed", [(Decimal("0.020000"), True)]),
        ]
        for model, status, outcomes in groups:
            for index, (cost, is_correct) in enumerate(outcomes):
                run = Run(
                    id=uuid.uuid4(),
                    agent_id=agent.id,
                    task_id=task.id,
                    provider="openai",
                    model=model,
                    rubric_id=rubric.id,
                    status=status,
                    started_at=now,
                    finished_at=now,
                    created_by="test",
                )
                session.add(run)
                session.flush()
                attempt = Attempt(
                    run_id=run.id,
                    attempt_number=1,
                    adapter_version="test-adapter/1",
                    started_at=now,
                    finished_at=now,
                    outcome="success",
                )
                session.add(attempt)
                session.flush()
                trace_hash = f"trace-{model}-{index}"
                session.add(
                    TraceMetadata(
                        hash=trace_hash,
                        run_id=run.id,
                        attempt_id=attempt.id,
                        provider="openai",
                        model=model,
                        total_input_tokens=100,
                        total_output_tokens=50,
                        estimated_cost_usd=cost,
                        latency_ms=100 + index,
                    )
                )
                # The model layer defines no relationship() constructs, so the
                # unit of work cannot infer insert order across classes; flush
                # the trace row before the score row that references it.
                session.flush()
                session.add(
                    Score(
                        trace_hash=trace_hash,
                        rubric_hash="rubric-exact-1",
                        score=Decimal("1.0000") if is_correct else Decimal("0.0000"),
                        is_correct=is_correct,
                        score_detail={"method": "exact_match"},
                    )
                )
        session.commit()


def test_leaderboard_cpca_ordering_and_refresh(database_url: str) -> None:
    from agent_arena.db.leaderboard import leaderboard_query, refresh_leaderboard
    from alembic import command
    from sqlalchemy import create_engine

    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    command.upgrade(config, "head")
    _seed(engine)

    # The view was created before the seed data existed; refresh picks it up.
    # Two consecutive refreshes prove idempotency, one of them concurrent.
    refresh_leaderboard(engine, concurrently=False)
    refresh_leaderboard(engine, concurrently=True)

    with engine.connect() as connection:
        rows = connection.execute(leaderboard_query()).mappings().all()

    assert [row["model"] for row in rows] == ["cheap", "pricey", "wrong"]

    by_model = {row["model"]: row for row in rows}
    assert by_model["cheap"]["cost_per_correct_usd"] == Decimal("0.010000")
    assert by_model["cheap"]["correct_count"] == 2
    assert by_model["cheap"]["total_count"] == 2
    assert by_model["cheap"]["mean_score"] == Decimal("1.0000")

    assert by_model["pricey"]["cost_per_correct_usd"] == Decimal("0.100000")
    assert by_model["pricey"]["correct_count"] == 1
    assert by_model["pricey"]["total_cost_usd"] == Decimal("0.100000")

    assert by_model["wrong"]["cost_per_correct_usd"] is None
    assert by_model["wrong"]["correct_count"] == 0

    assert "failed" not in by_model

    engine.dispose()


def test_downgrade_removes_aggregates(database_url: str) -> None:
    from alembic import command
    from sqlalchemy import create_engine, inspect

    config = _alembic_config(database_url)
    engine = create_engine(database_url)

    command.downgrade(config, "0001_m1_subset")
    inspector = inspect(engine)
    assert "aggregates" not in set(inspector.get_schema_names())

    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert "scores" in set(inspector.get_table_names(schema="aggregates"))

    engine.dispose()
