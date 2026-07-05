"""vLLM adapter.

Self-hosted vLLM exposes an OpenAI-compatible endpoint, so this adapter
reuses the ``openai`` async SDK pointed at the vLLM base URL and the message
and tool normalisation from the OpenAI adapter (ADR-0002). Cost follows the
local model rule from ADR-0004, exactly like Ollama: no per-token price;
the authoritative latency-aware cost ``(latency_seconds / 3600) *
hourly_rate`` is computed where the latency is known and surfaced as
``provider_metadata["cost_usd"]``, which the runner persists. The
``estimate_cost`` protocol method carries no latency and therefore returns
the latency-independent token cost, honestly zero for a local model. An
unpriced model still runs; it simply reports no cost.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

from agent_arena.adapters.base import (
    AdapterResponse,
    Capability,
    Message,
    TokenUsage,
    Tool,
)
from agent_arena.adapters.openai_adapter import (
    _parse_tool_calls,
    _to_openai_messages,
    _to_openai_tools,
    _to_token_usage,
)
from agent_arena.adapters.registry import register
from agent_arena.cost_models import CostModelError, PricingTable, default_pricing
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
    omit,
)

_PROVIDER = "vllm"
_DEFAULT_BASE_URL = "http://localhost:8000/v1"
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECONDS = 0.5

_RETRYABLE_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)


@register(_PROVIDER)
class VLLMAdapter:
    """``AgentAdapter`` implementation for a self-hosted vLLM server."""

    provider = _PROVIDER

    def __init__(
        self,
        model: str,
        *,
        client: AsyncOpenAI | None = None,
        base_url: str | None = None,
        hourly_rate: Decimal = Decimal("0"),
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_backoff_seconds: float = _DEFAULT_BASE_BACKOFF_SECONDS,
        pricing: PricingTable | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._base_url = base_url or os.environ.get("VLLM_BASE_URL", _DEFAULT_BASE_URL)
        self._hourly_rate = hourly_rate
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._pricing = pricing
        self._clock = clock or date.today

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT, Capability.TOOL_CALLING})

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        # Latency-independent share only; see the module docstring. The
        # latency-aware cost is attached to chat responses as ``cost_usd``.
        table = self._pricing or default_pricing()
        return table.estimate_cost(_PROVIDER, self.model, usage, at=self._clock())

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse:
        oai_messages = _to_openai_messages(messages)
        oai_tools = _to_openai_tools(tools) if tools else None

        async def call() -> AdapterResponse:
            client = self._resolve_client()
            start = time.monotonic()
            completion = await client.chat.completions.create(
                model=self.model,
                messages=oai_messages,
                tools=oai_tools if oai_tools is not None else omit,
                temperature=temperature if temperature is not None else omit,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            choice = completion.choices[0]
            usage = _to_token_usage(completion.usage)
            metadata: dict[str, Any] = {"id": completion.id, "base_url": self._base_url}
            self._attach_cost(metadata, usage, latency_ms)
            return AdapterResponse(
                provider=self.provider,
                model=self.model,
                content=choice.message.content,
                usage=usage,
                latency_ms=latency_ms,
                finish_reason=choice.finish_reason,
                tool_calls=_parse_tool_calls(choice.message),
                provider_metadata=metadata,
            )

        return await self._with_retry(call)

    def _attach_cost(self, metadata: dict[str, Any], usage: TokenUsage, latency_ms: int) -> None:
        """Latency-aware local cost, recorded like the Ollama adapter does."""
        metadata["hourly_rate"] = str(self._hourly_rate)
        table = self._pricing or default_pricing()
        try:
            cost = table.estimate_cost(
                _PROVIDER,
                self.model,
                usage,
                at=self._clock(),
                latency_ms=latency_ms,
                hourly_rate=self._hourly_rate,
            )
        except CostModelError:
            return
        metadata["cost_usd"] = str(cost)

    def _resolve_client(self) -> AsyncOpenAI:
        if self._client is None:
            # vLLM ignores the key but the SDK requires one.
            self._client = AsyncOpenAI(base_url=self._base_url, api_key="EMPTY")
        return self._client

    async def _with_retry(
        self, factory: Callable[[], Awaitable[AdapterResponse]]
    ) -> AdapterResponse:
        attempt = 0
        while True:
            try:
                return await factory()
            except _RETRYABLE_ERRORS:
                attempt += 1
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(self._base_backoff_seconds * (2 ** (attempt - 1)))
