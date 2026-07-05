"""The trace store protocol and shared key layout."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class TraceNotFoundError(KeyError):
    """No body is stored under the requested hash."""


def object_key(trace_hash: str) -> str:
    """The storage key for a trace hash: ``{hash[:2]}/{hash}.json``."""
    if len(trace_hash) < 3:
        raise ValueError(f"implausible trace hash {trace_hash!r}")
    return f"{trace_hash[:2]}/{trace_hash}.json"


@runtime_checkable
class TraceStore(Protocol):
    """Content-addressed, write-once storage for trace bodies.

    ``put`` is idempotent: bodies are immutable by construction because the
    key is the hash of the content, so writing the same hash twice is a
    no-op. Implementations return the URI recorded in
    ``traces.trace_metadata.body_uri``.
    """

    def put(self, trace_hash: str, body: bytes) -> str: ...

    def get(self, trace_hash: str) -> bytes: ...

    def exists(self, trace_hash: str) -> bool: ...
