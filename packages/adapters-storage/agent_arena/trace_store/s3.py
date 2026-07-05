"""S3-compatible trace store (MinIO in Compose, any S3 store elsewhere)."""

from __future__ import annotations

from typing import Any

from agent_arena.trace_store.base import TraceNotFoundError, object_key


class S3TraceStore:
    """Trace bodies in one bucket of an S3-compatible object store.

    The boto3 client is injected so credentials and endpoint configuration
    stay with the caller (the runner builds it from environment variables;
    tests point it at a MinIO container).
    """

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def ensure_bucket(self) -> None:
        """Create the bucket when missing. Idempotent; called at startup."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except self._client.exceptions.ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def put(self, trace_hash: str, body: bytes) -> str:
        key = object_key(trace_hash)
        if not self.exists(trace_hash):
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
            )
        return f"s3://{self._bucket}/{key}"

    def get(self, trace_hash: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key(trace_hash))
        except self._client.exceptions.NoSuchKey as exc:
            raise TraceNotFoundError(trace_hash) from exc
        return bytes(response["Body"].read())

    def exists(self, trace_hash: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key(trace_hash))
        except self._client.exceptions.ClientError:
            return False
        return True
