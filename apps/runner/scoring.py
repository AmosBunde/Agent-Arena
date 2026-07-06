"""Synchronous scoring for deterministic rubrics.

Deterministic rubrics compare the agent's final answer to the task's
``expected`` reference output. LLM-judge rubrics (``judge_required``) are out
of scope here; they arrive with issue #19 as a follow-up Celery task.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.runner.contracts import RubricDefinition, TaskDefinition

_CORRECT = Decimal("1.0000")
_INCORRECT = Decimal("0.0000")


class ScoringError(ValueError):
    """The rubric cannot be applied to this task or answer."""


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: Decimal
    is_correct: bool
    detail: dict[str, Any]


def score_answer(
    rubric: RubricDefinition, task: TaskDefinition, final_answer: str | None
) -> ScoreResult:
    """Apply a deterministic rubric to the agent's final answer."""
    if final_answer is None:
        return ScoreResult(
            score=_INCORRECT,
            is_correct=False,
            detail={"method": rubric.type, "reason": "no final answer"},
        )
    if rubric.type == "exact_match":
        return _exact_match(rubric, task, final_answer)
    if rubric.type == "regex_match":
        return _regex_match(task, final_answer)
    if rubric.type == "json_key_match":
        return _json_key_match(task, final_answer)
    if rubric.type == "llm_judge":
        raise ScoringError("llm_judge rubrics are scored through apps.runner.judging")
    raise ScoringError(f"unsupported rubric type {rubric.type!r}")


def _require_expected(task: TaskDefinition, rubric_type: str) -> Any:
    if task.expected is None:
        raise ScoringError(f"rubric {rubric_type!r} requires the task to define 'expected'")
    return task.expected


def _exact_match(rubric: RubricDefinition, task: TaskDefinition, answer: str) -> ScoreResult:
    expected = str(_require_expected(task, "exact_match"))
    actual = answer
    if rubric.strip_whitespace:
        expected, actual = expected.strip(), actual.strip()
    if rubric.case_insensitive:
        expected, actual = expected.lower(), actual.lower()
    correct = actual == expected
    return ScoreResult(
        score=_CORRECT if correct else _INCORRECT,
        is_correct=correct,
        detail={"method": "exact_match", "expected": expected, "actual": actual},
    )


def _regex_match(task: TaskDefinition, answer: str) -> ScoreResult:
    pattern = str(_require_expected(task, "regex_match"))
    try:
        matched = re.search(pattern, answer) is not None
    except re.error as exc:
        raise ScoringError(f"task 'expected' is not a valid regex: {exc}") from exc
    return ScoreResult(
        score=_CORRECT if matched else _INCORRECT,
        is_correct=matched,
        detail={"method": "regex_match", "pattern": pattern, "matched": matched},
    )


def _json_key_match(task: TaskDefinition, answer: str) -> ScoreResult:
    expected = _require_expected(task, "json_key_match")
    if not isinstance(expected, dict):
        raise ScoringError("rubric 'json_key_match' requires 'expected' to be an object")
    try:
        parsed = json.loads(_extract_json(answer))
    except (json.JSONDecodeError, ValueError):
        return ScoreResult(
            score=_INCORRECT,
            is_correct=False,
            detail={"method": "json_key_match", "reason": "answer is not valid JSON"},
        )
    if not isinstance(parsed, dict):
        return ScoreResult(
            score=_INCORRECT,
            is_correct=False,
            detail={"method": "json_key_match", "reason": "answer JSON is not an object"},
        )
    mismatches = {
        key: {"expected": value, "actual": parsed.get(key)}
        for key, value in expected.items()
        if parsed.get(key) != value
    }
    correct = not mismatches
    return ScoreResult(
        score=_CORRECT if correct else _INCORRECT,
        is_correct=correct,
        detail={"method": "json_key_match", "mismatches": mismatches},
    )


def _extract_json(answer: str) -> str:
    """Allow answers that wrap JSON in a fenced code block or prose."""
    stripped = answer.strip()
    if stripped.startswith("{"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in answer")
    return stripped[start : end + 1]
