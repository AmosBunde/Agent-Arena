"""Tests for issue #19: LLM-judge rubric scoring."""

from __future__ import annotations

import uuid

import pytest

from apps.runner.contracts import DefinitionError, RubricDefinition, TaskDefinition
from apps.runner.judging import execute_judge_score, judge_answer
from apps.runner.scoring import ScoringError, score_answer
from tests.runner.fakes import FakeAdapter, response

JUDGE_RUBRIC = RubricDefinition(
    type="llm_judge",
    judge_provider="fake",
    judge_model="fake-judge",
    judge_temperature=0.0,
)
TASK = TaskDefinition(prompt="what is 6 * 7?", expected="42")


def _run(coro):  # type: ignore[no-untyped-def]
    import asyncio

    return asyncio.run(coro)


def test_judge_rubric_contract_requires_judge_fields() -> None:
    with pytest.raises(DefinitionError, match="judge_provider"):
        RubricDefinition.parse({"type": "llm_judge"})
    with pytest.raises(DefinitionError, match="judge_model"):
        RubricDefinition.parse({"type": "llm_judge", "judge_provider": "openai"})
    parsed = RubricDefinition.parse(
        {"type": "llm_judge", "judge_provider": "openai", "judge_model": "gpt-4o-mini"}
    )
    assert parsed.judge_temperature == 0.0


def test_sync_scoring_rejects_judge_rubrics() -> None:
    with pytest.raises(ScoringError, match="judging"):
        score_answer(JUDGE_RUBRIC, TASK, "42")


def test_judge_answer_correct_verdict_and_cost_detail() -> None:
    adapter = FakeAdapter(
        responses=[response('{"correct": true, "reason": "matches the expectation"}')]
    )
    result = _run(judge_answer(adapter, JUDGE_RUBRIC, TASK, "42"))
    assert result.is_correct
    assert result.detail["judge_model"] == "fake-judge"
    assert result.detail["judge_cost_usd"] == "0.000015"
    assert result.detail["reason"] == "matches the expectation"
    # Judge call went through the adapter layer with the rubric temperature.
    assert adapter.calls[0]["temperature"] == 0.0
    prompt = adapter.calls[0]["messages"][1].content
    assert "what is 6 * 7?" in prompt and "42" in prompt


def test_judge_answer_incorrect_verdict() -> None:
    adapter = FakeAdapter(responses=[response('{"correct": false, "reason": "wrong"}')])
    result = _run(judge_answer(adapter, JUDGE_RUBRIC, TASK, "41"))
    assert not result.is_correct


def test_judge_answer_malformed_verdict_scores_incorrect() -> None:
    adapter = FakeAdapter(responses=[response("I think the answer is fine.")])
    result = _run(judge_answer(adapter, JUDGE_RUBRIC, TASK, "42"))
    assert not result.is_correct
    assert result.detail["reason"] == "judge response was not a valid verdict"


def test_judge_answer_without_final_answer_skips_the_call() -> None:
    adapter = FakeAdapter(responses=[])
    result = _run(judge_answer(adapter, JUDGE_RUBRIC, TASK, None))
    assert not result.is_correct
    assert adapter.calls == []


@pytest.mark.integration
def test_judge_run_enqueues_followup_and_judge_task_scores(
    session_factory,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    from agent_arena.adapters import AdapterRegistry
    from agent_arena.trace_store import LocalTraceStore

    from apps.runner.execution import execute_run_sync
    from tests.runner.test_execution import _fetch, _seed_run

    store = LocalTraceStore(tmp_path)
    enqueued: list[tuple[str, uuid.UUID]] = []

    agent_adapter = FakeAdapter(responses=[response("42")])
    registry = AdapterRegistry()
    registry.register("fake", agent_adapter)

    run_id = _seed_run(session_factory, judge_required=True)
    # Make the judge rubric definition real so the follow-up can parse it.
    from agent_arena.db.models import Rubric, Run

    with session_factory() as session:
        run = session.get(Run, run_id)
        rubric = session.get(Rubric, run.rubric_id)
        rubric.definition = {
            "type": "llm_judge",
            "judge_provider": "fake-judge-provider",
            "judge_model": "fake-judge",
        }
        rubric_id = rubric.id
        session.commit()

    outcome = execute_run_sync(
        run_id,
        session_factory=session_factory,
        registry=registry,
        trace_store=store,
        enqueue_judge=lambda trace_hash, rid: enqueued.append((trace_hash, rid)),
    )
    assert outcome.run_status == "complete"
    assert len(enqueued) == 1
    trace_hash, enqueued_rubric = enqueued[0]
    assert enqueued_rubric == rubric_id

    # No score yet: judge scoring is the follow-up job.
    _, _, traces, scores = _fetch(session_factory, run_id)
    assert scores == []
    assert traces[0].hash == trace_hash

    judge_adapter = FakeAdapter(responses=[response('{"correct": true, "reason": "ok"}')])
    judge_registry = AdapterRegistry()
    judge_registry.register("fake-judge-provider", judge_adapter)

    status = execute_judge_score(
        trace_hash,
        rubric_id,
        session_factory=session_factory,
        registry=judge_registry,
        trace_store=store,
    )
    assert status == "scored"

    _, _, traces, scores = _fetch(session_factory, run_id)
    assert len(scores) == 1
    assert scores[0].is_correct
    assert scores[0].judge_model == "fake-judge"
    detail = scores[0].score_detail
    assert detail["method"] == "llm_judge"
    assert "judge_cost_usd" in detail
    # The judge spend stays out of the run cost (issue #19): the trace cost
    # reflects only the agent call.
    assert str(traces[0].estimated_cost_usd) == "0.000015"

    # Idempotent: a redelivered job does not call the judge again.
    assert (
        execute_judge_score(
            trace_hash,
            rubric_id,
            session_factory=session_factory,
            registry=judge_registry,
            trace_store=store,
        )
        == "already scored"
    )
    assert len(judge_adapter.calls) == 1
