"""OpenAI adapter.

Wraps the ``openai`` async SDK behind the ``AgentAdapter`` protocol: normalises
messages, tools, and token usage, measures wall-clock latency, and retries
transient failures with exponential backoff (ADR-0002, system-design failure
handling). Cost is delegated to the versioned cost model (ADR-0004).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterable, Awaitable, Callable
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
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
    omit,
)
from openai.types.chat import (
    ChatCompletionChunk,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
)
from openai.types.completion_usage import CompletionUsage

_PROVIDER = "openai"
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECONDS = 0.5

# Transient errors worth retrying; auth and bad-request errors are not here and
# so propagate immediately.
_RETRYABLE_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)


@register(_PROVIDER)
class OpenAIAdapter:
    """``AgentAdapter`` implementation backed by the OpenAI SDK."""

    provider = _PROVIDER

    def __init__(
        self,
        model: str,
        *,
        client: AsyncOpenAI | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_backoff_seconds: float = _DEFAULT_BASE_BACKOFF_SECONDS,
        pricing: PricingTable | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._pricing = pricing
        self._clock = clock or date.today

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT, Capability.TOOL_CALLING, Capability.STREAMING})

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
        oai_messages = _to_openai_messages(messages)
        oai_tools = _to_openai_tools(tools) if tools else None

        async def call() -> AdapterResponse:
            client = self._resolve_client()
            tools_arg = oai_tools if oai_tools is not None else omit
            temperature_arg = temperature if temperature is not None else omit
            start = time.monotonic()
            if stream:
                response_stream = await client.chat.completions.create(
                    model=self.model,
                    messages=oai_messages,
                    tools=tools_arg,
                    temperature=temperature_arg,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                content, tool_calls, usage, finish_reason = await _consume_stream(response_stream)
                latency_ms = int((time.monotonic() - start) * 1000)
                metadata: dict[str, Any] = {}
            else:
                completion = await client.chat.completions.create(
                    model=self.model,
                    messages=oai_messages,
                    tools=tools_arg,
                    temperature=temperature_arg,
                )
                latency_ms = int((time.monotonic() - start) * 1000)
                choice = completion.choices[0]
                content = choice.message.content
                tool_calls = _parse_tool_calls(choice.message)
                usage = _to_token_usage(completion.usage)
                finish_reason = choice.finish_reason
                metadata = {
                    "id": completion.id,
                    "system_fingerprint": completion.system_fingerprint,
                }
            return AdapterResponse(
                provider=self.provider,
                model=self.model,
                content=content,
                usage=usage,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                provider_metadata=metadata,
            )

        return await self._with_retry(call)

    def _resolve_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI()
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


def _to_openai_messages(messages: list[Message]) -> list[ChatCompletionMessageParam]:
    out: list[ChatCompletionMessageParam] = []
    for message in messages:
        if message.role == "assistant":
            payload: dict[str, Any] = {"role": "assistant"}
            if message.content is not None:
                payload["content"] = message.content
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in message.tool_calls
                ]
            out.append(cast(ChatCompletionMessageParam, payload))
        elif message.role == "tool":
            out.append(
                cast(
                    ChatCompletionMessageParam,
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content or "",
                    },
                )
            )
        else:
            out.append(
                cast(
                    ChatCompletionMessageParam,
                    {"role": message.role, "content": message.content or ""},
                )
            )
    return out


def _to_openai_tools(tools: list[Tool]) -> list[ChatCompletionFunctionToolParam]:
    return [
        cast(
            ChatCompletionFunctionToolParam,
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            },
        )
        for tool in tools
    ]


def _parse_tool_calls(message: ChatCompletionMessage) -> tuple[ToolCall, ...]:
    if not message.tool_calls:
        return ()
    calls: list[ToolCall] = []
    for tool_call in message.tool_calls:
        if tool_call.type != "function":
            continue
        raw = tool_call.function.arguments
        arguments = cast(dict[str, Any], json.loads(raw)) if raw else {}
        calls.append(ToolCall(id=tool_call.id, name=tool_call.function.name, arguments=arguments))
    return tuple(calls)


def _to_token_usage(usage: CompletionUsage | None) -> TokenUsage:
    if usage is None:
        return TokenUsage()
    cached = 0
    details = usage.prompt_tokens_details
    if details is not None and details.cached_tokens is not None:
        cached = details.cached_tokens
    return TokenUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_tokens=cached,
    )


async def _consume_stream(
    stream: AsyncIterable[ChatCompletionChunk],
) -> tuple[str | None, tuple[ToolCall, ...], TokenUsage, str | None]:
    content_parts: list[str] = []
    tool_accumulator: dict[int, dict[str, str]] = {}
    usage = TokenUsage()
    finish_reason: str | None = None
    async for chunk in stream:
        if chunk.usage is not None:
            usage = _to_token_usage(chunk.usage)
        for choice in chunk.choices:
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta
            if delta.content:
                content_parts.append(delta.content)
            for tool_delta in delta.tool_calls or []:
                slot = tool_accumulator.setdefault(
                    tool_delta.index, {"id": "", "name": "", "arguments": ""}
                )
                if tool_delta.id:
                    slot["id"] = tool_delta.id
                if tool_delta.function is not None:
                    if tool_delta.function.name:
                        slot["name"] = tool_delta.function.name
                    if tool_delta.function.arguments:
                        slot["arguments"] += tool_delta.function.arguments
    tool_calls = tuple(
        ToolCall(
            id=slot["id"],
            name=slot["name"],
            arguments=(
                cast(dict[str, Any], json.loads(slot["arguments"])) if slot["arguments"] else {}
            ),
        )
        for _, slot in sorted(tool_accumulator.items())
    )
    content = "".join(content_parts) if content_parts else None
    return content, tool_calls, usage, finish_reason
