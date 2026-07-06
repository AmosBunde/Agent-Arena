"""Pareto front over (cost, accuracy) for leaderboard cells (issue #24).

A cell dominates another when it costs no more per task and is at least as
accurate, and is strictly better on at least one of the two. The front is
the set of non-dominated cells. ADR-0004 chose CPCA as the default sort key
for the table view; the Pareto view is the complementary presentation for
the same tradeoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParetoPoint:
    key: str
    mean_cost_usd: Decimal
    accuracy: Decimal


def dominates(a: ParetoPoint, b: ParetoPoint) -> bool:
    """Whether ``a`` Pareto dominates ``b`` on (cost down, accuracy up)."""
    no_worse = a.mean_cost_usd <= b.mean_cost_usd and a.accuracy >= b.accuracy
    strictly_better = a.mean_cost_usd < b.mean_cost_usd or a.accuracy > b.accuracy
    return no_worse and strictly_better


def front_keys(points: list[ParetoPoint]) -> set[str]:
    """Keys of the non-dominated points.

    Sweep after sorting by (cost ascending, accuracy descending): a point is
    on the front exactly when its accuracy exceeds every cheaper point's
    accuracy. Duplicate (cost, accuracy) pairs are all on the front, since
    neither strictly dominates the other. O(n log n).
    """
    ordered = sorted(points, key=lambda p: (p.mean_cost_usd, -p.accuracy))
    front: set[str] = set()
    best_accuracy: Decimal | None = None
    best_cost: Decimal | None = None
    for point in ordered:
        if best_accuracy is None or point.accuracy > best_accuracy:
            front.add(point.key)
            best_accuracy = point.accuracy
            best_cost = point.mean_cost_usd
        elif (
            point.accuracy == best_accuracy
            and best_cost is not None
            and point.mean_cost_usd == best_cost
        ):
            # Exact tie with the current best: mutually non-dominating.
            front.add(point.key)
    return front
