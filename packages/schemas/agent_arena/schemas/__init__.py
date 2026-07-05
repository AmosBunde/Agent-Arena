"""Shared schema definitions for Agent Arena.

The canonical trace serialisation lives in :mod:`.trace_canonical`; see
docs/adr/0003-content-addressed-trace-store.md.
"""

from __future__ import annotations

from agent_arena.schemas.trace_canonical import (
    CANONICAL_VERSION,
    CanonicalisationError,
    canonical_json,
    canonicalise,
    trace_hash,
)

__all__ = [
    "CANONICAL_VERSION",
    "CanonicalisationError",
    "canonical_json",
    "canonicalise",
    "trace_hash",
]
