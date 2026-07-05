"""Celery task definitions.

``runner.execute_run`` drives one agent run; ``runner.refresh_leaderboard``
is the scheduler entry point for the materialised view (every five minutes
per ADR-0005, wired in the beat schedule in ``celery_app``).
"""

from __future__ import annotations

import logging
import uuid

import redis

# Importing the provider modules registers each adapter in the default
# registry (side effect of the @register decorator).
from agent_arena.adapters import anthropic_adapter as _anthropic  # noqa: F401
from agent_arena.adapters import default_registry
from agent_arena.adapters import google_adapter as _google  # noqa: F401
from agent_arena.adapters import ollama_adapter as _ollama  # noqa: F401
from agent_arena.adapters import openai_adapter as _openai  # noqa: F401
from agent_arena.db.leaderboard import refresh_leaderboard

from apps.runner.celery_app import celery_app, settings
from apps.runner.db import get_engine, get_session_factory
from apps.runner.execution import execute_run_sync

logger = logging.getLogger(__name__)

CANCEL_KEY_TEMPLATE = "arena:run:{run_id}:cancel"

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.redis_url)
    return _redis_client


def cancel_requested(run_id: uuid.UUID) -> bool:
    """Cooperative cancellation flag set by the API (session-design.md)."""
    try:
        return bool(_get_redis().exists(CANCEL_KEY_TEMPLATE.format(run_id=run_id)))
    except redis.RedisError:  # pragma: no cover - broker outage
        logger.warning("could not read cancel flag for run %s", run_id)
        return False


@celery_app.task(name="runner.execute_run")
def execute_run(run_id: str) -> str:
    """Execute one agent run to a terminal state."""
    parsed = uuid.UUID(run_id)
    outcome = execute_run_sync(
        parsed,
        session_factory=get_session_factory(settings),
        registry=default_registry(),
        default_max_turns=settings.default_max_turns,
        cancel_requested=lambda: cancel_requested(parsed),
    )
    logger.info(
        "run %s finished: status=%s attempt=%s detail=%s",
        run_id,
        outcome.run_status,
        outcome.attempt_outcome,
        outcome.detail,
    )
    return outcome.run_status


@celery_app.task(name="runner.refresh_leaderboard")
def refresh_leaderboard_task() -> None:
    """Refresh the leaderboard materialised view (idempotent)."""
    refresh_leaderboard(get_engine(settings))
