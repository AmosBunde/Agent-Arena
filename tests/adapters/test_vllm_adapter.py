"""vLLM adapter tests (issue #22).

The adapter is exercised through the real OpenAI SDK against an in-process
mock transport speaking the OpenAI-compatible wire format vLLM serves, so
the full HTTP layer is covered without a GPU. A live test gated on
VLLM_LIVE_TEST covers a real server.
"""

from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal

import httpx
import pytest
from agent_arena.adapters import AgentAdapter, Capability, Message, TokenUsage, Tool
from agent_arena.adapters.registry import default_registry
from agent_arena.adapters.vllm_adapter import VLLMAdapter
from openai import AsyncOpenAI, InternalServerError

MODEL = "meta-llama/Llama-3.1-8B-Instruct"


def _completion_payload(
    content: str | None = "pong",
    tool_calls: list[dict] | None = None,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    message: dict = {"role": "assistant", "content": content}  # type: ignore[type-arg]
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


def _adapter_with_server(
    responses: list[httpx.Response], **kwargs: object
) -> tuple[VLLMAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    # SDK-internal retries are disabled so the adapter owns the retry policy.
    client = AsyncOpenAI(
        base_url="http://vllm.test/v1",
        api_key="EMPTY",
        http_client=http_client,
        max_retries=0,
    )
    adapter = VLLMAdapter(MODEL, client=client, base_backoff_seconds=0, **kwargs)  # type: ignore[arg-type]
    return adapter, requests


def test_registered_and_satisfies_protocol() -> None:
    assert default_registry().is_registered("vllm")
    adapter, _ = _adapter_with_server([])
    assert isinstance(adapter, AgentAdapter)
    assert adapter.capabilities() == frozenset({Capability.CHAT, Capability.TOOL_CALLING})


def test_chat_over_openai_compatible_wire() -> None:
    adapter, requests = _adapter_with_server([httpx.Response(200, json=_completion_payload())])
    response = asyncio.run(
        adapter.chat(
            [Message(role="system", content="be terse"), Message(role="user", content="ping")],
            temperature=0.1,
        )
    )
    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    payload = json.loads(request.content)
    assert payload["model"] == MODEL
    assert payload["messages"][0] == {"role": "system", "content": "be terse"}
    assert payload["temperature"] == 0.1
    assert response.content == "pong"
    assert response.usage.prompt_tokens == 5
    assert response.usage.completion_tokens == 2


def test_latency_based_cost_in_provider_metadata() -> None:
    adapter, _ = _adapter_with_server(
        [httpx.Response(200, json=_completion_payload())],
        hourly_rate=Decimal("3.60"),
    )
    response = asyncio.run(adapter.chat([Message(role="user", content="ping")]))
    assert response.provider_metadata["hourly_rate"] == "3.60"
    cost = Decimal(response.provider_metadata["cost_usd"])
    # (latency_seconds / 3600) * hourly_rate, with hourly_rate 3.60:
    # cost equals latency in milliseconds divided by one million.
    assert cost == Decimal(response.latency_ms) / Decimal("1000000")


def test_unpriced_model_still_runs_without_cost() -> None:
    adapter, _ = _adapter_with_server([httpx.Response(200, json=_completion_payload())])
    unpriced = VLLMAdapter(
        "some/unknown-model",
        client=adapter._client,  # noqa: SLF001 - reuse the mock transport
        hourly_rate=Decimal("3.60"),
    )
    response = asyncio.run(unpriced.chat([Message(role="user", content="ping")]))
    assert "cost_usd" not in response.provider_metadata
    assert response.provider_metadata["hourly_rate"] == "3.60"


def test_estimate_cost_is_latency_independent_zero() -> None:
    adapter, _ = _adapter_with_server([])
    usage_cost = adapter.estimate_cost(TokenUsage(prompt_tokens=1000, completion_tokens=1000))
    assert usage_cost == Decimal("0")


def test_tool_calls_parse() -> None:
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression": "6 * 7"}'},
        }
    ]
    adapter, requests = _adapter_with_server(
        [httpx.Response(200, json=_completion_payload(content=None, tool_calls=tool_calls))]
    )
    tool = Tool(name="calculator", description="maths", parameters={"type": "object"})
    response = asyncio.run(adapter.chat([Message(role="user", content="compute")], tools=[tool]))
    assert response.tool_calls[0].name == "calculator"
    assert response.tool_calls[0].arguments == {"expression": "6 * 7"}
    payload = json.loads(requests[0].content)
    assert payload["tools"][0]["function"]["name"] == "calculator"


def test_retries_transient_errors() -> None:
    adapter, requests = _adapter_with_server(
        [
            httpx.Response(500, json={"error": "boom"}),
            httpx.Response(500, json={"error": "boom"}),
            httpx.Response(200, json=_completion_payload()),
        ]
    )
    response = asyncio.run(adapter.chat([Message(role="user", content="ping")]))
    assert response.content == "pong"
    assert len(requests) == 3


def test_retry_budget_exhausted_raises() -> None:
    adapter, _ = _adapter_with_server([httpx.Response(500, json={"error": "boom"})] * 3)
    with pytest.raises(InternalServerError):
        asyncio.run(adapter.chat([Message(role="user", content="ping")]))


@pytest.mark.integration
def test_live_vllm_call() -> None:
    if not os.environ.get("VLLM_LIVE_TEST"):
        pytest.skip("VLLM_LIVE_TEST not set")
    adapter = VLLMAdapter(os.environ.get("VLLM_MODEL", MODEL))
    response = asyncio.run(
        adapter.chat([Message(role="user", content="Reply with the word pong.")])
    )
    assert response.content is not None
    assert response.usage.total_tokens > 0
