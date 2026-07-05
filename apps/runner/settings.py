"""Runner configuration from environment variables.

Provider API keys are read by the adapters themselves and never pass through
this module (system-design.md, Security).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    """Environment-derived runner configuration."""

    database_url: str
    redis_url: str
    # Ceiling on agent loop turns when the task does not set max_turns.
    default_max_turns: int
    # Amortised cost of local compute for local model adapters (ADR-0004).
    # Defaults to zero, which makes local models look free; deployments that
    # care set LOCAL_HOURLY_RATE_USD.
    local_hourly_rate_usd: Decimal
    # Celery hard time limit per run (session-design.md: default ten minutes).
    run_time_limit_seconds: int
    # Soft limit fires SoftTimeLimitExceeded inside the task shortly before
    # the hard kill so the run can be marked failed_timeout cleanly.
    run_soft_time_limit_seconds: int

    @classmethod
    def from_env(cls) -> RunnerSettings:
        hard = int(os.environ.get("RUNNER_TIME_LIMIT_SECONDS", "600"))
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://arena:arena@localhost:5432/arena",
            ),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            default_max_turns=int(os.environ.get("RUNNER_DEFAULT_MAX_TURNS", "8")),
            local_hourly_rate_usd=Decimal(os.environ.get("LOCAL_HOURLY_RATE_USD", "0")),
            run_time_limit_seconds=hard,
            run_soft_time_limit_seconds=int(
                os.environ.get("RUNNER_SOFT_TIME_LIMIT_SECONDS", str(max(hard - 30, 1)))
            ),
        )
