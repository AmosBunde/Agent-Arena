"""Google (Gemini) adapter.

One adapter, two auth modes: the Gemini Developer API (AI Studio, API key) and
Vertex AI (GCP project + location). Translates the normalised message and tool
schema to and from ``google-genai`` types, passes safety settings through, and
retries transient failures with exponential backoff (ADR-0002). Cost is
delegated to the versioned cost model (ADR-0004).
"""

from __future__ import annotations

import asyncio
import json
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
from google import genai
from google.genai import errors, types

_PROVIDER = "google"
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF_SECONDS = 0.5
_RETRYABLE_STATUS = frozenset({429})


@register(_PROVIDER)
class GoogleAdapter:
    """``AgentAdapter`` implementation backed by the google-genai SDK."""

    provider = _PROVIDER

    def __init__(
        self,
        model: str,
        *,
        client: genai.Client | None = None,
        use_vertex: bool = False,
        api_key: str | None = None,
        project: str | None = None,
        location: str | None = None,
        safety_settings: list[types.SafetySetting] | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_backoff_seconds: float = _DEFAULT_BASE_BACKOFF_SECONDS,
        pricing: PricingTable | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._use_vertex = use_vertex
        self._api_key = api_key
        self._project = project
        self._location = location
        self._safety_settings = safety_settings
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
        system_instruction, contents = _to_genai_contents(messages)
        # The SDK's tools field is an invariant union list (ToolListUnion); a
        # concrete list[types.Tool] is not assignable to it, so widen to Any.
        tools_param: Any = _to_genai_tools(tools) if tools else None
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            tools=tools_param,
            safety_settings=self._safety_settings,
        )

        async def call() -> AdapterResponse:
            client = self._resolve_client()
            start = time.monotonic()
            if stream:
                content, tool_calls, usage, finish_reason, metadata = await _consume_stream(
                    await client.aio.models.generate_content_stream(
                        model=self.model, contents=contents, config=config
                    )
                )
            else:
                response = await client.aio.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                content, tool_calls, finish_reason = _parse_candidate(response)
                usage = _to_token_usage(response.usage_metadata)
                metadata = _response_metadata(response)
            latency_ms = int((time.monotonic() - start) * 1000)
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

    def _resolve_client(self) -> genai.Client:
        if self._client is None:
            if self._use_vertex:
                self._client = genai.Client(
                    vertexai=True, project=self._project, location=self._location
                )
            else:
                self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def _with_retry(
        self, factory: Callable[[], Awaitable[AdapterResponse]]
    ) -> AdapterResponse:
        attempt = 0
        while True:
            try:
                return await factory()
            except errors.APIError as exc:
                if not _is_retryable(exc):
                    raise
                attempt += 1
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(self._base_backoff_seconds * (2 ** (attempt - 1)))


def _is_retryable(exc: errors.APIError) -> bool:
    if isinstance(exc, errors.ServerError):
        return True
    return isinstance(exc, errors.ClientError) and exc.code in _RETRYABLE_STATUS


def _to_genai_contents(
    messages: list[Message],
) -> tuple[str | None, list[types.Content]]:
    system_parts: list[str] = []
    contents: list[types.Content] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
        elif message.role == "tool":
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=message.name or "",
                                response=_as_response(message.content),
                            )
                        )
                    ],
                )
            )
        elif message.role == "assistant":
            parts: list[types.Part] = []
            if message.content:
                parts.append(types.Part(text=message.content))
            for call in message.tool_calls:
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(name=call.name, args=call.arguments)
                    )
                )
            contents.append(types.Content(role="model", parts=parts))
        else:
            contents.append(
                types.Content(role="user", parts=[types.Part(text=message.content or "")])
            )
    system_instruction = "\n".join(system_parts) if system_parts else None
    return system_instruction, contents


def _to_genai_tools(tools: list[Tool]) -> list[types.Tool]:
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters_json_schema=tool.parameters,
                )
                for tool in tools
            ]
        )
    ]


def _as_response(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return {"result": content}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _parse_candidate(
    response: types.GenerateContentResponse,
) -> tuple[str | None, tuple[ToolCall, ...], str | None]:
    if not response.candidates:
        return None, (), None
    candidate = response.candidates[0]
    parts = candidate.content.parts if candidate.content else None
    content, tool_calls = _parse_parts(parts)
    finish_reason = candidate.finish_reason.name if candidate.finish_reason is not None else None
    return content, tool_calls, finish_reason


def _parse_parts(
    parts: list[types.Part] | None,
) -> tuple[str | None, tuple[ToolCall, ...]]:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for part in parts or []:
        if part.text:
            text_parts.append(part.text)
        if part.function_call is not None and part.function_call.name:
            tool_calls.append(
                ToolCall(
                    id=part.function_call.id or "",
                    name=part.function_call.name,
                    arguments=dict(part.function_call.args or {}),
                )
            )
    content = "".join(text_parts) if text_parts else None
    return content, tuple(tool_calls)


def _to_token_usage(
    usage: types.GenerateContentResponseUsageMetadata | None,
) -> TokenUsage:
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=usage.prompt_token_count or 0,
        completion_tokens=usage.candidates_token_count or 0,
        cached_tokens=usage.cached_content_token_count or 0,
    )


def _response_metadata(response: types.GenerateContentResponse) -> dict[str, Any]:
    return {
        "model_version": response.model_version,
        "response_id": response.response_id,
    }


async def _consume_stream(
    stream: Any,
) -> tuple[str | None, tuple[ToolCall, ...], TokenUsage, str | None, dict[str, Any]]:
    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    usage = TokenUsage()
    finish_reason: str | None = None
    metadata: dict[str, Any] = {}
    async for chunk in stream:
        if chunk.usage_metadata is not None:
            usage = _to_token_usage(chunk.usage_metadata)
        metadata = _response_metadata(chunk)
        chunk_content, chunk_tool_calls, chunk_finish = _parse_candidate(chunk)
        if chunk_content:
            content_parts.append(chunk_content)
        tool_calls.extend(chunk_tool_calls)
        if chunk_finish:
            finish_reason = chunk_finish
    content = "".join(content_parts) if content_parts else None
    return content, tuple(tool_calls), usage, finish_reason, metadata
