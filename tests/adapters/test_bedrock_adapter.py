"""Bedrock adapter tests (issue #21).

Unit tests run offline against a fake injected client; live tests are gated
on AWS credentials plus BEDROCK_LIVE_TEST and cover one Claude and one
Mistral model, per the issue acceptance.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from decimal import Decimal

import pytest
from agent_arena.adapters import AgentAdapter, Capability, Message, TokenUsage, Tool
from agent_arena.adapters.bedrock_adapter import BedrockAdapter
from agent_arena.adapters.registry import default_registry
from botocore.exceptions import ClientError

CLAUDE = "anthropic.claude-3-5-haiku-20241022-v1:0"
MISTRAL = "mistral.mistral-large-2402-v1:0"


def _response(
    text: str | None = "hello",
    tool_use: dict | None = None,  # type: ignore[type-arg]
    stop_reason: str = "end_turn",
) -> dict:  # type: ignore[type-arg]
    content = []
    if text is not None:
        content.append({"text": text})
    if tool_use is not None:
        content.append({"toolUse": tool_use})
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop_reason,
        "usage": {"inputTokens": 12, "outputTokens": 7, "cacheReadInputTokens": 3},
        "ResponseMetadata": {"RequestId": "req-1"},
    }


class FakeBedrockClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []  # type: ignore[type-arg]

    def converse(self, **kwargs: object) -> dict:  # type: ignore[type-arg]
        self.requests.append(dict(kwargs))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]


def _throttle() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
    )


def test_registered_and_satisfies_protocol() -> None:
    assert default_registry().is_registered("bedrock")
    adapter = BedrockAdapter(CLAUDE, client=FakeBedrockClient([_response()]))
    assert isinstance(adapter, AgentAdapter)
    assert adapter.capabilities() == frozenset({Capability.CHAT, Capability.TOOL_CALLING})


def test_chat_normalises_messages_and_usage() -> None:
    client = FakeBedrockClient([_response()])
    adapter = BedrockAdapter(CLAUDE, client=client)
    response = asyncio.run(
        adapter.chat(
            [
                Message(role="system", content="be terse"),
                Message(role="user", content="hi"),
            ],
            temperature=0.2,
        )
    )
    request = client.requests[0]
    assert request["modelId"] == CLAUDE
    assert request["system"] == [{"text": "be terse"}]
    assert request["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]
    assert request["inferenceConfig"] == {"temperature": 0.2}
    assert response.content == "hello"
    assert response.usage == TokenUsage(prompt_tokens=12, completion_tokens=7, cached_tokens=3)
    assert response.finish_reason == "end_turn"
    assert response.provider_metadata["request_id"] == "req-1"


def test_tool_round_trip() -> None:
    tool_use = {"toolUseId": "t1", "name": "calculator", "input": {"expression": "6 * 7"}}
    client = FakeBedrockClient([_response(text=None, tool_use=tool_use, stop_reason="tool_use")])
    adapter = BedrockAdapter(CLAUDE, client=client)
    tool = Tool(name="calculator", description="maths", parameters={"type": "object"})

    first = asyncio.run(adapter.chat([Message(role="user", content="compute")], tools=[tool]))
    assert first.tool_calls[0].name == "calculator"
    assert first.tool_calls[0].arguments == {"expression": "6 * 7"}
    request = client.requests[0]
    assert request["toolConfig"]["tools"][0]["toolSpec"]["name"] == "calculator"

    # Feed the tool result back: assistant toolUse then user toolResult.
    client2 = FakeBedrockClient([_response(text="42")])
    adapter2 = BedrockAdapter(CLAUDE, client=client2)
    asyncio.run(
        adapter2.chat(
            [
                Message(role="user", content="compute"),
                Message(role="assistant", tool_calls=first.tool_calls),
                Message(role="tool", content="42", tool_call_id="t1", name="calculator"),
            ]
        )
    )
    messages = client2.requests[0]["messages"]
    assert messages[1]["content"][0]["toolUse"]["toolUseId"] == "t1"
    assert messages[2]["content"][0]["toolResult"]["toolUseId"] == "t1"
    assert messages[2]["role"] == "user"


def test_retries_throttling_then_succeeds() -> None:
    client = FakeBedrockClient([_throttle(), _throttle(), _response()])
    adapter = BedrockAdapter(CLAUDE, client=client, base_backoff_seconds=0)
    response = asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert response.content == "hello"
    assert len(client.requests) == 3


def test_retry_budget_exhausted_raises() -> None:
    client = FakeBedrockClient([_throttle(), _throttle(), _throttle()])
    adapter = BedrockAdapter(CLAUDE, client=client, base_backoff_seconds=0, max_retries=3)
    with pytest.raises(ClientError):
        asyncio.run(adapter.chat([Message(role="user", content="hi")]))


def test_non_retryable_error_propagates_immediately() -> None:
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse")
    client = FakeBedrockClient([denied, _response()])
    adapter = BedrockAdapter(CLAUDE, client=client, base_backoff_seconds=0)
    with pytest.raises(ClientError):
        asyncio.run(adapter.chat([Message(role="user", content="hi")]))
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (CLAUDE, Decimal("0.0088")),
        (MISTRAL, Decimal("0.028")),
    ],
)
def test_cost_normalised_through_bedrock_pricing(model: str, expected: Decimal) -> None:
    adapter = BedrockAdapter(model, client=FakeBedrockClient([]), clock=lambda: date(2026, 7, 1))
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=2000, cached_tokens=0)
    assert adapter.estimate_cost(usage) == expected


@pytest.mark.integration
@pytest.mark.parametrize("model", [CLAUDE, MISTRAL])
def test_live_bedrock_call(model: str) -> None:
    if not os.environ.get("BEDROCK_LIVE_TEST"):
        pytest.skip("BEDROCK_LIVE_TEST not set")
    adapter = BedrockAdapter(model)
    response = asyncio.run(
        adapter.chat([Message(role="user", content="Reply with the word pong.")])
    )
    assert response.content is not None
    assert response.usage.total_tokens > 0
