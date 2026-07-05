"""AWS Bedrock adapter.

Wraps the Bedrock Runtime Converse API behind the ``AgentAdapter`` protocol.
Converse is used deliberately: it is Bedrock's own normalisation layer over
the per-model request shapes (Claude, Mistral, Llama, and the rest), so the
per-model dispatch the platform would otherwise need lives server-side and
this adapter stays model agnostic (ADR-0002). Token usage comes from the
Converse ``usage`` block and cost is delegated to the versioned cost model
under the ``bedrock`` provider (ADR-0004).

boto3 is synchronous, so calls run in a worker thread to satisfy the async
protocol without blocking the event loop.
"""

from __future__ import annotations

import asyncio
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
    ToolCall,
)
from agent_arena.adapters.registry import register
from agent_arena.cost_models import PricingTable, default_pricing

_PROVIDER = "bedrock"
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECONDS = 0.5

# Transient Converse error codes worth retrying; access and validation
# errors are absent so they propagate immediately.
_RETRYABLE_CODES = (
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "InternalServerException",
    "ModelNotReadyException",
)


@register(_PROVIDER)
class BedrockAdapter:
    """``AgentAdapter`` implementation backed by the Bedrock Converse API."""

    provider = _PROVIDER

    def __init__(
        self,
        model: str,
        *,
        client: Any | None = None,
        region_name: str | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_backoff_seconds: float = _DEFAULT_BASE_BACKOFF_SECONDS,
        pricing: PricingTable | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._region_name = region_name
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._pricing = pricing
        self._clock = clock or date.today

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT, Capability.TOOL_CALLING})

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
        request = _to_converse_request(self.model, messages, tools, temperature)

        async def call() -> AdapterResponse:
            client = self._resolve_client()
            start = time.monotonic()
            response = await asyncio.to_thread(client.converse, **request)
            latency_ms = int((time.monotonic() - start) * 1000)
            content, tool_calls = _parse_output(response)
            return AdapterResponse(
                provider=self.provider,
                model=self.model,
                content=content,
                usage=_to_token_usage(response.get("usage", {})),
                latency_ms=latency_ms,
                finish_reason=response.get("stopReason"),
                tool_calls=tool_calls,
                provider_metadata={
                    "request_id": response.get("ResponseMetadata", {}).get("RequestId"),
                },
            )

        return await self._with_retry(call)

    def _resolve_client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=self._region_name)
        return self._client

    async def _with_retry(
        self, factory: Callable[[], Awaitable[AdapterResponse]]
    ) -> AdapterResponse:
        from botocore.exceptions import ClientError

        attempt = 0
        while True:
            try:
                return await factory()
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in _RETRYABLE_CODES:
                    raise
                attempt += 1
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(self._base_backoff_seconds * (2 ** (attempt - 1)))


def _to_converse_request(
    model: str,
    messages: list[Message],
    tools: list[Tool] | None,
    temperature: float | None,
) -> dict[str, Any]:
    system: list[dict[str, Any]] = []
    converse_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            system.append({"text": message.content or ""})
        elif message.role == "assistant":
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"text": message.content})
            for call in message.tool_calls:
                content.append(
                    {"toolUse": {"toolUseId": call.id, "name": call.name, "input": call.arguments}}
                )
            converse_messages.append({"role": "assistant", "content": content})
        elif message.role == "tool":
            converse_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": message.tool_call_id,
                                "content": [{"text": message.content or ""}],
                            }
                        }
                    ],
                }
            )
        else:
            converse_messages.append({"role": "user", "content": [{"text": message.content or ""}]})

    request: dict[str, Any] = {"modelId": model, "messages": converse_messages}
    if system:
        request["system"] = system
    if temperature is not None:
        request["inferenceConfig"] = {"temperature": temperature}
    if tools:
        request["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": {"json": tool.parameters},
                    }
                }
                for tool in tools
            ]
        }
    return request


def _parse_output(response: dict[str, Any]) -> tuple[str | None, tuple[ToolCall, ...]]:
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in blocks:
        if "text" in block:
            text_parts.append(block["text"])
        elif "toolUse" in block:
            tool_use = block["toolUse"]
            tool_calls.append(
                ToolCall(
                    id=tool_use.get("toolUseId", ""),
                    name=tool_use.get("name", ""),
                    arguments=dict(tool_use.get("input", {})),
                )
            )
    content = "".join(text_parts) if text_parts else None
    return content, tuple(tool_calls)


def _to_token_usage(usage: dict[str, Any]) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=int(usage.get("inputTokens", 0)),
        completion_tokens=int(usage.get("outputTokens", 0)),
        cached_tokens=int(usage.get("cacheReadInputTokens", 0) or 0),
    )
