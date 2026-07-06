"""Versioned cost model for Agent Arena.

Cost-per-correct-answer (CPCA) is the headline leaderboard metric; this package
holds the per-provider pricing data and the Decimal cost computation behind it.
See docs/adr/0004-cost-model.md.
"""

from __future__ import annotations

from agent_arena.cost_models.loader import (
    CostModelError,
    NoPriceForDateError,
    PriceLine,
    PricingTable,
    UnknownModelError,
    default_pricing,
)

__all__ = [
    "CostModelError",
    "NoPriceForDateError",
    "PriceLine",
    "PricingTable",
    "UnknownModelError",
    "default_pricing",
]
