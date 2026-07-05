"""Unit tests for trace assembly and hashing."""

from __future__ import annotations

import uuid

from apps.runner.agent_loop import LoopResult, LoopStep
from apps.runner.tracing import build_trace, serialise_trace
from tests.runner.conftest import response

RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _trace(final_answer: str = "42") -> dict:  # type: ignore[type-arg]
    result = LoopResult(final_answer=final_answer)
    result.steps.append(LoopStep(index=0, request_messages=(), response=response(final_answer)))
    result.total_prompt_tokens = 10
    result.total_completion_tokens = 5
    result.total_latency_ms = 100
    return build_trace(
        run_id=RUN_ID,
        provider="fake",
        model="fake-model",
        task_slug="add",
        task_version="1",
        agent_slug="solver",
        agent_version="1",
        result=result,
    )


def test_serialisation_is_deterministic() -> None:
    first = serialise_trace(_trace())
    second = serialise_trace(_trace())
    assert first.hash == second.hash
    assert first.body == second.body
    assert first.size_bytes == len(first.body.encode("utf-8"))


def test_different_content_changes_hash() -> None:
    assert serialise_trace(_trace("42")).hash != serialise_trace(_trace("41")).hash


def test_trace_document_shape() -> None:
    document = _trace()
    assert document["schema_version"] == 1
    assert document["run_id"] == str(RUN_ID)
    assert document["final_answer"] == "42"
    assert document["totals"]["prompt_tokens"] == 10
    step = document["steps"][0]
    assert step["response"]["content"] == "42"
    assert step["response"]["usage"]["completion_tokens"] == 5
