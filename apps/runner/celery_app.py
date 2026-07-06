"""Celery application for the runner and scheduler services.

Workers start as ``celery -A apps.runner.celery_app worker`` and the
scheduler as ``celery -A apps.runner.celery_app beat``. Reliability
settings follow system-design.md: acknowledgements after completion so a
crashed worker's job is redelivered (execution is idempotent), one job
prefetched per worker, and hard time limits per run
(session-design.md, Cancellation).

A hard time limit kill is acknowledged by Celery and is not redelivered;
the ``runner.reap_stale_runs`` beat task repairs any run stranded in
``running`` by such a kill.
"""

from __future__ import annotations

from agent_arena.db.leaderboard import REFRESH_INTERVAL_SECONDS
from celery import Celery
from celery.signals import worker_init

from apps.runner.settings import RunnerSettings

settings = RunnerSettings.from_env()

STALE_RUN_REAP_INTERVAL_SECONDS = 600

celery_app = Celery("agent_arena", broker=settings.redis_url)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.run_time_limit_seconds,
    task_soft_time_limit=settings.run_soft_time_limit_seconds,
    # Redelivery covers workers that vanish without acknowledging; keep the
    # window comfortably above the hard time limit so live runs are not
    # duplicated. Time limit kills are acknowledged and are covered by the
    # stale run reaper instead.
    broker_transport_options={
        "visibility_timeout": settings.run_time_limit_seconds * 2,
    },
    task_default_queue="runs",
    beat_schedule={
        "refresh-leaderboard": {
            "task": "runner.refresh_leaderboard",
            "schedule": REFRESH_INTERVAL_SECONDS,
        },
        "reap-stale-runs": {
            "task": "runner.reap_stale_runs",
            "schedule": STALE_RUN_REAP_INTERVAL_SECONDS,
        },
        "compute-leaderboard-ci": {
            "task": "runner.compute_leaderboard_ci",
            "schedule": REFRESH_INTERVAL_SECONDS,
        },
    },
)

# Workers resolve apps.runner.tasks lazily at startup; no import here, which
# would be circular (tasks.py imports this module).
celery_app.autodiscover_tasks(["apps.runner"])


@worker_init.connect
def _start_observability(**_kwargs: object) -> None:
    from apps.runner.observability import setup_tracing, start_metrics_server

    start_metrics_server()
    setup_tracing()
