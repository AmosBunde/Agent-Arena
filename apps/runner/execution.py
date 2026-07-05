"""Run execution orchestration.

Owns the run lifecycle documented in session-design.md
(``queued -> running -> complete | failed | cancelled``), the attempt
outcome taxonomy from system-design.md, idempotent restart after a worker
crash, capability negotiation (ADR-0002), trace persistence, and synchronous
scoring for deterministic rubrics.

Failure taxonomy (system-design.md, Failure handling):

- Exceptions escaping ``adapter.chat`` are provider failures: the attempt is
  ``failed_provider_error`` and the error is captured in the trace.
- Adapter and definition bugs are ``failed_adapter_error``: no partial trace
  is written, because partial traces would corrupt deduplication.
- The Celery soft time limit surfaces as ``failed_timeout``; partial state is
  discarded.
- Cooperative cancellation writes no attempt and no trace.

Dependencies (session factory, adapter registry, cancellation probe) are
injected so tests can drive the orchestration without Celery or Redis.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from agent_arena.adapters import (
    AdapterError,
    AdapterRegistry,
    AgentAdapter,
    Capability,
    TokenUsage,
    missing_capabilities,
)
from agent_arena.db.models import Agent, Attempt, Rubric, Run, Score, Task, TraceMetadata
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.runner.agent_loop import LoopResult, RunCancelled, run_agent_loop
from apps.runner.contracts import (
    AgentDefinition,
    DefinitionError,
    RubricDefinition,
    TaskDefinition,
)
from apps.runner.scoring import ScoringError, score_answer
from apps.runner.tracing import build_trace, serialise_trace

try:  # pragma: no cover - the soft limit only fires under a worker
    from celery.exceptions import SoftTimeLimitExceeded
except ImportError:  # pragma: no cover

    class SoftTimeLimitExceeded(Exception):  # type: ignore[no-redef]
        """Stand-in when Celery is not installed (unit tests)."""


SessionFactory = Callable[[], Session]
CancelProbe = Callable[[], bool]


def _adapter_version(provider: str) -> str:
    try:
        package_version = version("agent-arena")
    except PackageNotFoundError:  # pragma: no cover - not installed
        package_version = "unknown"
    return f"{provider}/agent-arena-{package_version}"


def _never() -> bool:
    return False


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """What happened to the run, for logging and tests."""

    run_status: str
    attempt_outcome: str | None
    detail: str | None = None


def execute_run_sync(
    run_id: uuid.UUID,
    *,
    session_factory: SessionFactory,
    registry: AdapterRegistry,
    default_max_turns: int = 8,
    cancel_requested: CancelProbe = _never,
) -> ExecutionOutcome:
    """Execute one run to a terminal state. Safe to call again after a crash."""
    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is None:
            return ExecutionOutcome("missing", None, f"run {run_id} not found")
        if run.status in ("complete", "failed", "cancelled"):
            return ExecutionOutcome(run.status, None, "already terminal")

        if _has_successful_trace(session, run_id):
            _finish(session, run, "complete")
            return ExecutionOutcome("complete", None, "complete from cache")

        if cancel_requested():
            _finish(session, run, "cancelled")
            return ExecutionOutcome("cancelled", None, "cancelled before start")

        run.status = "running"
        run.started_at = datetime.now(UTC)
        session.commit()

        try:
            return _execute(
                session,
                run,
                registry=registry,
                default_max_turns=default_max_turns,
                cancel_requested=cancel_requested,
            )
        except RunCancelled:
            _finish(session, run, "cancelled")
            return ExecutionOutcome("cancelled", None, "cancelled mid-run")
        except SoftTimeLimitExceeded:
            _record_attempt(session, run, "failed_timeout")
            _finish(session, run, "failed", failure_reason="timeout")
            return ExecutionOutcome("failed", "failed_timeout")


def _execute(
    session: Session,
    run: Run,
    *,
    registry: AdapterRegistry,
    default_max_turns: int,
    cancel_requested: CancelProbe,
) -> ExecutionOutcome:
    try:
        task_row, agent_row, rubric_row = _load_catalog(session, run)
        task = TaskDefinition.parse(task_row.definition)
        agent = AgentDefinition.parse(agent_row.definition)
        rubric = (
            None if rubric_row.judge_required else RubricDefinition.parse(rubric_row.definition)
        )
        adapter = registry.get_adapter(run.provider, run.model)
        required = _required_capabilities(task, task_row.capabilities_required)
    except (DefinitionError, AdapterError, LookupError) as exc:
        _record_attempt(session, run, "failed_adapter_error")
        _finish(session, run, "failed", failure_reason=f"invalid run setup: {exc}")
        return ExecutionOutcome("failed", "failed_adapter_error", str(exc))

    missing = missing_capabilities(adapter, required)
    if missing:
        names = sorted(capability.value for capability in missing)
        _record_attempt(session, run, "skipped_unsupported")
        _finish(session, run, "failed", failure_reason=f"unsupported capabilities: {names}")
        return ExecutionOutcome("failed", "skipped_unsupported", str(names))

    try:
        result = asyncio.run(
            run_agent_loop(
                adapter,
                task,
                agent,
                default_max_turns=default_max_turns,
                cancel_requested=cancel_requested,
            )
        )
    except (RunCancelled, SoftTimeLimitExceeded):
        raise
    except AdapterError as exc:
        _record_attempt(session, run, "failed_adapter_error")
        _finish(session, run, "failed", failure_reason=f"adapter error: {exc}")
        return ExecutionOutcome("failed", "failed_adapter_error", str(exc))
    except Exception as exc:
        # Adapters retry internally; what escapes chat() is a provider
        # failure. The error is captured in a minimal trace per
        # system-design.md.
        attempt = _record_attempt(session, run, "failed_provider_error")
        _write_trace(
            session,
            run,
            attempt,
            task_row,
            agent_row,
            adapter,
            LoopResult(),
            error=f"{type(exc).__name__}: {exc}",
        )
        _finish(session, run, "failed", failure_reason=f"provider error: {exc}")
        return ExecutionOutcome("failed", "failed_provider_error", str(exc))

    score = None
    if rubric is not None:
        try:
            score = score_answer(rubric, task, result.final_answer)
        except ScoringError as exc:
            attempt = _record_attempt(session, run, "failed_adapter_error")
            _write_trace(session, run, attempt, task_row, agent_row, adapter, result)
            _finish(session, run, "failed", failure_reason=f"scoring error: {exc}")
            return ExecutionOutcome("failed", "failed_adapter_error", str(exc))

    attempt = _record_attempt(session, run, "success")
    trace = _write_trace(session, run, attempt, task_row, agent_row, adapter, result)
    if score is not None:
        session.add(
            Score(
                trace_hash=trace.hash,
                rubric_hash=rubric_row.definition_hash,
                score=score.score,
                is_correct=score.is_correct,
                score_detail=score.detail,
            )
        )
    _finish(session, run, "complete")
    return ExecutionOutcome("complete", "success")


def _load_catalog(session: Session, run: Run) -> tuple[Task, Agent, Rubric]:
    task = session.get(Task, run.task_id)
    agent = session.get(Agent, run.agent_id)
    rubric = session.get(Rubric, run.rubric_id)
    if task is None or agent is None or rubric is None:
        raise LookupError("run references a missing task, agent, or rubric")
    return task, agent, rubric


def _required_capabilities(
    task: TaskDefinition, declared: list[str] | None
) -> frozenset[Capability]:
    required = {Capability.CHAT}
    if task.tools:
        required.add(Capability.TOOL_CALLING)
    for name in declared or []:
        try:
            required.add(Capability(name))
        except ValueError as exc:
            raise DefinitionError(f"unknown required capability {name!r}") from exc
    return frozenset(required)


def _has_successful_trace(session: Session, run_id: uuid.UUID) -> bool:
    statement = (
        select(TraceMetadata.hash)
        .join(Attempt, Attempt.id == TraceMetadata.attempt_id)
        .where(TraceMetadata.run_id == run_id, Attempt.outcome == "success")
        .limit(1)
    )
    return session.execute(statement).first() is not None


def _record_attempt(session: Session, run: Run, outcome: str) -> Attempt:
    number = (
        session.execute(
            select(Attempt.attempt_number)
            .where(Attempt.run_id == run.id)
            .order_by(Attempt.attempt_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    ) + 1
    attempt = Attempt(
        run_id=run.id,
        attempt_number=number,
        adapter_version=_adapter_version(run.provider),
        started_at=run.started_at or datetime.now(UTC),
        finished_at=datetime.now(UTC),
        outcome=outcome,
    )
    session.add(attempt)
    session.flush()
    return attempt


def _write_trace(
    session: Session,
    run: Run,
    attempt: Attempt,
    task_row: Task,
    agent_row: Agent,
    adapter: AgentAdapter,
    result: LoopResult,
    *,
    error: str | None = None,
) -> TraceMetadata:
    document: dict[str, Any] = build_trace(
        run_id=run.id,
        provider=run.provider,
        model=run.model,
        task_slug=task_row.slug,
        task_version=task_row.version,
        agent_slug=agent_row.slug,
        agent_version=agent_row.version,
        result=result,
        error=error,
    )
    serialised = serialise_trace(document)
    usage = TokenUsage(
        prompt_tokens=result.total_prompt_tokens,
        completion_tokens=result.total_completion_tokens,
        cached_tokens=result.total_cached_tokens,
    )
    trace = TraceMetadata(
        hash=serialised.hash,
        run_id=run.id,
        attempt_id=attempt.id,
        body_uri=None,
        body_size_bytes=serialised.size_bytes,
        provider=run.provider,
        model=run.model,
        total_input_tokens=result.total_prompt_tokens,
        total_output_tokens=result.total_completion_tokens,
        total_cached_tokens=result.total_cached_tokens,
        estimated_cost_usd=adapter.estimate_cost(usage),
        latency_ms=result.total_latency_ms,
        tool_call_count=result.tool_call_count,
    )
    session.add(trace)
    session.flush()
    return trace


def _finish(session: Session, run: Run, status: str, *, failure_reason: str | None = None) -> None:
    run.status = status
    run.failure_reason = failure_reason
    run.finished_at = datetime.now(UTC)
    session.commit()
