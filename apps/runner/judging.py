"""LLM-judge rubric scoring (issue #19).

The judge call is routed through the adapter layer like any other provider
call (ADR-0002). Judge rubrics are non-deterministic by nature (ADR-0003),
so the score detail records the judge model and temperature for approximate
reproduction, plus the judge verdict and the judge cost. The judge cost is
recorded only inside the score detail, never on the trace, so run
cost-per-correct-answer stays free of judging spend (issue #19; ADR-0004).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal

from agent_arena.adapters import AgentAdapter, Message
from agent_arena.db.models import Rubric, Run, Score, Task, TraceMetadata
from agent_arena.trace_store import TraceNotFoundError, TraceStore
from sqlalchemy.exc import IntegrityError

from apps.runner.contracts import DefinitionError, RubricDefinition, TaskDefinition
from apps.runner.execution import AdapterSource, SessionFactory
from apps.runner.scoring import ScoreResult, _extract_json

_CORRECT = Decimal("1.0000")
_INCORRECT = Decimal("0.0000")

_JUDGE_SYSTEM = (
    "You are an impartial evaluation judge. Decide whether the candidate answer "
    "solves the task. Respond with a JSON object of the form "
    '{"correct": true or false, "reason": "one sentence"} and nothing else.'
)


def build_judge_messages(
    rubric: RubricDefinition, task: TaskDefinition, final_answer: str
) -> list[Message]:
    parts = [f"Task:\n{task.prompt}"]
    if task.expected is not None:
        parts.append(f"Reference expectation:\n{task.expected}")
    if rubric.instructions:
        parts.append(f"Judging instructions:\n{rubric.instructions}")
    parts.append(f"Candidate answer:\n{final_answer}")
    return [
        Message(role="system", content=_JUDGE_SYSTEM),
        Message(role="user", content="\n\n".join(parts)),
    ]


async def judge_answer(
    adapter: AgentAdapter,
    rubric: RubricDefinition,
    task: TaskDefinition,
    final_answer: str | None,
) -> ScoreResult:
    """Score an answer with an LLM judge through the adapter layer."""
    detail_base = {
        "method": "llm_judge",
        "judge_provider": rubric.judge_provider,
        "judge_model": rubric.judge_model,
        "judge_temperature": rubric.judge_temperature,
    }
    if final_answer is None:
        return ScoreResult(
            score=_INCORRECT,
            is_correct=False,
            detail={**detail_base, "reason": "no final answer"},
        )

    response = await adapter.chat(
        build_judge_messages(rubric, task, final_answer),
        temperature=rubric.judge_temperature,
    )
    judge_cost = adapter.estimate_cost(response.usage)
    detail = {
        **detail_base,
        # Separate from the run cost by design; see the module docstring.
        "judge_cost_usd": str(judge_cost),
        "judge_usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "cached_tokens": response.usage.cached_tokens,
        },
        "judge_raw": response.content,
    }

    verdict = _parse_verdict(response.content)
    if verdict is None:
        return ScoreResult(
            score=_INCORRECT,
            is_correct=False,
            detail={**detail, "reason": "judge response was not a valid verdict"},
        )
    correct, reason = verdict
    return ScoreResult(
        score=_CORRECT if correct else _INCORRECT,
        is_correct=correct,
        detail={**detail, "reason": reason},
    )


def _parse_verdict(content: str | None) -> tuple[bool, str] | None:
    if content is None:
        return None
    try:
        parsed = json.loads(_extract_json(content))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("correct"), bool):
        return None
    return parsed["correct"], str(parsed.get("reason", ""))


def execute_judge_score(
    trace_hash: str,
    rubric_id: uuid.UUID,
    *,
    session_factory: SessionFactory,
    registry: AdapterSource,
    trace_store: TraceStore,
) -> str:
    """Score one trace under one judge rubric. Idempotent; returns a status.

    The (trace_hash, rubric_hash) key makes re-delivery and racing writers
    safe: an existing score wins and the judge call is skipped entirely, so
    at most one judging spend happens per pair in the common path.
    """
    with session_factory() as session:
        rubric = session.get(Rubric, rubric_id)
        if rubric is None:
            return "unknown rubric"
        if session.get(Score, (trace_hash, rubric.definition_hash)) is not None:
            return "already scored"
        trace = session.get(TraceMetadata, trace_hash)
        if trace is None:
            return "unknown trace"
        run = session.get(Run, trace.run_id)
        task_row = session.get(Task, run.task_id) if run is not None else None
        if task_row is None:
            return "task unavailable"

        try:
            rubric_definition = RubricDefinition.parse(rubric.definition)
            task_definition = TaskDefinition.parse(task_row.definition)
        except DefinitionError as exc:
            return f"invalid definition: {exc}"
        if rubric_definition.type != "llm_judge":
            return "rubric is not an llm_judge rubric"

        try:
            body = trace_store.get(trace_hash)
        except TraceNotFoundError:
            return "trace body unavailable"
        final_answer = json.loads(body).get("final_answer")

        adapter = registry.get_adapter(
            rubric_definition.judge_provider or "", rubric_definition.judge_model or ""
        )
        result = asyncio.run(
            judge_answer(adapter, rubric_definition, task_definition, final_answer)
        )

        session.add(
            Score(
                trace_hash=trace_hash,
                rubric_hash=rubric.definition_hash,
                score=result.score,
                is_correct=result.is_correct,
                score_detail=result.detail,
                judge_model=rubric_definition.judge_model,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return "already scored"
        return "scored"
