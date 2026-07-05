"""Unit tests for definition contracts."""

from __future__ import annotations

import pytest

from apps.runner.contracts import (
    AgentDefinition,
    DefinitionError,
    RubricDefinition,
    TaskDefinition,
)


def test_task_requires_prompt() -> None:
    with pytest.raises(DefinitionError, match="prompt"):
        TaskDefinition.parse({})


def test_task_rejects_boolean_max_turns() -> None:
    with pytest.raises(DefinitionError, match="max_turns"):
        TaskDefinition.parse({"prompt": "q", "max_turns": True})


def test_task_rejects_non_positive_max_turns() -> None:
    with pytest.raises(DefinitionError, match="max_turns"):
        TaskDefinition.parse({"prompt": "q", "max_turns": 0})


def test_agent_rejects_boolean_temperature() -> None:
    with pytest.raises(DefinitionError, match="temperature"):
        AgentDefinition.parse({"temperature": True})


def test_agent_accepts_integer_temperature() -> None:
    assert AgentDefinition.parse({"temperature": 1}).temperature == 1.0


def test_rubric_requires_known_type() -> None:
    with pytest.raises(DefinitionError, match="type"):
        RubricDefinition.parse({"type": "vibes"})
