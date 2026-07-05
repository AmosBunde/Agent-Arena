"""Local filesystem trace store.

Suitable for development and single machine deployments without MinIO.
Writes are atomic (temporary file then rename) so a crash cannot leave a
truncated body under a valid hash.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agent_arena.trace_store.base import TraceNotFoundError, object_key


class LocalTraceStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def put(self, trace_hash: str, body: bytes) -> str:
        path = self._path(trace_hash)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(body)
                os.replace(temp_name, path)
            except BaseException:
                os.unlink(temp_name)
                raise
        return path.as_uri()

    def get(self, trace_hash: str) -> bytes:
        path = self._path(trace_hash)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise TraceNotFoundError(trace_hash) from exc

    def exists(self, trace_hash: str) -> bool:
        return self._path(trace_hash).exists()

    def _path(self, trace_hash: str) -> Path:
        return self._root / object_key(trace_hash)
