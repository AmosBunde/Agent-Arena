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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol

from agent_arena.adapters import (
    AdapterError,
    AgentAdapter,
    Capability,
    TokenUsage,
    missing_capabilities,
)
from agent_arena.db.models import Agent, Attempt, Rubric, Run, Score, Task, TraceMetadata
from agent_arena.trace_store import TraceStore
from celery.exceptions import SoftTimeLimitExceeded
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
from apps.runner.tools import ToolExecutionError, tool_specs
from apps.runner.tracing import build_trace, serialise_trace

SessionFactory = Callable[[], Session]
CancelProbe = Callable[[], bool]
# Follow-up enqueue for judge scoring: (trace_hash, rubric_id).
JudgeEnqueue = Callable[[str, uuid.UUID], None]


class AdapterSource(Protocol):
    """Anything that resolves (provider, model) to an adapter.

    ``AdapterRegistry`` satisfies this; the Celery task layer wraps it to
    apply deployment-level construction arguments.
    """

    def get_adapter(self, provider: str, model: str, **kwargs: object) -> AgentAdapter: ...


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
    registry: AdapterSource,
    default_max_turns: int = 8,
    cancel_requested: CancelProbe = _never,
    trace_store: TraceStore | None = None,
    enqueue_judge: JudgeEnqueue | None = None,
) -> ExecutionOutcome:
    """Execute one run to a terminal state. Safe to call again after a crash.

    ``trace_store`` receives every trace body (ADR-0003); without one the
    metadata row is written with a NULL ``body_uri``, which keeps unit tests
    and pre-M2 deployments working.
    """
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
                trace_store=trace_store,
                enqueue_judge=enqueue_judge,
            )
        except RunCancelled:
            session.rollback()
            _finish(session, run, "cancelled")
            return ExecutionOutcome("cancelled", None, "cancelled mid-run")
        except SoftTimeLimitExceeded:
            # The soft limit can interrupt a flush; discard the transaction
            # before recording the timeout in a fresh one.
            session.rollback()
            _record_attempt(session, run, "failed_timeout")
            _finish(session, run, "failed", failure_reason="timeout")
            return ExecutionOutcome("failed", "failed_timeout")
        except Exception as exc:
            # Last-resort guard: whatever escaped _execute (cost model
            # lookup, database integrity, a bug) must still leave the run in
            # a terminal state instead of stranding it in ``running``.
            session.rollback()
            _record_attempt(session, run, "failed_adapter_error")
            _finish(session, run, "failed", failure_reason=f"internal error: {exc}")
            return ExecutionOutcome("failed", "failed_adapter_error", str(exc))


def _execute(
    session: Session,
    run: Run,
    *,
    registry: AdapterSource,
    default_max_turns: int,
    cancel_requested: CancelProbe,
    trace_store: TraceStore | None,
    enqueue_judge: JudgeEnqueue | None,
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
        if task.tools:
            # Unknown tool names are a definition bug; surface them here
            # rather than letting the loop misclassify them as provider
            # errors.
            try:
                tool_specs(task.tools)
            except ToolExecutionError as exc:
                raise DefinitionError(str(exc)) from exc
    except (DefinitionError, AdapterError, LookupError) as exc:
        _record_attempt(session, run, "failed_adapter_error")
        _finish(session, run, "failed", failure_reason=f"invalid run setup: {exc}")
        return ExecutionOutcome("failed", "failed_adapter_error", str(exc))

    missing = missing_capabilities(adapter, required)
    if missing:
        # The run status CHECK constraint has no skipped value, so the run is
        # marked failed with a distinguishable reason prefix; the attempt row
        # carries the honest outcome. The ADR-0002 versus schema tension is
        # tracked in issue #47.
        names = sorted(capability.value for capability in missing)
        _record_attempt(session, run, "skipped_unsupported")
        _finish(session, run, "failed", failure_reason=f"skipped_unsupported: {names}")
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
            trace_store=trace_store,
            temperature=agent.temperature,
            tools=task.tools,
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
            _write_trace(
                session,
                run,
                attempt,
                task_row,
                agent_row,
                adapter,
                result,
                trace_store=trace_store,
                temperature=agent.temperature,
                tools=task.tools,
            )
            _finish(session, run, "failed", failure_reason=f"scoring error: {exc}")
            return ExecutionOutcome("failed", "failed_adapter_error", str(exc))

    attempt = _record_attempt(session, run, "success")
    trace = _write_trace(
        session,
        run,
        attempt,
        task_row,
        agent_row,
        adapter,
        result,
        trace_store=trace_store,
        temperature=agent.temperature,
        tools=task.tools,
    )
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
    if rubric_row.judge_required and enqueue_judge is not None:
        # Judge scoring is a follow-up job (system-design.md, Request
        # lifecycle step 6); the run is already complete either way.
        enqueue_judge(trace.hash, rubric_row.id)
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
    trace_store: TraceStore | None = None,
    temperature: float | None = None,
    tools: tuple[str, ...] = (),
    error: str | None = None,
) -> TraceMetadata:
    document: dict[str, Any] = build_trace(
        run_id=run.id,
        attempt_number=attempt.attempt_number,
        provider=run.provider,
        model=run.model,
        task_slug=task_row.slug,
        task_version=task_row.version,
        agent_slug=agent_row.slug,
        agent_version=agent_row.version,
        result=result,
        temperature=temperature,
        tools=tools,
        error=error,
    )
    serialised = serialise_trace(document)
    body_uri = (
        trace_store.put(serialised.hash, serialised.body.encode("utf-8"))
        if trace_store is not None
        else None
    )
    trace = TraceMetadata(
        hash=serialised.hash,
        run_id=run.id,
        attempt_id=attempt.id,
        body_uri=body_uri,
        body_size_bytes=serialised.size_bytes,
        provider=run.provider,
        model=run.model,
        total_input_tokens=result.total_prompt_tokens,
        total_output_tokens=result.total_completion_tokens,
        total_cached_tokens=result.total_cached_tokens,
        estimated_cost_usd=_estimate_total_cost(adapter, result),
        latency_ms=result.total_latency_ms,
        tool_call_count=result.tool_call_count,
    )
    session.add(trace)
    session.flush()
    return trace


def _estimate_total_cost(adapter: AgentAdapter, result: LoopResult) -> Decimal:
    """Total run cost in USD.

    Local model adapters surface the authoritative latency-aware cost per
    call as ``provider_metadata["cost_usd"]`` (ADR-0004); token-priced
    adapters compute from usage. Per step, the metadata figure wins when
    present.
    """
    if not result.steps:
        return adapter.estimate_cost(
            TokenUsage(
                prompt_tokens=result.total_prompt_tokens,
                completion_tokens=result.total_completion_tokens,
                cached_tokens=result.total_cached_tokens,
            )
        )
    total = Decimal("0")
    for step in result.steps:
        metadata_cost = step.response.provider_metadata.get("cost_usd")
        if metadata_cost is not None:
            total += Decimal(str(metadata_cost))
        else:
            total += adapter.estimate_cost(step.response.usage)
    return total


def _finish(session: Session, run: Run, status: str, *, failure_reason: str | None = None) -> None:
    run.status = status
    run.failure_reason = failure_reason
    run.finished_at = datetime.now(UTC)
    session.commit()


def fail_stale_runs(*, session_factory: SessionFactory, stale_after_seconds: int) -> int:
    """Reap runs stranded in ``running`` (scheduler duty, system-design.md).

    A hard time limit kill or a worker crash after acknowledgement can leave
    a run non-terminal with no attempt row. Anything running longer than the
    threshold (well above the hard limit) is marked failed with a timeout
    attempt. Idempotent; runs on the beat schedule.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    reaped = 0
    with session_factory() as session:
        stale = (
            session.execute(select(Run).where(Run.status == "running", Run.started_at < cutoff))
            .scalars()
            .all()
        )
        for run in stale:
            _record_attempt(session, run, "failed_timeout")
            run.status = "failed"
            run.failure_reason = "reaped: exceeded the stale run threshold"
            run.finished_at = datetime.now(UTC)
            reaped += 1
        session.commit()
    return reaped


def compute_leaderboard_cis(*, session_factory: SessionFactory, resamples: int = 1000) -> int:
    """Recompute bootstrap intervals for every leaderboard cell (issue #23).

    Reads per-trace (cost, is_correct) samples for complete runs, bootstraps
    each (agent, task, provider, model, rubric) cell, and upserts
    ``aggregates.leaderboard_ci``. Deterministic per cell, so reruns are
    idempotent; scheduled on the beat alongside the view refresh.
    """
    from agent_arena.db.models import LeaderboardCi

    from apps.runner.statistics import bootstrap_cell

    statement = (
        select(
            Run.agent_id,
            Run.task_id,
            Run.provider,
            Run.model,
            Score.rubric_hash,
            TraceMetadata.estimated_cost_usd,
            Score.is_correct,
        )
        .join(Attempt, Attempt.run_id == Run.id)
        .join(TraceMetadata, TraceMetadata.attempt_id == Attempt.id)
        .join(Score, Score.trace_hash == TraceMetadata.hash)
        .where(Run.status == "complete")
    )
    updated = 0
    with session_factory() as session:
        cells: dict[tuple[Any, ...], list[tuple[Decimal, bool]]] = {}
        for row in session.execute(statement):
            key = (row.agent_id, row.task_id, row.provider, row.model, row.rubric_hash)
            cells.setdefault(key, []).append((row.estimated_cost_usd, row.is_correct))
        for key, samples in cells.items():
            agent_id, task_id, provider, model, rubric_hash = key
            result = bootstrap_cell(
                samples,
                seed_key=f"{agent_id}:{task_id}:{provider}:{model}:{rubric_hash}",
                resamples=resamples,
            )
            session.merge(
                LeaderboardCi(
                    agent_id=agent_id,
                    task_id=task_id,
                    provider=provider,
                    model=model,
                    rubric_hash=rubric_hash,
                    accuracy=Decimal(str(round(result.accuracy, 4))),
                    accuracy_ci_low=Decimal(str(round(result.accuracy_ci_low, 4))),
                    accuracy_ci_high=Decimal(str(round(result.accuracy_ci_high, 4))),
                    cpca_usd=result.cpca,
                    cpca_ci_low_usd=result.cpca_ci_low,
                    cpca_ci_high_usd=result.cpca_ci_high,
                    resamples=result.resamples,
                    computed_at=datetime.now(UTC),
                )
            )
            updated += 1
        session.commit()
    return updated


def find_stuck_queued_runs(
    *, session_factory: SessionFactory, stuck_after_seconds: int
) -> list[uuid.UUID]:
    """Runs sitting in ``queued`` past the threshold (scheduler duty).

    A producer accident or a task that died before execution leaves a run
    queued with no message behind it. Re-enqueueing is safe because
    execution is idempotent: a duplicate message finds the run terminal or
    completes it from cache.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=stuck_after_seconds)
    with session_factory() as session:
        rows = session.execute(select(Run.id).where(Run.status == "queued", Run.queued_at < cutoff))
        return [row[0] for row in rows]
