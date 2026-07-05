"""Trace store access for the API service.

The API reads trace bodies for the trace browser and re-scoring; only the
runner writes them. Tests override the dependency with a local store.
"""

from __future__ import annotations

import os

from agent_arena.trace_store import TraceStore, store_from_url

_store: TraceStore | None = None


def get_trace_store() -> TraceStore:
    global _store
    if _store is None:
        _store = store_from_url(os.environ.get("TRACE_STORE_URL", "data/traces"))
    return _store
