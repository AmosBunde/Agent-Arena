"""Unit tests for the Pareto front (issue #24): synthetic known fronts."""

from __future__ import annotations

from decimal import Decimal

from apps.api.pareto import ParetoPoint, dominates, front_keys


def _point(key: str, cost: str, accuracy: str) -> ParetoPoint:
    return ParetoPoint(key=key, mean_cost_usd=Decimal(cost), accuracy=Decimal(accuracy))


def test_dominates_semantics() -> None:
    cheap_good = _point("a", "0.01", "0.9")
    pricey_bad = _point("b", "0.05", "0.5")
    assert dominates(cheap_good, pricey_bad)
    assert not dominates(pricey_bad, cheap_good)
    # Equal points do not dominate each other.
    twin = _point("c", "0.01", "0.9")
    assert not dominates(cheap_good, twin)
    assert not dominates(twin, cheap_good)


def test_known_front_staircase() -> None:
    points = [
        _point("cheap-weak", "0.01", "0.40"),
        _point("mid", "0.03", "0.70"),
        _point("pricey-strong", "0.10", "0.95"),
        _point("dominated-1", "0.04", "0.60"),
        _point("dominated-2", "0.12", "0.90"),
    ]
    assert front_keys(points) == {"cheap-weak", "mid", "pricey-strong"}


def test_single_point_is_the_front() -> None:
    assert front_keys([_point("only", "0.02", "0.5")]) == {"only"}


def test_one_point_dominating_all() -> None:
    points = [
        _point("best", "0.01", "0.99"),
        _point("worse-1", "0.02", "0.90"),
        _point("worse-2", "0.05", "0.99"),
        _point("worse-3", "0.01", "0.50"),
    ]
    assert front_keys(points) == {"best"}


def test_exact_ties_are_all_on_the_front() -> None:
    points = [
        _point("twin-1", "0.02", "0.80"),
        _point("twin-2", "0.02", "0.80"),
        _point("dominated", "0.03", "0.70"),
    ]
    assert front_keys(points) == {"twin-1", "twin-2"}


def test_equal_cost_different_accuracy() -> None:
    points = [
        _point("strong", "0.02", "0.90"),
        _point("weak", "0.02", "0.60"),
    ]
    assert front_keys(points) == {"strong"}


def test_empty_input() -> None:
    assert front_keys([]) == set()
