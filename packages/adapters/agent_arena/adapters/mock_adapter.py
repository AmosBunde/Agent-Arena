"""Mock adapter for benchmarking and deployment verification.

A deterministic, zero cost, zero latency provider: the answer is the text
after the ``Answer with exactly:`` marker in the last user message, or
``42`` when no marker is present. It exists so operators can measure end to
end run throughput of a deployment (issue #33) and exercise the full
pipeline without provider credentials or spend. It is a real registered
adapter and appears on leaderboards like any other provider; its cost is
honestly zero.
"""

from __future__ import annotations

from decimal import Decimal

from agent_arena.adapters.base import (
    AdapterResponse,
    Capability,
    Message,
    TokenUsage,
    Tool,
)
from agent_arena.adapters.registry import register

_PROVIDER = "mock"
ANSWER_MARKER = "Answer with exactly:"


@register(_PROVIDER)
class MockAdapter:
    """``AgentAdapter`` implementation that answers deterministically."""

    provider = _PROVIDER

    def __init__(self, model: str = "mock-1", **_kwargs: object) -> None:
        self.model = model

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT, Capability.TOOL_CALLING})

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        return Decimal("0")

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse:
        content = "42"
        for message in reversed(messages):
            if message.role == "user" and message.content and ANSWER_MARKER in message.content:
                content = message.content.split(ANSWER_MARKER, 1)[1].strip()
                break
        return AdapterResponse(
            provider=self.provider,
            model=self.model,
            content=content,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            latency_ms=1,
            finish_reason="stop",
        )
