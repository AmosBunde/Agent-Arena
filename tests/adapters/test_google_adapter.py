"""Tests for the Google (Gemini) adapter.

Unit tests run offline against a fake injected client; a live test is gated on
a Gemini API key and marked integration.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agent_arena.adapters import AgentAdapter, Capability, Message, TokenUsage, Tool
from agent_arena.adapters.google_adapter import GoogleAdapter
from agent_arena.adapters.registry import default_registry
from google.genai import errors

# --- fakes -----------------------------------------------------------------


def _part(text=None, function_call=None):
    return SimpleNamespace(text=text, function_call=function_call)


def _fc(name, args, id=None):
    return SimpleNamespace(id=id, name=name, args=args)


def _usage(prompt, completion, cached=0):
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=completion,
        cached_content_token_count=cached,
    )


def _response(parts, usage, finish="STOP"):
    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=parts),
        finish_reason=SimpleNamespace(name=finish) if finish else None,
    )
    return SimpleNamespace(
        candidates=[candidate],
        usage_metadata=usage,
        model_version="gemini-test",
        response_id="resp-1",
    )


class _Models:
    def __init__(self, results=None, stream_chunks=None) -> None:
        self._results = list(results or [])
        self._stream_chunks = stream_chunks or []
        self.calls = 0
        self.last_config = None

    async def generate_content(self, *, model, contents, config):
        self.last_config = config
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result

    async def generate_content_stream(self, *, model, contents, config):
        self.last_config = config
        self.calls += 1
        chunks = self._stream_chunks

        async def gen():
            for chunk in chunks:
                yield chunk

        return gen()


def _client(models: _Models):
    return SimpleNamespace(aio=SimpleNamespace(models=models))


def _adapter(models: _Models, **kwargs) -> GoogleAdapter:
    return GoogleAdapter(
        "gemini-2.0-flash", client=_client(models), base_backoff_seconds=0, **kwargs
    )


# --- tests -----------------------------------------------------------------


def test_capabilities() -> None:
    assert _adapter(_Models()).capabilities() == frozenset(
        {Capability.CHAT, Capability.TOOL_CALLING, Capability.STREAMING}
    )


def test_chat_normalises_response_and_usage() -> None:
    models = _Models([_response([_part(text="hi there")], _usage(40, 8, cached=5))])
    adapter = _adapter(models)
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "hi there"
    assert response.usage == TokenUsage(prompt_tokens=40, completion_tokens=8, cached_tokens=5)
    assert response.finish_reason == "STOP"
    assert response.provider_metadata["model_version"] == "gemini-test"


def test_chat_parses_function_calls() -> None:
    part = _part(function_call=_fc("search", {"q": "rain"}, id="fc-1"))
    models = _Models([_response([part], _usage(5, 5), finish="STOP")])
    adapter = _adapter(models)
    response = asyncio.run(adapter.chat([Message(role="user", content="weather?")]))
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"q": "rain"}


def test_tool_schema_translated_to_function_declarations() -> None:
    models = _Models([_response([_part(text="ok")], _usage(1, 1))])
    adapter = _adapter(models)
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    tools = [Tool(name="search", description="find things", parameters=schema)]
    asyncio.run(adapter.chat([Message(role="user", content="hi")], tools=tools))
    declarations = models.last_config.tools[0].function_declarations
    assert declarations[0].name == "search"
    assert declarations[0].parameters_json_schema == schema


def test_system_message_becomes_system_instruction() -> None:
    models = _Models([_response([_part(text="ok")], _usage(1, 1))])
    adapter = _adapter(models)
    asyncio.run(
        adapter.chat(
            [
                Message(role="system", content="Be terse."),
                Message(role="user", content="hi"),
            ]
        )
    )
    assert models.last_config.system_instruction == "Be terse."


def test_streaming_accumulates() -> None:
    chunks = [
        _response([_part(text="Hel")], None, finish=None),
        _response([_part(text="lo")], _usage(6, 2), finish="STOP"),
    ]
    adapter = _adapter(_Models(stream_chunks=chunks))
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")], stream=True))
    assert response.content == "Hello"
    assert response.usage == TokenUsage(prompt_tokens=6, completion_tokens=2)
    assert response.finish_reason == "STOP"


def test_retries_server_error_then_succeeds() -> None:
    err = errors.ServerError(503, {"error": {"message": "unavailable"}})
    models = _Models([err, _response([_part(text="ok")], _usage(1, 1))])
    adapter = _adapter(models)
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "ok"
    assert models.calls == 2


def test_rate_limit_is_retryable() -> None:
    err = errors.ClientError(429, {"error": {"message": "rate limited"}})
    models = _Models([err, _response([_part(text="ok")], _usage(1, 1))])
    response = asyncio.run(_adapter(models).chat([Message(role="user", content="hi")]))
    assert response.content == "ok"


def test_non_retryable_client_error_propagates() -> None:
    err = errors.ClientError(400, {"error": {"message": "bad request"}})
    models = _Models([err])
    with pytest.raises(errors.ClientError):
        asyncio.run(_adapter(models).chat([Message(role="user", content="hi")]))
    assert models.calls == 1


def test_both_auth_modes_build_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def fake_client(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(aio=SimpleNamespace(models=_Models()))

    monkeypatch.setattr("agent_arena.adapters.google_adapter.genai.Client", fake_client)

    GoogleAdapter("gemini-2.0-flash", api_key="k")._resolve_client()
    GoogleAdapter(
        "gemini-2.5-pro", use_vertex=True, project="p", location="us-central1"
    )._resolve_client()

    assert captured[0] == {"api_key": "k"}
    assert captured[1] == {"vertexai": True, "project": "p", "location": "us-central1"}


def test_estimate_cost_uses_google_pricing() -> None:
    adapter = GoogleAdapter("gemini-2.0-flash", clock=lambda: date(2025, 3, 1))
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000)
    # 1000*0.10 + 1000*0.40 per million = 0.0005
    assert adapter.estimate_cost(usage) == Decimal("0.0005")


def test_registered_in_default_registry() -> None:
    adapter = default_registry().get_adapter("google", "gemini-2.0-flash")
    assert isinstance(adapter, AgentAdapter)
    assert adapter.provider == "google"


@pytest.mark.integration
def test_live_google_call() -> None:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        pytest.skip("GEMINI_API_KEY/GOOGLE_API_KEY not set")
    adapter = GoogleAdapter("gemini-2.0-flash")
    response = asyncio.run(
        adapter.chat([Message(role="user", content="Reply with the single word: pong")])
    )
    assert response.content
    assert response.usage.prompt_tokens > 0
