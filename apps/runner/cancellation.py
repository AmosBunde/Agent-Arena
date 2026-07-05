"""The cross-service run cancellation contract.

session-design.md specifies that ``DELETE /runs/{id}`` sets a cancel flag in
Redis and the runner checks it between provider calls. This module is the
single definition of that contract: the API (issue #9) imports
``request_cancellation`` and the runner imports ``is_cancellation_requested``.
It deliberately has no import-time side effects (no Celery application, no
settings read) so either service can import it safely.

The flag carries a TTL comfortably above the run hard time limit so abandoned
flags do not accumulate in Redis, which holds no durable state (ADR-0005).
"""

from __future__ import annotations

import uuid

import redis

CANCEL_KEY_TEMPLATE = "arena:run:{run_id}:cancel"

# One day; far above any run time limit, small enough to self-clean.
CANCEL_FLAG_TTL_SECONDS = 86_400


def cancel_key(run_id: uuid.UUID) -> str:
    return CANCEL_KEY_TEMPLATE.format(run_id=run_id)


def request_cancellation(client: redis.Redis, run_id: uuid.UUID) -> None:
    """Set the cancel flag. The runner aborts at its next checkpoint."""
    client.set(cancel_key(run_id), "1", ex=CANCEL_FLAG_TTL_SECONDS)


def is_cancellation_requested(client: redis.Redis, run_id: uuid.UUID) -> bool:
    return bool(client.exists(cancel_key(run_id)))


def clear_cancellation(client: redis.Redis, run_id: uuid.UUID) -> None:
    client.delete(cancel_key(run_id))
