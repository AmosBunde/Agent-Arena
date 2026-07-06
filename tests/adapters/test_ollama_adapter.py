"""Tests for the Ollama adapter.

Unit tests run offline against a real ``httpx`` client wired to a
``MockTransport``, so request shaping, status handling, JSON parsing, and
NDJSON streaming are exercised through genuine httpx machinery rather than a
hand-rolled fake. A live test is gated on ``OLLAMA_HOST`` and marked
integration; CI sets that variable against a real Ollama service.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from decimal import Decimal

import httpx
import pytest
from agent_arena.adapters import AgentAdapter, Capability, Message, TokenUsage, Tool, ToolCall
from agent_arena.adapters.ollama_adapter import OllamaAdapter
from agent_arena.adapters.registry import default_registry
from agent_arena.cost_models import UnknownModelError

_MODEL = "llama3.1:8b"


class _Handler:
    """A MockTransport handler that replays a queue of responders.

    Each responder is an ``httpx`` exception instance (raised), or a callable
    taking the request and returning an ``httpx.Response``. The last responder
    repeats once the queue is exhausted.
    """

    def __init__(self, responders: list[object]) -> None:
        self._responders = responders
        self.requests: list[httpx.Request] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def last_body(self) -> dict[str, object]:
        return json.loads(self.requests[-1].content)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responder = self._responders[min(len(self.requests) - 1, len(self._responders) - 1)]
        if isinstance(responder, BaseException):
            raise responder
        assert callable(responder)
        return responder(request)


def _json(payload: dict[str, object], status: int = 200):
    return lambda _request: httpx.Response(status, json=payload)


def _ndjson(chunks: list[dict[str, object]]):
    content = "".join(json.dumps(chunk) + "\n" for chunk in chunks)
    return lambda _request: httpx.Response(200, content=content)


def _message(content: str, *, prompt: int = 1, completion: int = 1, **extra: object):
    payload: dict[str, object] = {
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": prompt,
        "eval_count": completion,
    }
    payload.update(extra)
    return payload


def _adapter(responders: list[object], **kwargs: object) -> tuple[OllamaAdapter, _Handler]:
    handler = _Handler(responders)
    client = httpx.AsyncClient(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    adapter = OllamaAdapter(_MODEL, client=client, base_backoff_seconds=0, **kwargs)
    return adapter, handler


def test_capabilities_include_tool_calling_when_supported() -> None:
    adapter, _ = _adapter([])
    caps = adapter.capabilities()
    assert {Capability.CHAT, Capability.STREAMING, Capability.TOOL_CALLING} == caps


def test_capabilities_drop_tool_calling_when_unsupported() -> None:
    adapter, _ = _adapter([], supports_tools=False)
    caps = adapter.capabilities()
    assert Capability.TOOL_CALLING not in caps
    assert {Capability.CHAT, Capability.STREAMING} == caps


def test_chat_normalises_response_and_token_usage() -> None:
    adapter, _ = _adapter([_json(_message("hi", prompt=100, completion=20))])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "hi"
    assert response.usage == TokenUsage(prompt_tokens=100, completion_tokens=20)
    assert response.finish_reason == "stop"
    assert response.provider == "ollama"
    assert response.model == _MODEL


def test_chat_empty_content_is_none() -> None:
    adapter, _ = _adapter([_json(_message(""))])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content is None


def test_chat_parses_tool_calls() -> None:
    payload = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "search", "arguments": {"q": "x"}}}],
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 5,
        "eval_count": 5,
    }
    adapter, _ = _adapter([_json(payload)])
    response = asyncio.run(adapter.chat([Message(role="user", content="find")]))
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "call_0"
    assert call.name == "search"
    assert call.arguments == {"q": "x"}


def test_request_shapes_messages_tools_and_temperature() -> None:
    adapter, handler = _adapter([_json(_message("ok"))])
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    tools = [Tool(name="search", description="find", parameters=schema)]
    asyncio.run(
        adapter.chat(
            [
                Message(role="system", content="Be terse."),
                Message(role="user", content="hi"),
            ],
            tools=tools,
            temperature=0.2,
        )
    )
    body = handler.last_body()
    assert body["model"] == _MODEL
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "hi"},
    ]
    assert body["tools"] == [
        {
            "type": "function",
            "function": {"name": "search", "description": "find", "parameters": schema},
        }
    ]
    assert body["options"] == {"temperature": 0.2}


def test_request_omits_optional_fields_when_absent() -> None:
    adapter, handler = _adapter([_json(_message("ok"))])
    asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    body = handler.last_body()
    assert "tools" not in body
    assert "options" not in body


def test_request_shapes_assistant_tool_calls_and_tool_results() -> None:
    adapter, handler = _adapter([_json(_message("ok"))])
    history = [
        Message(role="user", content="find x"),
        Message(
            role="assistant",
            # ToolCall id is dropped on the wire; Ollama keys on name.
            tool_calls=(ToolCall(id="call_0", name="search", arguments={"q": "x"}),),
        ),
        Message(role="tool", content="result", tool_call_id="call_0", name="search"),
    ]
    asyncio.run(adapter.chat(history))
    messages = handler.last_body()["messages"]
    assert messages[1] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "search", "arguments": {"q": "x"}}}],
    }
    assert messages[2] == {"role": "tool", "content": "result", "tool_name": "search"}


def test_streaming_accumulates_content_and_final_usage() -> None:
    chunks: list[dict[str, object]] = [
        {"message": {"role": "assistant", "content": "hel"}, "done": False},
        {"message": {"role": "assistant", "content": "lo"}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 7,
            "eval_count": 3,
            "total_duration": 123456,
        },
    ]
    adapter, handler = _adapter([_ndjson(chunks)])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")], stream=True))
    assert response.content == "hello"
    assert response.usage == TokenUsage(prompt_tokens=7, completion_tokens=3)
    assert response.finish_reason == "stop"
    assert response.provider_metadata["total_duration_ns"] == 123456
    assert handler.last_body()["stream"] is True


def test_streaming_parses_tool_calls() -> None:
    chunks: list[dict[str, object]] = [
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "search", "arguments": {"q": "y"}}}],
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 4,
            "eval_count": 1,
        },
    ]
    adapter, _ = _adapter([_ndjson(chunks)])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")], stream=True))
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"q": "y"}


def test_retries_server_error_then_succeeds() -> None:
    adapter, handler = _adapter([_json({"error": "overloaded"}, status=503), _json(_message("ok"))])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "ok"
    assert handler.calls == 2


def test_retries_transport_error_then_succeeds() -> None:
    adapter, handler = _adapter([httpx.ConnectError("boom"), _json(_message("ok"))])
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "ok"
    assert handler.calls == 2


def test_client_error_propagates_without_retry() -> None:
    adapter, handler = _adapter([_json({"error": "bad request"}, status=400)])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert handler.calls == 1


def test_retries_exhaust_and_raise() -> None:
    adapter, handler = _adapter([_json({"error": "overloaded"}, status=503)], max_retries=3)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert handler.calls == 3


def test_estimate_cost_is_zero_for_local_without_latency() -> None:
    adapter, _ = _adapter([], hourly_rate=Decimal("5"), clock=lambda: date(2025, 1, 1))
    assert adapter.estimate_cost(TokenUsage(prompt_tokens=1000, completion_tokens=1000)) == Decimal(
        "0"
    )


def test_estimate_cost_unknown_model_raises() -> None:
    adapter = OllamaAdapter("mystery:1b", clock=lambda: date(2025, 1, 1))
    with pytest.raises(UnknownModelError):
        adapter.estimate_cost(TokenUsage(prompt_tokens=1, completion_tokens=1))


def test_cost_usd_follows_latency_and_hourly_rate() -> None:
    rate = Decimal("3600")  # one dollar per second, to make the arithmetic legible
    adapter, _ = _adapter([_json(_message("ok"))], hourly_rate=rate, clock=lambda: date(2025, 1, 1))
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.provider_metadata["hourly_rate"] == "3600"
    # Recompute the cost-model formula from the measured latency the adapter
    # reported, so the assertion is exact regardless of wall-clock timing.
    seconds = Decimal(response.latency_ms) / Decimal(1000)
    expected = (seconds / Decimal(3600)) * rate
    assert Decimal(response.provider_metadata["cost_usd"]) == expected


def test_cost_usd_is_zero_with_default_rate() -> None:
    adapter, _ = _adapter([_json(_message("ok"))], clock=lambda: date(2025, 1, 1))
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert Decimal(response.provider_metadata["cost_usd"]) == Decimal("0")
    assert response.provider_metadata["hourly_rate"] == "0"


def test_cost_usd_omitted_for_unpriced_model() -> None:
    handler = _Handler([_json(_message("ok"))])
    client = httpx.AsyncClient(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    adapter = OllamaAdapter(
        "mystery:1b", client=client, hourly_rate=Decimal("5"), clock=lambda: date(2025, 1, 1)
    )
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert "cost_usd" not in response.provider_metadata
    assert response.provider_metadata["hourly_rate"] == "5"


def test_registered_in_default_registry() -> None:
    adapter = default_registry().get_adapter("ollama", _MODEL)
    assert isinstance(adapter, AgentAdapter)
    assert adapter.provider == "ollama"


@pytest.mark.integration
def test_live_ollama_call() -> None:
    host = os.environ.get("OLLAMA_HOST")
    if not host:
        pytest.skip("OLLAMA_HOST not set")
    model = os.environ.get("OLLAMA_MODEL", _MODEL)
    adapter = OllamaAdapter(model, host=host)
    response = asyncio.run(
        adapter.chat([Message(role="user", content="Reply with the single word: pong")])
    )
    assert response.content
    assert response.usage.prompt_tokens > 0
    assert response.latency_ms >= 0
