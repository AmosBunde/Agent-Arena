"""Acceptance tests for issue #8: run execution end to end.

Real Postgres via testcontainers, scripted adapter, no Celery broker: the
orchestration is exercised through ``execute_run_sync`` with injected
dependencies, which is exactly how the Celery task drives it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from agent_arena.adapters import AdapterRegistry, Capability, ToolCall
from agent_arena.db.models import Agent, Attempt, Rubric, Run, Score, Task, TraceMetadata
from sqlalchemy import select

from apps.runner.execution import execute_run_sync
from tests.runner.fakes import FakeAdapter, response

pytestmark = pytest.mark.integration


def _registry(adapter: FakeAdapter) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register("fake", adapter)
    return registry


def _seed_run(
    session_factory,  # type: ignore[no-untyped-def]
    *,
    task_definition: dict | None = None,  # type: ignore[type-arg]
    capabilities_required: list[str] | None = None,
    judge_required: bool = False,
) -> uuid.UUID:
    unique = uuid.uuid4().hex[:8]
    with session_factory() as session:
        task = Task(
            slug=f"task-{unique}",
            version="1",
            domain="math",
            definition=task_definition or {"prompt": "what is 6 * 7?", "expected": "42"},
            capabilities_required=capabilities_required or [],
        )
        agent = Agent(slug=f"agent-{unique}", version="1", definition={})
        rubric = Rubric(
            slug=f"rubric-{unique}",
            version="1",
            definition_hash=f"rubric-{unique}",
            definition={"type": "exact_match"},
            judge_required=judge_required,
        )
        session.add_all([task, agent, rubric])
        session.flush()
        run = Run(
            id=uuid.uuid4(),
            agent_id=agent.id,
            task_id=task.id,
            provider="fake",
            model="fake-model",
            rubric_id=rubric.id,
            status="queued",
            queued_at=datetime.now(UTC),
            created_by="test",
        )
        session.add(run)
        session.commit()
        return run.id


def _fetch(session_factory, run_id):  # type: ignore[no-untyped-def]
    with session_factory() as session:
        run = session.get(Run, run_id)
        attempts = session.execute(select(Attempt).where(Attempt.run_id == run_id)).scalars().all()
        traces = (
            session.execute(select(TraceMetadata).where(TraceMetadata.run_id == run_id))
            .scalars()
            .all()
        )
        scores = []
        for trace in traces:
            scores.extend(
                session.execute(select(Score).where(Score.trace_hash == trace.hash)).scalars().all()
            )
        return run, attempts, traces, scores


def test_successful_run_writes_trace_and_score(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(session_factory)

    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))

    assert outcome.run_status == "complete"
    assert outcome.attempt_outcome == "success"
    run, attempts, traces, scores = _fetch(session_factory, run_id)
    assert run.status == "complete"
    assert run.started_at is not None and run.finished_at is not None
    assert [a.outcome for a in attempts] == ["success"]
    assert len(traces) == 1
    trace = traces[0]
    assert trace.body_uri is None
    assert trace.total_input_tokens == 10
    assert trace.total_output_tokens == 5
    assert trace.estimated_cost_usd == Decimal("0.000015")
    assert len(scores) == 1
    assert scores[0].is_correct


def test_second_call_completes_from_cache(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(session_factory)
    execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))

    # Simulate a redelivered job after a crash-before-ack: reset the status.
    with session_factory() as session:
        run = session.get(Run, run_id)
        run.status = "queued"
        session.commit()

    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "complete"
    assert outcome.detail == "complete from cache"
    _, attempts, traces, _ = _fetch(session_factory, run_id)
    assert len(attempts) == 1
    assert len(traces) == 1


def test_tool_use_run_end_to_end(session_factory) -> None:  # type: ignore[no-untyped-def]
    call = ToolCall(id="c1", name="calculator", arguments={"expression": "6 * 7"})
    adapter = FakeAdapter(responses=[response(None, tool_calls=(call,)), response("42")])
    run_id = _seed_run(
        session_factory,
        task_definition={
            "prompt": "compute 6 * 7 with the calculator",
            "expected": "42",
            "tools": ["calculator"],
        },
    )
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "complete"
    _, _, traces, scores = _fetch(session_factory, run_id)
    assert traces[0].tool_call_count == 1
    assert scores[0].is_correct


def test_provider_error_writes_error_trace(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(error=RuntimeError("rate limited after retries"))
    run_id = _seed_run(session_factory)
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "failed"
    assert outcome.attempt_outcome == "failed_provider_error"
    run, attempts, traces, scores = _fetch(session_factory, run_id)
    assert run.failure_reason is not None and "rate limited" in run.failure_reason
    assert [a.outcome for a in attempts] == ["failed_provider_error"]
    assert len(traces) == 1
    assert scores == []


def test_missing_capability_skips_unsupported(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")], capabilities=frozenset({Capability.CHAT}))
    run_id = _seed_run(
        session_factory,
        task_definition={"prompt": "q", "expected": "42", "tools": ["calculator"]},
    )
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "failed"
    assert outcome.attempt_outcome == "skipped_unsupported"
    run, attempts, traces, _ = _fetch(session_factory, run_id)
    assert "tool_calling" in (run.failure_reason or "")
    assert [a.outcome for a in attempts] == ["skipped_unsupported"]
    assert traces == []
    assert adapter.calls == []


def test_invalid_task_definition_fails_adapter_error(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(session_factory, task_definition={"no_prompt": True})
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "failed"
    assert outcome.attempt_outcome == "failed_adapter_error"


def test_cancellation_before_start(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(session_factory)
    outcome = execute_run_sync(
        run_id,
        session_factory=session_factory,
        registry=_registry(adapter),
        cancel_requested=lambda: True,
    )
    assert outcome.run_status == "cancelled"
    run, attempts, traces, _ = _fetch(session_factory, run_id)
    assert run.status == "cancelled"
    assert attempts == []
    assert traces == []


def test_judge_required_rubric_completes_without_score(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(session_factory, judge_required=True)
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "complete"
    _, _, traces, scores = _fetch(session_factory, run_id)
    assert len(traces) == 1
    assert scores == []


def test_terminal_run_is_left_alone(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(session_factory)
    with session_factory() as session:
        run = session.get(Run, run_id)
        run.status = "cancelled"
        session.commit()
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "cancelled"
    assert outcome.detail == "already terminal"
    assert adapter.calls == []


def test_retried_provider_error_gets_distinct_trace_hash(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(error=RuntimeError("identical error text"))
    run_id = _seed_run(session_factory)
    execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))

    # Retry path: an operator requeues the failed run.
    with session_factory() as session:
        run = session.get(Run, run_id)
        run.status = "queued"
        session.commit()

    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "failed"
    _, attempts, traces, _ = _fetch(session_factory, run_id)
    assert [a.outcome for a in attempts] == ["failed_provider_error", "failed_provider_error"]
    assert len(traces) == 2
    assert traces[0].hash != traces[1].hash


def test_cost_model_error_leaves_run_terminal(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(
        responses=[response("42")], cost_error=LookupError("no price line for model")
    )
    run_id = _seed_run(session_factory)
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "failed"
    assert outcome.attempt_outcome == "failed_adapter_error"
    run, attempts, _, _ = _fetch(session_factory, run_id)
    assert run.status == "failed"
    assert "no price line" in (run.failure_reason or "")
    assert attempts, "the failure must record an attempt"


def test_provider_metadata_cost_wins_over_estimate(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42", provider_metadata={"cost_usd": "0.123456"})])
    run_id = _seed_run(session_factory)
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "complete"
    _, _, traces, _ = _fetch(session_factory, run_id)
    assert traces[0].estimated_cost_usd == Decimal("0.123456")


def test_unknown_tool_is_a_definition_error(session_factory) -> None:  # type: ignore[no-untyped-def]
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(
        session_factory,
        task_definition={"prompt": "q", "expected": "42", "tools": ["web_browser"]},
    )
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=_registry(adapter))
    assert outcome.run_status == "failed"
    assert outcome.attempt_outcome == "failed_adapter_error"
    _, _, traces, _ = _fetch(session_factory, run_id)
    assert traces == []
    assert adapter.calls == []


def test_fail_stale_runs_reaps_stranded_running(session_factory) -> None:  # type: ignore[no-untyped-def]
    from datetime import timedelta

    from apps.runner.execution import fail_stale_runs

    run_id = _seed_run(session_factory)
    with session_factory() as session:
        run = session.get(Run, run_id)
        run.status = "running"
        run.started_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()

    reaped = fail_stale_runs(session_factory=session_factory, stale_after_seconds=3600)
    assert reaped == 1
    run, attempts, _, _ = _fetch(session_factory, run_id)
    assert run.status == "failed"
    assert [a.outcome for a in attempts] == ["failed_timeout"]

    # Idempotent: a second sweep finds nothing.
    assert fail_stale_runs(session_factory=session_factory, stale_after_seconds=3600) == 0


def test_trace_body_persisted_through_store(session_factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from agent_arena.trace_store import LocalTraceStore

    store = LocalTraceStore(tmp_path)
    adapter = FakeAdapter(responses=[response("42")])
    run_id = _seed_run(session_factory)
    outcome = execute_run_sync(
        run_id,
        session_factory=session_factory,
        registry=_registry(adapter),
        trace_store=store,
    )
    assert outcome.run_status == "complete"
    _, _, traces, _ = _fetch(session_factory, run_id)
    trace = traces[0]
    assert trace.body_uri is not None and trace.body_uri.startswith("file://")
    body = store.get(trace.hash)
    assert len(body) == trace.body_size_bytes
    import json

    document = json.loads(body)
    assert document["final_answer"] == "42"
