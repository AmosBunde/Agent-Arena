"""Unit tests for the built-in deterministic tools."""

from __future__ import annotations

import pytest

from apps.runner.contracts import TaskDefinition
from apps.runner.tools import ToolExecutionError, execute_tool, tool_specs

TASK = TaskDefinition(
    prompt="q",
    tools=("calculator", "search"),
    search_corpus={"capital of France": "Paris is the capital of France."},
)


def test_tool_specs_resolves_known_tools() -> None:
    specs = tool_specs(("calculator", "search"))
    assert [tool.name for tool in specs] == ["calculator", "search"]


def test_tool_specs_rejects_unknown_tool() -> None:
    with pytest.raises(ToolExecutionError, match="unknown tools"):
        tool_specs(("calculator", "web_browser"))


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 1", "2"),
        ("(3 + 4) * 2", "14"),
        ("10 / 4", "2.5"),
        ("2 ** 10", "1024"),
        ("7 % 3", "1"),
        ("-5 + 2", "-3"),
        ("10 // 3", "3"),
    ],
)
def test_calculator_evaluates(expression: str, expected: str) -> None:
    assert execute_tool("calculator", {"expression": expression}, TASK) == expected


@pytest.mark.parametrize(
    "expression",
    ["__import__('os')", "x + 1", "(1).bit_length()", "1 if True else 2", "1 / 0", "1 +"],
)
def test_calculator_rejects_unsafe_or_invalid(expression: str) -> None:
    with pytest.raises(ToolExecutionError):
        execute_tool("calculator", {"expression": expression}, TASK)


def test_calculator_requires_string_expression() -> None:
    with pytest.raises(ToolExecutionError, match="string 'expression'"):
        execute_tool("calculator", {"expression": 7}, TASK)


def test_search_exact_key() -> None:
    result = execute_tool("search", {"query": "capital of France"}, TASK)
    assert result == "Paris is the capital of France."


def test_search_substring_match_is_case_insensitive() -> None:
    result = execute_tool("search", {"query": "the CAPITAL OF FRANCE please"}, TASK)
    assert result == "Paris is the capital of France."


def test_search_no_results() -> None:
    assert execute_tool("search", {"query": "capital of Peru"}, TASK) == "no results"


def test_unknown_tool_name() -> None:
    with pytest.raises(ToolExecutionError, match="unknown tool"):
        execute_tool("web_browser", {}, TASK)
