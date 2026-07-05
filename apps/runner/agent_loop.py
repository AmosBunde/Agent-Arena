"""The sequential agent loop.

One run executes serially inside one worker (system-design.md, Concurrency
model). The loop feeds the task prompt to the adapter, executes built-in
tools when the model requests them, and stops on the first turn without tool
calls or when the turn ceiling is reached. Cancellation is cooperative: the
caller's ``cancel_requested`` callable is checked between provider calls
(session-design.md, Cancellation).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent_arena.adapters import AdapterResponse, AgentAdapter, Message, ToolCall

from apps.runner.contracts import AgentDefinition, TaskDefinition
from apps.runner.tools import ToolExecutionError, execute_tool, tool_specs


class RunCancelled(Exception):
    """The user cancelled the run; abort cleanly at the next checkpoint."""


@dataclass(frozen=True, slots=True)
class LoopStep:
    """One provider round trip, captured for the trace."""

    index: int
    request_messages: tuple[Message, ...]
    response: AdapterResponse
    tool_results: tuple[tuple[ToolCall, str], ...] = ()


@dataclass(slots=True)
class LoopResult:
    steps: list[LoopStep] = field(default_factory=list)
    final_answer: str | None = None
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    total_latency_ms: int = 0
    tool_call_count: int = 0
    turn_limit_reached: bool = False


def _never_cancelled() -> bool:
    return False


async def run_agent_loop(
    adapter: AgentAdapter,
    task: TaskDefinition,
    agent: AgentDefinition,
    *,
    default_max_turns: int,
    cancel_requested: Callable[[], bool] = _never_cancelled,
) -> LoopResult:
    """Run the agent to completion and return the captured loop state."""
    max_turns = task.max_turns or default_max_turns
    tools = tool_specs(task.tools) if task.tools else None

    system_parts = [part for part in (agent.system_prompt, task.system) if part]
    messages: list[Message] = []
    if system_parts:
        messages.append(Message(role="system", content="\n\n".join(system_parts)))
    messages.append(Message(role="user", content=task.prompt))

    result = LoopResult()
    for turn in range(max_turns):
        if cancel_requested():
            raise RunCancelled

        request_snapshot = tuple(messages)
        response = await adapter.chat(
            messages,
            tools=tools,
            temperature=agent.temperature,
        )
        result.total_prompt_tokens += response.usage.prompt_tokens
        result.total_completion_tokens += response.usage.completion_tokens
        result.total_cached_tokens += response.usage.cached_tokens
        result.total_latency_ms += response.latency_ms

        if not response.tool_calls:
            result.steps.append(
                LoopStep(index=turn, request_messages=request_snapshot, response=response)
            )
            result.final_answer = response.content
            return result

        result.tool_call_count += len(response.tool_calls)
        messages.append(
            Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )
        tool_results: list[tuple[ToolCall, str]] = []
        for call in response.tool_calls:
            output = _execute_tool_safely(call, task)
            tool_results.append((call, output))
            messages.append(
                Message(
                    role="tool",
                    content=output,
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
        result.steps.append(
            LoopStep(
                index=turn,
                request_messages=request_snapshot,
                response=response,
                tool_results=tuple(tool_results),
            )
        )

    result.turn_limit_reached = True
    return result


def _execute_tool_safely(call: ToolCall, task: TaskDefinition) -> str:
    """Tool failures are returned to the model as the tool result.

    A malformed tool request is agent behaviour worth capturing and scoring,
    not an infrastructure failure, so it does not abort the run.
    """
    arguments: dict[str, Any] = call.arguments
    try:
        return execute_tool(call.name, arguments, task)
    except ToolExecutionError as exc:
        return f"tool error: {exc}"
