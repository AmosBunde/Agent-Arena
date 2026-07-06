"""Unit tests for the adapter value types and capability negotiation."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from agent_arena.adapters import (
    AdapterResponse,
    AgentAdapter,
    Capability,
    Message,
    TokenUsage,
    Tool,
    ToolCall,
    missing_capabilities,
    supports,
)


class FakeAdapter:
    """Minimal protocol-conforming adapter for tests."""

    def __init__(
        self, model: str, *, caps: frozenset[Capability] = frozenset({Capability.CHAT})
    ) -> None:
        self.provider = "fake"
        self.model = model
        self._caps = caps

    def capabilities(self) -> frozenset[Capability]:
        return self._caps

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse:
        return AdapterResponse(
            provider=self.provider,
            model=self.model,
            content="ok",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=5),
            latency_ms=1,
        )

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        return Decimal("0")


def test_token_usage_total() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=7, cached_tokens=4)
    assert usage.total_tokens == 17


def test_value_types_are_immutable() -> None:
    call = ToolCall(id="1", name="search", arguments={"q": "x"})
    msg = Message(role="assistant", tool_calls=(call,))
    assert msg.tool_calls[0].name == "search"
    tool = Tool(name="search", description="d", parameters={"type": "object"})
    assert tool.parameters["type"] == "object"


def test_fake_adapter_satisfies_protocol() -> None:
    adapter = FakeAdapter("m")
    assert isinstance(adapter, AgentAdapter)


def test_chat_returns_normalised_response() -> None:
    adapter = FakeAdapter("m")
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "ok"
    assert response.usage.total_tokens == 8
    assert response.provider_metadata == {}


def test_capability_negotiation() -> None:
    adapter = FakeAdapter("m", caps=frozenset({Capability.CHAT, Capability.STREAMING}))
    assert supports(adapter, {Capability.CHAT})
    assert not supports(adapter, {Capability.TOOL_CALLING})
    assert missing_capabilities(adapter, {Capability.CHAT, Capability.TOOL_CALLING}) == (
        frozenset({Capability.TOOL_CALLING})
    )
    assert missing_capabilities(adapter, {Capability.CHAT}) == frozenset()
