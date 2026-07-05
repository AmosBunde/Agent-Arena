"""Run queue and cancellation from the API side.

The API enqueues runner jobs by task name over a producer-only Celery
application; it never imports the runner's task code. Cancellation uses the
shared contract in ``apps.runner.cancellation`` (a side-effect-free module).
Tests override the ``get_queue`` dependency with a recording fake.
"""

from __future__ import annotations

import uuid

import redis
from celery import Celery

from apps.api.settings import ApiSettings
from apps.runner.cancellation import request_cancellation

EXECUTE_RUN_TASK = "runner.execute_run"
RUNS_QUEUE = "runs"


class RunQueue:
    """Producer-side handle on the run queue and the cancel flags."""

    def __init__(self, settings: ApiSettings) -> None:
        self._celery = Celery("agent_arena_api", broker=settings.redis_url)
        self._redis = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=5, socket_timeout=5
        )

    def enqueue_run(self, run_id: uuid.UUID) -> None:
        self._celery.send_task(EXECUTE_RUN_TASK, args=[str(run_id)], queue=RUNS_QUEUE)

    def request_cancellation(self, run_id: uuid.UUID) -> None:
        request_cancellation(self._redis, run_id)


_queue: RunQueue | None = None


def get_queue() -> RunQueue:
    """FastAPI dependency for the run queue; overridden in tests."""
    global _queue
    if _queue is None:
        _queue = RunQueue(ApiSettings.from_env())
    return _queue
