"""Mock adapter tests (issue #33)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from agent_arena.adapters import AgentAdapter, Message, TokenUsage
from agent_arena.adapters.mock_adapter import MockAdapter
from agent_arena.adapters.registry import default_registry


def test_registered_and_satisfies_protocol() -> None:
    assert default_registry().is_registered("mock")
    assert isinstance(MockAdapter(), AgentAdapter)


def test_answers_the_marker_deterministically() -> None:
    adapter = MockAdapter()
    response = asyncio.run(
        adapter.chat([Message(role="user", content="Benchmark. Answer with exactly: 480")])
    )
    assert response.content == "480"
    again = asyncio.run(
        adapter.chat([Message(role="user", content="Benchmark. Answer with exactly: 480")])
    )
    assert again.content == response.content


def test_defaults_to_42_without_marker() -> None:
    adapter = MockAdapter()
    response = asyncio.run(adapter.chat([Message(role="user", content="anything")]))
    assert response.content == "42"


def test_cost_is_zero() -> None:
    assert MockAdapter().estimate_cost(TokenUsage(10_000, 10_000)) == Decimal("0")
