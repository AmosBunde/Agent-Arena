"""Unit tests for the versioned cost model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from agent_arena.adapters import TokenUsage
from agent_arena.cost_models import (
    NoPriceForDateError,
    PricingTable,
    UnknownModelError,
    default_pricing,
)


@pytest.fixture(scope="module")
def table() -> PricingTable:
    return PricingTable.load()


def test_prices_are_decimal_not_float(table: PricingTable) -> None:
    line = table.lookup("openai", "gpt-4o", date(2024, 9, 1))
    assert isinstance(line.input_per_million, Decimal)
    # Exact source text preserved; a float round-trip would not give this.
    assert line.input_per_million == Decimal("2.50")
    assert line.output_per_million == Decimal("10.00")
    assert line.cached_input_per_million == Decimal("1.25")


def test_historical_lookup_picks_valid_from(table: PricingTable) -> None:
    before = table.lookup("openai", "gpt-4o", date(2024, 6, 1))
    after = table.lookup("openai", "gpt-4o", date(2024, 9, 1))
    assert before.valid_from == date(2024, 5, 13)
    assert after.valid_from == date(2024, 8, 6)


def test_estimate_cost_openai_after_repricing(table: PricingTable) -> None:
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, cached_tokens=200)
    cost = table.estimate_cost("openai", "gpt-4o", usage, date(2024, 9, 1))
    # 800*2.50 + 200*1.25 + 500*10.00 = 7250, per million => 0.00725
    assert cost == Decimal("0.00725")
    assert isinstance(cost, Decimal)


def test_estimate_cost_openai_before_repricing(table: PricingTable) -> None:
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, cached_tokens=200)
    cost = table.estimate_cost("openai", "gpt-4o", usage, date(2024, 6, 1))
    # 800*5.00 + 200*2.50 + 500*15.00 = 12000, per million => 0.012
    assert cost == Decimal("0.012")


def test_estimate_cost_anthropic(table: PricingTable) -> None:
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000)
    cost = table.estimate_cost("anthropic", "claude-opus-4-7", usage, date(2026, 3, 1))
    # 1000*15.00 + 1000*75.00 = 90000, per million => 0.09
    assert cost == Decimal("0.09")


def test_local_model_is_free_by_default(table: PricingTable) -> None:
    usage = TokenUsage(prompt_tokens=10_000, completion_tokens=10_000)
    cost = table.estimate_cost("ollama", "llama3.1:8b", usage, date(2025, 1, 1), latency_ms=5000)
    assert cost == Decimal("0")


def test_local_model_bills_by_wall_clock(table: PricingTable) -> None:
    usage = TokenUsage()
    cost = table.estimate_cost(
        "ollama",
        "llama3.1:8b",
        usage,
        date(2025, 1, 1),
        latency_ms=3_600_000,
        hourly_rate=Decimal("2.00"),
    )
    # One hour at 2.00/hour.
    assert cost == Decimal("2.00")


def test_unknown_model_raises(table: PricingTable) -> None:
    with pytest.raises(UnknownModelError):
        table.lookup("openai", "gpt-9-ultra", date(2024, 9, 1))


def test_no_price_before_earliest_date_raises(table: PricingTable) -> None:
    with pytest.raises(NoPriceForDateError):
        table.lookup("openai", "gpt-4o", date(2024, 1, 1))


def test_default_pricing_is_cached_and_populated() -> None:
    first = default_pricing()
    second = default_pricing()
    assert first is second
    assert first.lookup("anthropic", "claude-sonnet-4-6", date(2026, 3, 1))
