"""Tests for the OpenAI adapter.

Unit tests run fully offline against a fake injected client; a live test is
gated on OPENAI_API_KEY and marked integration.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from decimal import Decimal

import httpx
import pytest
from agent_arena.adapters import AgentAdapter, Capability, Message, TokenUsage, Tool
from agent_arena.adapters.openai_adapter import OpenAIAdapter
from agent_arena.adapters.registry import default_registry
from openai import APITimeoutError

# --- fakes -----------------------------------------------------------------


class _Fn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.type = "function"
        self.function = _Fn(name, arguments)


class _Msg:
    def __init__(self, content=None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message, finish_reason="stop") -> None:
        self.message = message
        self.finish_reason = finish_reason


class _Details:
    def __init__(self, cached) -> None:
        self.cached_tokens = cached


class _Usage:
    def __init__(self, prompt, completion, cached=0) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = _Details(cached)


class _Completion:
    def __init__(self, choices, usage, id="cmpl-1", system_fingerprint="fp-1") -> None:
        self.choices = choices
        self.usage = usage
        self.id = id
        self.system_fingerprint = system_fingerprint


class _Stream:
    def __init__(self, chunks) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


class _Completions:
    def __init__(self, results) -> None:
        self._results = list(results)
        self.calls = 0

    async def create(self, **kwargs):
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


class _Client:
    def __init__(self, results) -> None:
        self.chat = type("_Chat", (), {"completions": _Completions(results)})()


def _adapter(results, **kwargs) -> OpenAIAdapter:
    return OpenAIAdapter("gpt-4o-mini", client=_Client(results), base_backoff_seconds=0, **kwargs)


# --- tests -----------------------------------------------------------------


def test_capabilities() -> None:
    adapter = _adapter([])
    assert adapter.capabilities() == frozenset(
        {Capability.CHAT, Capability.TOOL_CALLING, Capability.STREAMING}
    )


def test_chat_normalises_response_and_usage() -> None:
    completion = _Completion(
        choices=[_Choice(_Msg(content="hello"))],
        usage=_Usage(prompt=100, completion=20, cached=10),
    )
    adapter = _adapter([completion])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "hello"
    assert response.provider == "openai"
    assert response.usage == TokenUsage(prompt_tokens=100, completion_tokens=20, cached_tokens=10)
    assert response.finish_reason == "stop"
    assert response.provider_metadata["id"] == "cmpl-1"


def test_chat_parses_tool_calls() -> None:
    message = _Msg(
        content=None,
        tool_calls=[_ToolCall("call-1", "search", json.dumps({"q": "weather"}))],
    )
    completion = _Completion([_Choice(message, finish_reason="tool_calls")], _Usage(5, 5))
    adapter = _adapter([completion])
    tools = [Tool(name="search", description="d", parameters={"type": "object"})]
    response = asyncio.run(adapter.chat([Message(role="user", content="weather?")], tools=tools))
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"q": "weather"}


def test_streaming_accumulates_content_and_usage() -> None:
    def chunk(content=None, usage=None, finish=None):
        delta = type("_Delta", (), {"content": content, "tool_calls": None})()
        choices = [type("_C", (), {"delta": delta, "finish_reason": finish})()]
        return type("_Chunk", (), {"choices": choices, "usage": usage})()

    chunks = [
        chunk(content="Hel"),
        chunk(content="lo"),
        chunk(finish="stop"),
        type("_Chunk", (), {"choices": [], "usage": _Usage(7, 3)})(),
    ]
    adapter = _adapter([_Stream(chunks)])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")], stream=True))
    assert response.content == "Hello"
    assert response.usage == TokenUsage(prompt_tokens=7, completion_tokens=3)
    assert response.finish_reason == "stop"


def test_retries_transient_error_then_succeeds() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    completion = _Completion([_Choice(_Msg(content="ok"))], _Usage(1, 1))
    adapter = _adapter(
        [APITimeoutError(request=request), APITimeoutError(request=request), completion]
    )
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "ok"
    assert adapter._client.chat.completions.calls == 3  # type: ignore[union-attr]


def test_gives_up_after_max_retries() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    adapter = _adapter([APITimeoutError(request=request)] * 5, max_retries=3)
    with pytest.raises(APITimeoutError):
        asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert adapter._client.chat.completions.calls == 3  # type: ignore[union-attr]


def test_non_retryable_error_propagates_immediately() -> None:
    # A non-retryable error (not in _RETRYABLE_ERRORS) must not be retried.
    adapter = _adapter([ValueError("bad request")])
    with pytest.raises(ValueError):
        asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert adapter._client.chat.completions.calls == 1  # type: ignore[union-attr]


def test_estimate_cost_uses_pricing_at_clock_date() -> None:
    adapter = OpenAIAdapter("gpt-4o", clock=lambda: date(2024, 9, 1))
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, cached_tokens=200)
    # Post-repricing gpt-4o: 800*2.50 + 200*1.25 + 500*10.00 per million = 0.00725
    assert adapter.estimate_cost(usage) == Decimal("0.00725")


def test_registered_in_default_registry() -> None:
    adapter = default_registry().get_adapter("openai", "gpt-4o-mini")
    assert isinstance(adapter, AgentAdapter)
    assert adapter.provider == "openai"


@pytest.mark.integration
def test_live_openai_call() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    adapter = OpenAIAdapter("gpt-4o-mini")
    response = asyncio.run(
        adapter.chat([Message(role="user", content="Reply with the single word: pong")])
    )
    assert response.content
    assert response.usage.prompt_tokens > 0
