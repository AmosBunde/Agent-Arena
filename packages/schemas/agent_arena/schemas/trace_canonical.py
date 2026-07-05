"""Canonical JSON serialisation for traces.

Two structurally identical traces must serialise to identical bytes so their
SHA-256 hashes match (ADR-0003). The rules, version 1:

- Only JSON types are accepted: mapping, sequence, str, int, float, bool,
  None. Anything else raises ``CanonicalisationError``.
- Object keys must be strings. Keys are sorted by Unicode code point after
  normalisation.
- Every string, including keys, is normalised to Unicode NFC, so composed
  and decomposed forms of the same text serialise identically.
- Two distinct keys that normalise to the same NFC string are a collision
  and raise rather than silently dropping data.
- No whitespace: separators are ``,`` and ``:``.
- Output is UTF-8 bytes with non-ASCII characters unescaped.
- Floats render through Python's shortest round-trip ``repr``, which is
  identical for IEEE 754 doubles across Linux, macOS, and Windows on
  CPython. ``NaN`` and infinities are not JSON and raise. Negative zero
  normalises to ``0.0``. Integral floats keep their trailing ``.0`` so the
  int versus float distinction survives (``1`` and ``1.0`` hash differently).

Changes to these rules change every future hash and therefore go through the
ADR amendment process (ADR-0003).
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

CANONICAL_VERSION = 1


class CanonicalisationError(ValueError):
    """The value cannot be represented in canonical JSON."""


def canonicalise(value: Any) -> Any:
    """Return a normalised copy of ``value`` ready for serialisation."""
    return _normalise(value, path="$")


def canonical_json(value: Any) -> bytes:
    """Serialise ``value`` to canonical JSON bytes."""
    normalised = canonicalise(value)
    text = json.dumps(
        normalised,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


def trace_hash(value: Any) -> str:
    """The SHA-256 hex digest of the canonical JSON form of ``value``."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _normalise(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CanonicalisationError(f"{path}: NaN and infinity are not JSON")
        if value == 0.0:
            return 0.0
        return value
    if isinstance(value, bytes | bytearray):
        # bytes satisfy Sequence and would silently become integer lists.
        raise CanonicalisationError(f"{path}: bytes cannot be represented in canonical JSON")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalisationError(
                    f"{path}: object keys must be strings, got {type(key).__name__}"
                )
            normalised_key = unicodedata.normalize("NFC", key)
            if normalised_key in result:
                raise CanonicalisationError(
                    f"{path}: keys {key!r} and another key collide after NFC normalisation"
                )
            result[normalised_key] = _normalise(item, path=f"{path}.{normalised_key}")
        return result
    if isinstance(value, Sequence):
        return [_normalise(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise CanonicalisationError(
        f"{path}: type {type(value).__name__} cannot be represented in canonical JSON"
    )
