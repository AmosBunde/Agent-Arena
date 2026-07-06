"""Trace assembly and hashing.

The trace captures every provider round trip in the run, including the
request parameters (temperature, offered tools) so the capture is auditable.
Serialisation and hashing use the canonical JSON rules from
``agent_arena.schemas.trace_canonical`` (ADR-0003, issue #15); ``body_uri``
stays NULL until the content-addressed store lands (issue #16).

The body includes run and attempt identity, which makes every hash unique
per attempt. That deliberately trades the cross-run deduplication property
of ADR-0003 for insert safety: ``traces.trace_metadata`` keys on the hash
and carries a run id, so two runs cannot share a row today. The schema
tension is tracked in issue #47.

Authorization material never enters the trace: adapters read credentials
from the environment and messages contain only conversation content
(system-design.md, Security).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from agent_arena.adapters import Message
from agent_arena.schemas import canonical_json, trace_hash

from apps.runner.agent_loop import LoopResult, LoopStep

TRACE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SerialisedTrace:
    body: str
    hash: str
    size_bytes: int


def build_trace(
    *,
    run_id: uuid.UUID,
    attempt_number: int,
    provider: str,
    model: str,
    task_slug: str,
    task_version: str,
    agent_slug: str,
    agent_version: str,
    result: LoopResult,
    temperature: float | None = None,
    tools: tuple[str, ...] = (),
    error: str | None = None,
) -> dict[str, Any]:
    """Assemble the trace document from the loop result."""
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "run_id": str(run_id),
        "attempt_number": attempt_number,
        "provider": provider,
        "model": model,
        "parameters": {"temperature": temperature, "tools": list(tools)},
        "task": {"slug": task_slug, "version": task_version},
        "agent": {"slug": agent_slug, "version": agent_version},
        "steps": [_step_to_dict(step) for step in result.steps],
        "final_answer": result.final_answer,
        "turn_limit_reached": result.turn_limit_reached,
        "error": error,
        "totals": {
            "prompt_tokens": result.total_prompt_tokens,
            "completion_tokens": result.total_completion_tokens,
            "cached_tokens": result.total_cached_tokens,
            "latency_ms": result.total_latency_ms,
            "tool_call_count": result.tool_call_count,
        },
    }


def serialise_trace(trace: dict[str, Any]) -> SerialisedTrace:
    """Serialise through the canonical JSON rules (ADR-0003)."""
    body = canonical_json(trace)
    return SerialisedTrace(
        body=body.decode("utf-8"),
        hash=trace_hash(trace),
        size_bytes=len(body),
    )


def _step_to_dict(step: LoopStep) -> dict[str, Any]:
    return {
        "index": step.index,
        "request_messages": [_message_to_dict(message) for message in step.request_messages],
        "response": {
            "content": step.response.content,
            "finish_reason": step.response.finish_reason,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in step.response.tool_calls
            ],
            "usage": {
                "prompt_tokens": step.response.usage.prompt_tokens,
                "completion_tokens": step.response.usage.completion_tokens,
                "cached_tokens": step.response.usage.cached_tokens,
            },
            "latency_ms": step.response.latency_ms,
            "provider_metadata": step.response.provider_metadata,
        },
        "tool_results": [
            {"tool_call_id": call.id, "name": call.name, "output": output}
            for call, output in step.tool_results
        ],
    }


def _message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
        "name": message.name,
    }
