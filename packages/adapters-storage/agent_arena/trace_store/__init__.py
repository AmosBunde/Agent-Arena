"""Content-addressed trace body storage (ADR-0003, issue #16).

Bodies are canonical JSON bytes keyed by their SHA-256 hash under
``{hash[:2]}/{hash}.json``. Two implementations: local filesystem for
development and tests, S3-compatible object storage (MinIO in Compose) for
deployments. ``store_from_url`` builds the right one from a
``TRACE_STORE_URL`` value.
"""

from __future__ import annotations

from agent_arena.trace_store.base import TraceNotFoundError, TraceStore, object_key
from agent_arena.trace_store.local import LocalTraceStore
from agent_arena.trace_store.s3 import S3TraceStore
from agent_arena.trace_store.url import store_from_url

__all__ = [
    "LocalTraceStore",
    "S3TraceStore",
    "TraceNotFoundError",
    "TraceStore",
    "object_key",
    "store_from_url",
]
