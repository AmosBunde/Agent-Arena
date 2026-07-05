"""Acceptance tests for issue #15.

Structurally identical traces serialise to identical bytes and hash equal;
the property tests generate arbitrary JSON documents and prove key order
independence, idempotence, and round-trip stability.
"""

from __future__ import annotations

import json
import math
import unicodedata

import pytest
from agent_arena.schemas import (
    CanonicalisationError,
    canonical_json,
    canonicalise,
    trace_hash,
)
from hypothesis import given
from hypothesis import strategies as st

COMPOSED = "café"
DECOMPOSED = "café"


def test_key_order_does_not_change_the_hash() -> None:
    a = {"alpha": 1, "beta": [1, 2, {"x": True, "y": None}]}
    b = {"beta": [1, 2, {"y": None, "x": True}], "alpha": 1}
    assert trace_hash(a) == trace_hash(b)


def test_output_has_sorted_keys_and_no_whitespace() -> None:
    body = canonical_json({"b": 1, "a": {"d": 2, "c": 3}})
    assert body == b'{"a":{"c":3,"d":2},"b":1}'


def test_unicode_nfc_equivalence() -> None:
    assert COMPOSED != DECOMPOSED
    assert trace_hash({"text": COMPOSED}) == trace_hash({"text": DECOMPOSED})
    assert trace_hash({COMPOSED: 1}) == trace_hash({DECOMPOSED: 1})


def test_non_ascii_is_not_escaped() -> None:
    assert canonical_json({"text": COMPOSED}) == f'{{"text":"{COMPOSED}"}}'.encode()


def test_nfc_key_collision_raises() -> None:
    with pytest.raises(CanonicalisationError, match="collide"):
        canonical_json({COMPOSED: 1, DECOMPOSED: 2})


def test_float_rendering_is_shortest_roundtrip() -> None:
    assert canonical_json({"x": 0.1}) == b'{"x":0.1}'
    assert canonical_json({"x": 1e300}) == b'{"x":1e+300}'


def test_negative_zero_normalises() -> None:
    assert trace_hash({"x": -0.0}) == trace_hash({"x": 0.0})


def test_int_and_float_hash_differently() -> None:
    assert trace_hash({"x": 1}) != trace_hash({"x": 1.0})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_rejected(bad: float) -> None:
    with pytest.raises(CanonicalisationError, match="NaN"):
        canonical_json({"x": bad})


@pytest.mark.parametrize("bad", [{1: "a"}, {"x": {2.5: "b"}}])
def test_non_string_keys_rejected(bad: object) -> None:
    with pytest.raises(CanonicalisationError, match="keys must be strings"):
        canonical_json(bad)


@pytest.mark.parametrize("bad", [b"bytes", {"x": b"bytes"}, {"x": {1, 2}}, object()])
def test_non_json_types_rejected(bad: object) -> None:
    with pytest.raises(CanonicalisationError):
        canonical_json(bad)


def test_bools_are_not_integers() -> None:
    assert canonical_json({"x": True}) == b'{"x":true}'
    assert trace_hash({"x": True}) != trace_hash({"x": 1})


# Arbitrary JSON documents: finite floats, text, nested containers.
_json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**63), max_value=2**63)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=25,
)


@given(_json_values)
def test_property_canonicalise_is_idempotent(value: object) -> None:
    once = canonicalise(value)
    assert canonicalise(once) == once


@given(_json_values)
def test_property_roundtrip_preserves_canonical_form(value: object) -> None:
    body = canonical_json(value)
    assert json.loads(body.decode("utf-8")) == _nan_safe(canonicalise(value))


@given(st.dictionaries(st.text(max_size=10), _json_values, max_size=8))
def test_property_key_insertion_order_is_irrelevant(value: dict[str, object]) -> None:
    reordered = dict(reversed(list(value.items())))
    try:
        assert trace_hash(value) == trace_hash(reordered)
    except CanonicalisationError:
        # NFC key collisions are rejected consistently for both orders.
        with pytest.raises(CanonicalisationError):
            trace_hash(reordered)


@given(st.text())
def test_property_nfc_equivalent_strings_hash_equal(text: str) -> None:
    composed = unicodedata.normalize("NFC", text)
    decomposed = unicodedata.normalize("NFD", text)
    assert trace_hash({"v": composed}) == trace_hash({"v": decomposed})


def _nan_safe(value: object) -> object:
    """Identity helper; kept so the round-trip assert reads clearly.

    Floats that survive canonicalisation are finite, so json.loads returns
    an equal value except for the int/float boundary cases Python equates
    (for example 1 == 1.0), which equality already treats as equal.
    """
    assert not isinstance(value, float) or not math.isnan(value)
    return value
