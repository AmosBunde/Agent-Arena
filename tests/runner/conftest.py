"""Fixtures for runner tests: a scripted in-memory adapter."""

from __future__ import annotations

from decimal import Decimal

import pytest
from agent_arena.adapters import (
    AdapterResponse,
    Capability,
    Message,
    TokenUsage,
    Tool,
    ToolCall,
)


class FakeAdapter:
    """Plays back scripted responses and records every chat call."""

    provider = "fake"

    def __init__(
        self,
        model: str = "fake-model",
        responses: list[AdapterResponse] | None = None,
        capabilities: frozenset[Capability] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.model = model
        self._responses = list(responses or [])
        self._capabilities = capabilities or frozenset({Capability.CHAT, Capability.TOOL_CALLING})
        self._error = error
        self.calls: list[dict[str, object]] = []

    def __call__(self, model: str = "fake-model", **kwargs: object) -> FakeAdapter:
        """Act as an adapter factory so instances can be registered directly.

        The registry validates protocol methods on the factory itself, which
        is designed for adapter classes; a scripted instance returns itself.
        """
        return self

    def capabilities(self) -> frozenset[Capability]:
        return self._capabilities

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "temperature": temperature,
            }
        )
        if self._error is not None:
            raise self._error
        return self._responses.pop(0)

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        return Decimal("0.000001") * usage.total_tokens


def response(
    content: str | None,
    *,
    tool_calls: tuple[ToolCall, ...] = (),
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cached_tokens: int = 0,
    latency_ms: int = 100,
) -> AdapterResponse:
    return AdapterResponse(
        provider="fake",
        model="fake-model",
        content=content,
        usage=TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        ),
        latency_ms=latency_ms,
        finish_reason="stop" if not tool_calls else "tool_use",
        tool_calls=tool_calls,
    )


@pytest.fixture()
def fake_adapter_factory():  # type: ignore[no-untyped-def]
    return FakeAdapter
