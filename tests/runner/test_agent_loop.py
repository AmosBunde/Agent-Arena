"""Unit tests for the sequential agent loop."""

from __future__ import annotations

import asyncio

import pytest
from agent_arena.adapters import ToolCall

from apps.runner.agent_loop import RunCancelled, run_agent_loop
from apps.runner.contracts import AgentDefinition, TaskDefinition
from tests.runner.conftest import FakeAdapter, response


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_direct_answer_single_turn() -> None:
    adapter = FakeAdapter(responses=[response("42")])
    task = TaskDefinition(prompt="what is 6 times 7?")
    result = _run(run_agent_loop(adapter, task, AgentDefinition(), default_max_turns=4))
    assert result.final_answer == "42"
    assert len(result.steps) == 1
    assert result.tool_call_count == 0
    assert result.total_prompt_tokens == 10
    assert result.total_completion_tokens == 5
    assert not result.turn_limit_reached


def test_system_prompts_compose_agent_then_task() -> None:
    adapter = FakeAdapter(responses=[response("ok")])
    task = TaskDefinition(prompt="q", system="task system")
    agent = AgentDefinition(system_prompt="agent system")
    _run(run_agent_loop(adapter, task, agent, default_max_turns=2))
    first_messages = adapter.calls[0]["messages"]
    assert first_messages[0].role == "system"
    assert first_messages[0].content == "agent system\n\ntask system"
    assert first_messages[1].role == "user"


def test_tool_call_round_trip() -> None:
    call = ToolCall(id="c1", name="calculator", arguments={"expression": "6 * 7"})
    adapter = FakeAdapter(responses=[response(None, tool_calls=(call,)), response("42")])
    task = TaskDefinition(prompt="compute 6 * 7", tools=("calculator",))
    result = _run(run_agent_loop(adapter, task, AgentDefinition(), default_max_turns=4))
    assert result.final_answer == "42"
    assert result.tool_call_count == 1
    assert len(result.steps) == 2
    assert result.steps[0].tool_results[0][1] == "42"
    # The second provider call must carry the assistant tool call and the
    # tool result message.
    second_messages = adapter.calls[1]["messages"]
    assert second_messages[-2].role == "assistant"
    assert second_messages[-2].tool_calls == (call,)
    assert second_messages[-1].role == "tool"
    assert second_messages[-1].content == "42"
    assert second_messages[-1].tool_call_id == "c1"


def test_tool_error_is_returned_to_model() -> None:
    call = ToolCall(id="c1", name="calculator", arguments={"expression": "x + 1"})
    adapter = FakeAdapter(responses=[response(None, tool_calls=(call,)), response("cannot")])
    task = TaskDefinition(prompt="q", tools=("calculator",))
    result = _run(run_agent_loop(adapter, task, AgentDefinition(), default_max_turns=4))
    assert result.steps[0].tool_results[0][1].startswith("tool error:")
    assert result.final_answer == "cannot"


def test_turn_limit_reached() -> None:
    call = ToolCall(id="c", name="calculator", arguments={"expression": "1"})
    adapter = FakeAdapter(
        responses=[response(None, tool_calls=(call,)), response(None, tool_calls=(call,))]
    )
    task = TaskDefinition(prompt="q", tools=("calculator",), max_turns=2)
    result = _run(run_agent_loop(adapter, task, AgentDefinition(), default_max_turns=8))
    assert result.turn_limit_reached
    assert result.final_answer is None
    assert len(result.steps) == 2


def test_usage_accumulates_across_turns() -> None:
    call = ToolCall(id="c", name="calculator", arguments={"expression": "1"})
    adapter = FakeAdapter(
        responses=[
            response(None, tool_calls=(call,), prompt_tokens=100, completion_tokens=20),
            response("1", prompt_tokens=150, completion_tokens=10, latency_ms=250),
        ]
    )
    task = TaskDefinition(prompt="q", tools=("calculator",))
    result = _run(run_agent_loop(adapter, task, AgentDefinition(), default_max_turns=4))
    assert result.total_prompt_tokens == 250
    assert result.total_completion_tokens == 30
    assert result.total_latency_ms == 350


def test_temperature_passthrough() -> None:
    adapter = FakeAdapter(responses=[response("ok")])
    task = TaskDefinition(prompt="q")
    agent = AgentDefinition(temperature=0.2)
    _run(run_agent_loop(adapter, task, agent, default_max_turns=2))
    assert adapter.calls[0]["temperature"] == 0.2


def test_cancellation_checked_before_each_turn() -> None:
    adapter = FakeAdapter(responses=[response("ok")])
    task = TaskDefinition(prompt="q")
    with pytest.raises(RunCancelled):
        _run(
            run_agent_loop(
                adapter,
                task,
                AgentDefinition(),
                default_max_turns=2,
                cancel_requested=lambda: True,
            )
        )
    assert adapter.calls == []
