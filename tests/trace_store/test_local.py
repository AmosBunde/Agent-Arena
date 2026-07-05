"""Unit tests for the local filesystem trace store."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_arena.trace_store import LocalTraceStore, TraceNotFoundError, object_key

HASH = "ab" + "0" * 62
BODY = b'{"answer":42,"text":"caf\xc3\xa9"}'


def test_round_trip_is_byte_identical(tmp_path: Path) -> None:
    store = LocalTraceStore(tmp_path)
    uri = store.put(HASH, BODY)
    assert store.get(HASH) == BODY
    assert uri.startswith("file://")
    assert uri.endswith(f"{HASH[:2]}/{HASH}.json")


def test_key_layout(tmp_path: Path) -> None:
    assert object_key(HASH) == f"ab/{HASH}.json"
    store = LocalTraceStore(tmp_path)
    store.put(HASH, BODY)
    assert (tmp_path / "ab" / f"{HASH}.json").read_bytes() == BODY


def test_put_is_idempotent_and_write_once(tmp_path: Path) -> None:
    store = LocalTraceStore(tmp_path)
    store.put(HASH, BODY)
    # Content addressing: the same hash means the same content, so a second
    # put never rewrites the stored body.
    store.put(HASH, b"different")
    assert store.get(HASH) == BODY


def test_exists(tmp_path: Path) -> None:
    store = LocalTraceStore(tmp_path)
    assert not store.exists(HASH)
    store.put(HASH, BODY)
    assert store.exists(HASH)


def test_get_missing_raises(tmp_path: Path) -> None:
    store = LocalTraceStore(tmp_path)
    with pytest.raises(TraceNotFoundError):
        store.get(HASH)


def test_implausible_hash_rejected(tmp_path: Path) -> None:
    store = LocalTraceStore(tmp_path)
    with pytest.raises(ValueError, match="implausible"):
        store.put("ab", BODY)
