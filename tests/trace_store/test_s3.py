"""Integration tests for the S3 trace store against a real MinIO container."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from agent_arena.trace_store import S3TraceStore, TraceNotFoundError

pytestmark = pytest.mark.integration

HASH = "cd" + "1" * 62
BODY = b'{"answer":42,"text":"caf\xc3\xa9"}'


@pytest.fixture(scope="module")
def s3_client() -> Iterator[Any]:
    try:
        import boto3
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs
    except ImportError:  # pragma: no cover - dev dependency missing
        pytest.skip("testcontainers is not installed")

    container = (
        DockerContainer("minio/minio:RELEASE.2024-10-13T13-34-11Z")
        .with_env("MINIO_ROOT_USER", "arena")
        .with_env("MINIO_ROOT_PASSWORD", "arena-secret")
        .with_exposed_ports(9000)
        .with_command("server /data")
    )
    try:
        with container:
            wait_for_logs(container, "API:", timeout=60)
            endpoint = (
                f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
            )
            yield boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id="arena",
                aws_secret_access_key="arena-secret",
                region_name="us-east-1",
            )
    except Exception as exc:  # pragma: no cover - Docker unavailable
        pytest.skip(f"could not start MinIO container: {exc}")


def test_round_trip_is_byte_identical(s3_client: Any) -> None:
    store = S3TraceStore(s3_client, bucket="arena-traces")
    store.ensure_bucket()
    store.ensure_bucket()  # idempotent

    uri = store.put(HASH, BODY)
    assert uri == f"s3://arena-traces/{HASH[:2]}/{HASH}.json"
    assert store.get(HASH) == BODY
    assert store.exists(HASH)

    # Content addressing: a second put never rewrites the stored body.
    store.put(HASH, b"different")
    assert store.get(HASH) == BODY


def test_get_missing_raises(s3_client: Any) -> None:
    store = S3TraceStore(s3_client, bucket="arena-traces")
    store.ensure_bucket()
    with pytest.raises(TraceNotFoundError):
        store.get("ee" + "2" * 62)
    assert not store.exists("ee" + "2" * 62)
