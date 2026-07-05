"""Unit tests for deterministic rubric scoring."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.runner.contracts import RubricDefinition, TaskDefinition
from apps.runner.scoring import ScoringError, score_answer


def _task(expected: object) -> TaskDefinition:
    return TaskDefinition(prompt="q", expected=expected)


def test_exact_match_correct_with_default_strip() -> None:
    rubric = RubricDefinition(type="exact_match")
    result = score_answer(rubric, _task("42"), "  42\n")
    assert result.is_correct
    assert result.score == Decimal("1.0000")


def test_exact_match_case_sensitivity() -> None:
    strict = RubricDefinition(type="exact_match")
    relaxed = RubricDefinition(type="exact_match", case_insensitive=True)
    task = _task("Paris")
    assert not score_answer(strict, task, "paris").is_correct
    assert score_answer(relaxed, task, "paris").is_correct


def test_exact_match_incorrect() -> None:
    result = score_answer(RubricDefinition(type="exact_match"), _task("42"), "41")
    assert not result.is_correct
    assert result.score == Decimal("0.0000")
    assert result.detail["expected"] == "42"


def test_regex_match() -> None:
    rubric = RubricDefinition(type="regex_match")
    task = _task(r"\b42\b")
    assert score_answer(rubric, task, "the answer is 42.").is_correct
    assert not score_answer(rubric, task, "the answer is 422.").is_correct


def test_regex_match_invalid_pattern_raises() -> None:
    with pytest.raises(ScoringError, match="valid regex"):
        score_answer(RubricDefinition(type="regex_match"), _task("("), "anything")


def test_json_key_match_correct_subset() -> None:
    rubric = RubricDefinition(type="json_key_match")
    task = _task({"answer": 42})
    result = score_answer(rubric, task, '{"answer": 42, "reasoning": "..."}')
    assert result.is_correct


def test_json_key_match_extracts_from_prose() -> None:
    rubric = RubricDefinition(type="json_key_match")
    task = _task({"answer": 42})
    answer = 'Here is the result:\n```json\n{"answer": 42}\n```\nDone.'
    assert score_answer(rubric, task, answer).is_correct


def test_json_key_match_mismatch_detail() -> None:
    rubric = RubricDefinition(type="json_key_match")
    result = score_answer(rubric, _task({"answer": 42}), '{"answer": 41}')
    assert not result.is_correct
    assert result.detail["mismatches"]["answer"] == {"expected": 42, "actual": 41}


def test_json_key_match_invalid_json() -> None:
    rubric = RubricDefinition(type="json_key_match")
    result = score_answer(rubric, _task({"answer": 42}), "not json at all")
    assert not result.is_correct
    assert result.detail["reason"] == "answer is not valid JSON"


def test_no_final_answer_scores_zero() -> None:
    result = score_answer(RubricDefinition(type="exact_match"), _task("42"), None)
    assert not result.is_correct
    assert result.detail["reason"] == "no final answer"


def test_missing_expected_raises() -> None:
    with pytest.raises(ScoringError, match="requires the task to define 'expected'"):
        score_answer(RubricDefinition(type="exact_match"), _task(None), "42")
