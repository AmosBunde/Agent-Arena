"""Tests for the Anthropic adapter.

Unit tests run offline against a fake injected client; a live test is gated on
ANTHROPIC_API_KEY and marked integration.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from agent_arena.adapters import AgentAdapter, Capability, Message, TokenUsage, Tool
from agent_arena.adapters.anthropic_adapter import AnthropicAdapter
from agent_arena.adapters.registry import default_registry
from anthropic import APITimeoutError
from anthropic.types import TextBlock, ToolUseBlock, Usage


def _message(content, usage, stop_reason="end_turn"):
    return SimpleNamespace(
        content=content,
        usage=usage,
        stop_reason=stop_reason,
        id="msg_1",
        model="claude-sonnet-4-6",
    )


def _usage(input_tokens, output_tokens, cache_read=0, cache_creation=0):
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )


class _Messages:
    def __init__(self, results) -> None:
        self._results = list(results)
        self.calls = 0
        self.last_kwargs: dict = {}

    def _next(self):
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._next()

    def stream(self, **kwargs):
        self.last_kwargs = kwargs
        return _StreamCtx(self)


class _StreamCtx:
    def __init__(self, messages: _Messages) -> None:
        self._messages = messages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self._messages._next()


def _client(messages: _Messages):
    return SimpleNamespace(messages=messages)


def _adapter(results, **kwargs) -> AnthropicAdapter:
    messages = _Messages(results)
    adapter = AnthropicAdapter(
        "claude-sonnet-4-6", client=_client(messages), base_backoff_seconds=0, **kwargs
    )
    return adapter


def test_capabilities_include_prompt_caching() -> None:
    caps = _adapter([]).capabilities()
    assert Capability.PROMPT_CACHING in caps
    assert {Capability.CHAT, Capability.TOOL_CALLING, Capability.STREAMING} <= caps


def test_chat_normalises_response_and_cached_tokens() -> None:
    message = _message(
        [TextBlock(text="hi", type="text")],
        _usage(100, 20, cache_read=10, cache_creation=5),
    )
    adapter = _adapter([message])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "hi"
    # prompt_tokens folds fresh input + cache read + cache creation; cached is the read.
    assert response.usage == TokenUsage(prompt_tokens=115, completion_tokens=20, cached_tokens=10)
    assert response.finish_reason == "end_turn"


def test_chat_parses_tool_use_blocks() -> None:
    block = ToolUseBlock(id="t1", name="search", input={"q": "x"}, type="tool_use")
    adapter = _adapter([_message([block], _usage(5, 5))])
    response = asyncio.run(adapter.chat([Message(role="user", content="find")]))
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"q": "x"}


def test_system_message_becomes_system_param() -> None:
    adapter = _adapter([_message([TextBlock(text="ok", type="text")], _usage(1, 1))])
    asyncio.run(
        adapter.chat(
            [
                Message(role="system", content="Be terse."),
                Message(role="user", content="hi"),
            ]
        )
    )
    assert adapter._client.messages.last_kwargs["system"] == "Be terse."  # type: ignore[union-attr]


def test_tool_schema_translation() -> None:
    adapter = _adapter([_message([TextBlock(text="ok", type="text")], _usage(1, 1))])
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    tools = [Tool(name="search", description="find", parameters=schema)]
    asyncio.run(adapter.chat([Message(role="user", content="hi")], tools=tools))
    sent = adapter._client.messages.last_kwargs["tools"]  # type: ignore[union-attr]
    assert sent == [{"name": "search", "description": "find", "input_schema": schema}]


def test_streaming_returns_final_message() -> None:
    message = _message([TextBlock(text="streamed", type="text")], _usage(3, 4))
    adapter = _adapter([message])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")], stream=True))
    assert response.content == "streamed"
    assert response.usage == TokenUsage(prompt_tokens=3, completion_tokens=4)


def test_retries_transient_then_succeeds() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    message = _message([TextBlock(text="ok", type="text")], _usage(1, 1))
    adapter = _adapter([APITimeoutError(request=request), message])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "ok"
    assert adapter._client.messages.calls == 2  # type: ignore[union-attr]


def test_non_retryable_propagates() -> None:
    adapter = _adapter([ValueError("bad")])
    with pytest.raises(ValueError):
        asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert adapter._client.messages.calls == 1  # type: ignore[union-attr]


def test_estimate_cost_uses_anthropic_pricing() -> None:
    adapter = AnthropicAdapter("claude-sonnet-4-6", clock=lambda: date(2026, 3, 1))
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000)
    # sonnet: 1000*3.00 + 1000*15.00 per million = 0.018
    assert adapter.estimate_cost(usage) == Decimal("0.018")


def test_registered_in_default_registry() -> None:
    adapter = default_registry().get_adapter("anthropic", "claude-sonnet-4-6")
    assert isinstance(adapter, AgentAdapter)
    assert adapter.provider == "anthropic"


@pytest.mark.integration
def test_live_anthropic_call() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    adapter = AnthropicAdapter("claude-sonnet-4-6")
    response = asyncio.run(
        adapter.chat([Message(role="user", content="Reply with the single word: pong")])
    )
    assert response.content
    assert response.usage.prompt_tokens > 0
