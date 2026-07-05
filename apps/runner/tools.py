"""Built-in deterministic tools for M1 tool-use tasks.

Two tools exist: ``calculator`` (safe arithmetic evaluation) and ``search``
(lookup against a canned corpus supplied by the task definition). Both are
deterministic by construction so traces replay bit-identically (ADR-0003).
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

from agent_arena.adapters import Tool

from apps.runner.contracts import TaskDefinition


class ToolExecutionError(Exception):
    """A tool could not produce a result for the given arguments."""


CALCULATOR = Tool(
    name="calculator",
    description="Evaluate an arithmetic expression and return the numeric result.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Arithmetic expression, e.g. (3 + 4) * 2",
            }
        },
        "required": ["expression"],
    },
)

SEARCH = Tool(
    name="search",
    description="Search a reference corpus and return the best matching entry.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
        },
        "required": ["query"],
    },
)

_TOOL_SPECS: dict[str, Tool] = {tool.name: tool for tool in (CALCULATOR, SEARCH)}

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def tool_specs(names: tuple[str, ...]) -> list[Tool]:
    """Resolve tool names from a task definition into adapter Tool specs."""
    unknown = [name for name in names if name not in _TOOL_SPECS]
    if unknown:
        raise ToolExecutionError(f"unknown tools requested by task: {unknown}")
    return [_TOOL_SPECS[name] for name in names]


def execute_tool(name: str, arguments: dict[str, Any], task: TaskDefinition) -> str:
    """Execute a built-in tool and return its string result.

    Raising ``ToolExecutionError`` is reserved for malformed requests; the
    error text is returned to the model as the tool result so the agent can
    recover, mirroring how real tool backends report failures.
    """
    if name == "calculator":
        expression = arguments.get("expression")
        if not isinstance(expression, str):
            raise ToolExecutionError("calculator requires a string 'expression'")
        return _evaluate_arithmetic(expression)
    if name == "search":
        query = arguments.get("query")
        if not isinstance(query, str):
            raise ToolExecutionError("search requires a string 'query'")
        return _search_corpus(query, task.search_corpus)
    raise ToolExecutionError(f"unknown tool {name!r}")


def _evaluate_arithmetic(expression: str) -> str:
    """Evaluate arithmetic safely via the AST; no names, calls, or attributes."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _evaluate_node(tree.body)
    except ToolExecutionError:
        raise
    except (SyntaxError, ZeroDivisionError, OverflowError, ValueError) as exc:
        raise ToolExecutionError(f"cannot evaluate expression: {exc}") from exc
    if isinstance(result, float) and result.is_integer():
        return str(int(result))
    return str(result)


def _evaluate_node(node: ast.expr) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise ToolExecutionError("only numeric literals are allowed")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BINARY_OPERATORS.get(type(node.op))
        if op is None:
            raise ToolExecutionError(f"operator {type(node.op).__name__} is not allowed")
        return op(_evaluate_node(node.left), _evaluate_node(node.right))
    if isinstance(node, ast.UnaryOp):
        unary = _UNARY_OPERATORS.get(type(node.op))
        if unary is None:
            raise ToolExecutionError(f"operator {type(node.op).__name__} is not allowed")
        return unary(_evaluate_node(node.operand))
    raise ToolExecutionError(f"expression element {type(node).__name__} is not allowed")


def _search_corpus(query: str, corpus: dict[str, str]) -> str:
    """Exact key match first, then case-insensitive substring match."""
    if query in corpus:
        return corpus[query]
    lowered = query.lower()
    for key, value in corpus.items():
        if lowered in key.lower() or key.lower() in lowered:
            return value
    return "no results"
