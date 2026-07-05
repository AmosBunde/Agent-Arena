"""Build a trace store from a ``TRACE_STORE_URL`` value.

- ``file:///data/traces`` or a plain path: local filesystem store.
- ``s3://bucket``: S3-compatible store. The endpoint and credentials come
  from the standard AWS environment variables plus ``S3_ENDPOINT_URL`` for
  MinIO and other non-AWS endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from agent_arena.trace_store.base import TraceStore
from agent_arena.trace_store.local import LocalTraceStore
from agent_arena.trace_store.s3 import S3TraceStore


def store_from_url(url: str) -> TraceStore:
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        path = parsed.path if parsed.scheme == "file" else url
        return LocalTraceStore(Path(path))
    if parsed.scheme == "s3":
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
        )
        store = S3TraceStore(client, bucket=parsed.netloc)
        store.ensure_bucket()
        return store
    raise ValueError(f"unsupported trace store url {url!r}")
