"""Ollama adapter.

Wraps a local Ollama server behind the ``AgentAdapter`` protocol. Unlike the
commercial providers this talks to Ollama's *native* ``/api/chat`` endpoint over
an injectable async ``httpx`` client rather than a vendor SDK, because the
native API reports the token counts (``prompt_eval_count``, ``eval_count``) and
finish reason directly, and exposes tool calling without the lossy translation
of the OpenAI-compatible shim (ADR-0002).

Cost is the one place Ollama departs from the token-priced providers. Local
models have no per-token price; ADR-0004 defines their cost as
``(latency_seconds / 3600) * hourly_rate`` with the hourly rate set per
deployment and defaulting to zero. The cost-model package already implements
that formula behind its ``is_local`` price lines; this adapter wires the
configured ``hourly_rate`` and the measured wall-clock latency into it.

Because the protocol's ``estimate_cost(usage)`` carries no latency, it can only
return the latency-independent token cost, which for a local model is honestly
zero. The authoritative, latency-aware cost is computed inside ``chat`` (where
the latency is known) and surfaced as ``provider_metadata["cost_usd"]``; the
runner persists that. The two paths share the same cost-model formula, so they
cannot diverge. When no price line exists for the model, ``cost_usd`` is omitted
rather than failing the call, so an unpriced local model still runs.

A zero default hourly rate makes local models look free relative to commercial
APIs, which they are not (ADR-0004). Deployments that care about local compute
cost set ``hourly_rate`` to a non-zero amortised figure.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any, cast

import httpx
from agent_arena.adapters.base import (
    AdapterResponse,
    Capability,
    Message,
    TokenUsage,
    Tool,
    ToolCall,
)
from agent_arena.adapters.registry import register
from agent_arena.cost_models import CostModelError, PricingTable, default_pricing

_PROVIDER = "ollama"
_DEFAULT_HOST = "http://localhost:11434"
_CHAT_PATH = "/api/chat"
_DEFAULT_TIMEOUT_SECONDS = 600.0
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECONDS = 0.5


def _is_retryable(exc: BaseException) -> bool:
    """Whether a failed request should be retried.

    Transport-level failures (connect, read, timeout) are transient. HTTP 5xx
    responses are transient server errors; 4xx are caller errors and propagate.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


@register(_PROVIDER)
class OllamaAdapter:
    """``AgentAdapter`` implementation backed by a local Ollama server."""

    provider = _PROVIDER

    def __init__(
        self,
        model: str,
        *,
        client: httpx.AsyncClient | None = None,
        host: str = _DEFAULT_HOST,
        hourly_rate: Decimal = Decimal("0"),
        supports_tools: bool = True,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_backoff_seconds: float = _DEFAULT_BASE_BACKOFF_SECONDS,
        pricing: PricingTable | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._host = host
        self._hourly_rate = hourly_rate
        # Ollama accepts a ``tools`` field for any model, but only tool-trained
        # models actually emit tool calls. The deployment declares support per
        # model so capability negotiation can mark tool-calling tasks
        # ``skipped_unsupported`` rather than silently returning no calls.
        self._supports_tools = supports_tools
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._pricing = pricing
        self._clock = clock or date.today

    def capabilities(self) -> frozenset[Capability]:
        caps = {Capability.CHAT, Capability.STREAMING}
        if self._supports_tools:
            caps.add(Capability.TOOL_CALLING)
        return frozenset(caps)

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        # Latency-independent cost only; for a local model this is zero. The
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
        body = _build_request(self.model, messages, tools, stream=stream, temperature=temperature)

        async def call() -> AdapterResponse:
            client = self._resolve_client()
            start = time.monotonic()
            if stream:
                content, tool_calls, usage, finish_reason, meta = await _consume_stream(
                    client, body
                )
            else:
                response = await client.post(_CHAT_PATH, json=body)
                response.raise_for_status()
                document = cast(dict[str, Any], response.json())
                content, tool_calls, usage, finish_reason, meta = _parse_document(document)
            latency_ms = int((time.monotonic() - start) * 1000)
            self._attach_cost(meta, usage, latency_ms)
            return AdapterResponse(
                provider=self.provider,
                model=self.model,
                content=content,
                usage=usage,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                provider_metadata=meta,
            )

        return await self._with_retry(call)

    def _resolve_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._host, timeout=_DEFAULT_TIMEOUT_SECONDS)
        return self._client

    def _attach_cost(self, meta: dict[str, Any], usage: TokenUsage, latency_ms: int) -> None:
        """Compute the latency-aware local cost and record it on the metadata.

        Always records the configured ``hourly_rate``. Records ``cost_usd`` only
        when a price line exists for the model; an unpriced model still runs,
        it simply reports no cost.
        """
        meta["hourly_rate"] = str(self._hourly_rate)
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
        meta["cost_usd"] = str(cost)

    async def _with_retry(
        self, factory: Callable[[], Awaitable[AdapterResponse]]
    ) -> AdapterResponse:
        attempt = 0
        while True:
            try:
                return await factory()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if not _is_retryable(exc):
                    raise
                attempt += 1
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(self._base_backoff_seconds * (2 ** (attempt - 1)))


def _build_request(
    model: str,
    messages: list[Message],
    tools: list[Tool] | None,
    *,
    stream: bool,
    temperature: float | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": _to_ollama_messages(messages),
        "stream": stream,
    }
    if tools:
        body["tools"] = _to_ollama_tools(tools)
    if temperature is not None:
        body["options"] = {"temperature": temperature}
    return body


def _to_ollama_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant" and message.tool_calls:
            payload: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            payload["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in message.tool_calls
            ]
            out.append(payload)
        elif message.role == "tool":
            # Ollama identifies tool results by name, not by call id.
            tool_message: dict[str, Any] = {"role": "tool", "content": message.content or ""}
            if message.name is not None:
                tool_message["tool_name"] = message.name
            out.append(tool_message)
        else:
            out.append({"role": message.role, "content": message.content or ""})
    return out


def _to_ollama_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


def _parse_tool_calls(message: dict[str, Any]) -> tuple[ToolCall, ...]:
    raw_calls = message.get("tool_calls")
    if not raw_calls:
        return ()
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        function = raw.get("function", {})
        arguments = function.get("arguments", {})
        # Ollama returns arguments as a parsed object, but tolerate a JSON
        # string defensively.
        if isinstance(arguments, str):
            arguments = cast(dict[str, Any], json.loads(arguments)) if arguments else {}
        # Native Ollama tool calls carry no id; synthesise a stable one from the
        # call's position so tool results can be correlated by the caller.
        calls.append(
            ToolCall(
                id=f"call_{index}",
                name=function.get("name", ""),
                arguments=cast(dict[str, Any], arguments),
            )
        )
    return tuple(calls)


def _to_token_usage(document: dict[str, Any]) -> TokenUsage:
    # Ollama exposes no prompt-cache accounting, so cached_tokens stays zero.
    return TokenUsage(
        prompt_tokens=int(document.get("prompt_eval_count") or 0),
        completion_tokens=int(document.get("eval_count") or 0),
    )


def _parse_document(
    document: dict[str, Any],
) -> tuple[str | None, tuple[ToolCall, ...], TokenUsage, str | None, dict[str, Any]]:
    message = cast(dict[str, Any], document.get("message") or {})
    raw_content = message.get("content")
    content = raw_content if raw_content else None
    tool_calls = _parse_tool_calls(message)
    usage = _to_token_usage(document)
    finish_reason = document.get("done_reason")
    meta: dict[str, Any] = {}
    if "total_duration" in document:
        meta["total_duration_ns"] = document["total_duration"]
    if "load_duration" in document:
        meta["load_duration_ns"] = document["load_duration"]
    return content, tool_calls, usage, finish_reason, meta


async def _consume_stream(
    client: httpx.AsyncClient, body: dict[str, Any]
) -> tuple[str | None, tuple[ToolCall, ...], TokenUsage, str | None, dict[str, Any]]:
    """Consume Ollama's newline-delimited JSON stream into a single response.

    Each line is a partial message; content fragments accumulate and the final
    line (``done: true``) carries the token counts, finish reason, and timing.
    """
    content_parts: list[str] = []
    tool_calls: tuple[ToolCall, ...] = ()
    usage = TokenUsage()
    finish_reason: str | None = None
    meta: dict[str, Any] = {}
    async with client.stream("POST", _CHAT_PATH, json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            chunk = cast(dict[str, Any], json.loads(line))
            message = cast(dict[str, Any], chunk.get("message") or {})
            fragment = message.get("content")
            if fragment:
                content_parts.append(fragment)
            chunk_calls = _parse_tool_calls(message)
            if chunk_calls:
                tool_calls = chunk_calls
            if chunk.get("done"):
                usage = _to_token_usage(chunk)
                finish_reason = chunk.get("done_reason")
                if "total_duration" in chunk:
                    meta["total_duration_ns"] = chunk["total_duration"]
                if "load_duration" in chunk:
                    meta["load_duration_ns"] = chunk["load_duration"]
    content = "".join(content_parts) if content_parts else None
    return content, tool_calls, usage, finish_reason, meta
