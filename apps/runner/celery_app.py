"""Celery application for the runner and scheduler services.

Workers start as ``celery -A apps.runner.celery_app worker`` and the
scheduler as ``celery -A apps.runner.celery_app beat``. Reliability
settings follow system-design.md: acknowledgements after completion so a
crashed worker's job is redelivered (execution is idempotent), one job
prefetched per worker, and hard time limits per run
(session-design.md, Cancellation).
"""

from __future__ import annotations

from agent_arena.db.leaderboard import REFRESH_INTERVAL_SECONDS
from celery import Celery

from apps.runner.settings import RunnerSettings

settings = RunnerSettings.from_env()

celery_app = Celery("agent_arena", broker=settings.redis_url)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.run_time_limit_seconds,
    task_soft_time_limit=settings.run_soft_time_limit_seconds,
    # Redelivery kicks in if a worker vanishes without acknowledging; keep it
    # comfortably above the hard time limit so live runs are not duplicated.
    broker_transport_options={
        "visibility_timeout": settings.run_time_limit_seconds * 2,
    },
    task_default_queue="runs",
    beat_schedule={
        "refresh-leaderboard": {
            "task": "runner.refresh_leaderboard",
            "schedule": REFRESH_INTERVAL_SECONDS,
        },
    },
)

celery_app.autodiscover_tasks(["apps.runner"])

# Importing the task module registers the tasks on the app when the worker
# starts through -A apps.runner.celery_app.
from apps.runner import tasks as tasks  # noqa: E402,F401
