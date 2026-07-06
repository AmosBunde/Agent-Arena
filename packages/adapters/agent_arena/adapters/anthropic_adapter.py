"""Anthropic adapter.

Wraps the ``anthropic`` async SDK behind the ``AgentAdapter`` protocol. System
prompts map to Anthropic's top-level ``system`` parameter; tool use maps to
``tool_use``/``tool_result`` content blocks. Cache-read tokens are accounted
separately from fresh input tokens (issue #5). Cost is delegated to the
versioned cost model (ADR-0004).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any, cast

from agent_arena.adapters.base import (
    AdapterResponse,
    Capability,
    Message,
    TokenUsage,
    Tool,
    ToolCall,
)
from agent_arena.adapters.registry import register
from agent_arena.cost_models import PricingTable, default_pricing
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AsyncAnthropic,
    InternalServerError,
    RateLimitError,
    omit,
)
from anthropic.types import Message as AnthropicMessage
from anthropic.types import MessageParam, TextBlock, ToolUseBlock, Usage

_PROVIDER = "anthropic"
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECONDS = 0.5
_DEFAULT_MAX_TOKENS = 4096

_RETRYABLE_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)


@register(_PROVIDER)
class AnthropicAdapter:
    """``AgentAdapter`` implementation backed by the Anthropic SDK."""

    provider = _PROVIDER

    def __init__(
        self,
        model: str,
        *,
        client: AsyncAnthropic | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_backoff_seconds: float = _DEFAULT_BASE_BACKOFF_SECONDS,
        pricing: PricingTable | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._pricing = pricing
        self._clock = clock or date.today

    def capabilities(self) -> frozenset[Capability]:
        return frozenset(
            {
                Capability.CHAT,
                Capability.TOOL_CALLING,
                Capability.STREAMING,
                Capability.PROMPT_CACHING,
            }
        )

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        table = self._pricing or default_pricing()
        return table.estimate_cost(_PROVIDER, self.model, usage, at=self._clock())

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse:
        system, anthropic_messages = _to_anthropic_messages(messages)
        system_arg = system if system is not None else omit
        temperature_arg = temperature if temperature is not None else omit
        # tools is an invariant union list in the SDK; widen to Any.
        tools_arg: Any = _to_anthropic_tools(tools) if tools else omit

        async def call() -> AdapterResponse:
            client = self._resolve_client()
            start = time.monotonic()
            message: AnthropicMessage
            if stream:
                async with client.messages.stream(
                    model=self.model,
                    max_tokens=self._max_tokens,
                    messages=anthropic_messages,
                    system=system_arg,
                    temperature=temperature_arg,
                    tools=tools_arg,
                ) as streamed:
                    message = await streamed.get_final_message()
            else:
                message = await client.messages.create(
                    model=self.model,
                    max_tokens=self._max_tokens,
                    messages=anthropic_messages,
                    system=system_arg,
                    temperature=temperature_arg,
                    tools=tools_arg,
                )
            latency_ms = int((time.monotonic() - start) * 1000)
            content, tool_calls = _parse_content(message)
            return AdapterResponse(
                provider=self.provider,
                model=self.model,
                content=content,
                usage=_to_token_usage(message.usage),
                latency_ms=latency_ms,
                finish_reason=message.stop_reason,
                tool_calls=tool_calls,
                provider_metadata={"id": message.id, "model": message.model},
            )

        return await self._with_retry(call)

    def _resolve_client(self) -> AsyncAnthropic:
        if self._client is None:
            self._client = AsyncAnthropic()
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


def _to_anthropic_messages(
    messages: list[Message],
) -> tuple[str | None, list[MessageParam]]:
    system_parts: list[str] = []
    out: list[MessageParam] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
        elif message.role == "tool":
            out.append(
                cast(
                    MessageParam,
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content or "",
                            }
                        ],
                    },
                )
            )
        elif message.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            out.append(cast(MessageParam, {"role": "assistant", "content": blocks}))
        else:
            out.append(cast(MessageParam, {"role": "user", "content": message.content or ""}))
    system = "\n".join(system_parts) if system_parts else None
    return system, out


def _to_anthropic_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }
        for tool in tools
    ]


def _parse_content(message: AnthropicMessage) -> tuple[str | None, tuple[ToolCall, ...]]:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            tool_calls.append(
                ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=cast(dict[str, Any], block.input),
                )
            )
    content = "".join(text_parts) if text_parts else None
    return content, tuple(tool_calls)


def _to_token_usage(usage: Usage) -> TokenUsage:
    # Anthropic's input_tokens excludes cache reads/creation, but the cost model
    # expects prompt_tokens to include the cached subset. Fold both cache
    # buckets into prompt_tokens; report cache reads as the cached subset.
    cache_read = usage.cache_read_input_tokens or 0
    cache_creation = usage.cache_creation_input_tokens or 0
    return TokenUsage(
        prompt_tokens=usage.input_tokens + cache_read + cache_creation,
        completion_tokens=usage.output_tokens,
        cached_tokens=cache_read,
    )
