"""Celery task definitions.

``runner.execute_run`` drives one agent run. ``runner.refresh_leaderboard``
and ``runner.reap_stale_runs`` are the scheduler entry points wired in the
beat schedule in ``celery_app`` (ADR-0005 and system-design.md scheduler
duties).
"""

from __future__ import annotations

import logging
import time
import uuid

import redis

# Importing the provider modules registers each adapter in the default
# registry (side effect of the @register decorator).
from agent_arena.adapters import anthropic_adapter as _anthropic  # noqa: F401
from agent_arena.adapters import bedrock_adapter as _bedrock  # noqa: F401
from agent_arena.adapters import default_registry
from agent_arena.adapters import google_adapter as _google  # noqa: F401
from agent_arena.adapters import ollama_adapter as _ollama  # noqa: F401
from agent_arena.adapters import openai_adapter as _openai  # noqa: F401
from agent_arena.adapters import vllm_adapter as _vllm  # noqa: F401
from agent_arena.db.leaderboard import refresh_leaderboard
from agent_arena.trace_store import TraceStore, store_from_url

from apps.runner.cancellation import is_cancellation_requested
from apps.runner.celery_app import STALE_RUN_REAP_INTERVAL_SECONDS, celery_app, settings
from apps.runner.db import get_engine, get_session_factory
from apps.runner.execution import compute_leaderboard_cis, execute_run_sync, fail_stale_runs
from apps.runner.judging import execute_judge_score
from apps.runner.observability import record_run, run_span

logger = logging.getLogger(__name__)

# Local model adapters take deployment-level construction arguments
# (ADR-0004: configurable hourly rate); token-priced adapters take none.
_ADAPTER_KWARGS: dict[str, dict[str, object]] = {
    "ollama": {"hourly_rate": settings.local_hourly_rate_usd},
    "vllm": {"hourly_rate": settings.local_hourly_rate_usd},
}

_redis_client: redis.Redis | None = None
_trace_store: TraceStore | None = None


def _get_trace_store() -> TraceStore:
    global _trace_store
    if _trace_store is None:
        _trace_store = store_from_url(settings.trace_store_url)
    return _trace_store


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _redis_client


def cancel_requested(run_id: uuid.UUID) -> bool:
    """Cooperative cancellation flag set by the API (session-design.md)."""
    try:
        return is_cancellation_requested(_get_redis(), run_id)
    except redis.RedisError:  # pragma: no cover - broker outage
        logger.warning("could not read cancel flag for run %s", run_id)
        return False


class _ConfiguredRegistry:
    """The default registry with deployment-level adapter arguments applied."""

    def get_adapter(self, provider: str, model: str, **kwargs: object):  # noqa: ANN201
        merged = {**_ADAPTER_KWARGS.get(provider, {}), **kwargs}
        return default_registry().get_adapter(provider, model, **merged)


@celery_app.task(name="runner.execute_run")
def execute_run(run_id: str) -> str:
    """Execute one agent run to a terminal state."""
    parsed = uuid.UUID(run_id)
    start = time.monotonic()
    with run_span(run_id):
        outcome = execute_run_sync(
            parsed,
            session_factory=get_session_factory(settings),
            registry=_ConfiguredRegistry(),
            default_max_turns=settings.default_max_turns,
            cancel_requested=lambda: cancel_requested(parsed),
            trace_store=_get_trace_store(),
            enqueue_judge=lambda trace_hash, rubric_id: celery_app.send_task(
                "runner.judge_score", args=[trace_hash, str(rubric_id)], queue="runs"
            ),
        )
    record_run(outcome.run_status, outcome.attempt_outcome, time.monotonic() - start)
    logger.info(
        "run %s finished: status=%s attempt=%s detail=%s",
        run_id,
        outcome.run_status,
        outcome.attempt_outcome,
        outcome.detail,
    )
    return outcome.run_status


@celery_app.task(name="runner.judge_score")
def judge_score(trace_hash: str, rubric_id: str) -> str:
    """Score one trace under one judge rubric (follow-up job)."""
    status = execute_judge_score(
        trace_hash,
        uuid.UUID(rubric_id),
        session_factory=get_session_factory(settings),
        registry=_ConfiguredRegistry(),
        trace_store=_get_trace_store(),
    )
    logger.info("judge score for trace %s rubric %s: %s", trace_hash, rubric_id, status)
    return status


@celery_app.task(name="runner.refresh_leaderboard")
def refresh_leaderboard_task() -> None:
    """Refresh the leaderboard materialised view (idempotent)."""
    refresh_leaderboard(get_engine(settings))


@celery_app.task(name="runner.compute_leaderboard_ci")
def compute_leaderboard_ci() -> int:
    """Recompute bootstrap confidence intervals for leaderboard cells."""
    updated = compute_leaderboard_cis(session_factory=get_session_factory(settings))
    logger.info("computed bootstrap intervals for %d leaderboard cells", updated)
    return updated


@celery_app.task(name="runner.reap_stale_runs")
def reap_stale_runs() -> int:
    """Repair runs stranded in ``running`` by a hard kill or lost worker."""
    threshold = max(settings.run_time_limit_seconds * 2, STALE_RUN_REAP_INTERVAL_SECONDS)
    reaped = fail_stale_runs(
        session_factory=get_session_factory(settings),
        stale_after_seconds=threshold,
    )
    if reaped:
        logger.warning("reaped %d stale runs", reaped)
    return reaped
