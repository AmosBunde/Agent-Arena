"""Definition contracts for tasks, agents, and rubrics.

``catalog.tasks.definition``, ``catalog.agents.definition``, and
``catalog.rubrics.definition`` are JSONB with application-enforced shape
(ADR-0005). This module is the single place that shape is enforced for the
runner; the example YAML files under ``tasks/`` and ``rubrics/`` (issue #14)
conform to these contracts.

Task definition:

- ``prompt`` (required str): the user turn given to the agent.
- ``system`` (optional str): task-level system prompt.
- ``expected`` (optional): reference output consumed by deterministic rubrics.
- ``tools`` (optional list[str]): names of built-in tools to offer, from
  ``apps.runner.tools``.
- ``search_corpus`` (optional dict[str, str]): canned corpus for the
  ``search`` tool, keyed by query.
- ``max_turns`` (optional int): loop ceiling for this task.

Agent definition:

- ``system_prompt`` (optional str): agent strategy prompt, prepended before
  the task system prompt.
- ``temperature`` (optional float): sampling temperature passed to the
  adapter.

Rubric definition:

- ``type`` (required str): one of ``exact_match``, ``regex_match``,
  ``json_key_match``.
- ``case_insensitive`` (optional bool, exact_match only).
- ``strip_whitespace`` (optional bool, exact_match only, default true).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DefinitionError(ValueError):
    """A catalog definition does not satisfy its contract."""


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    prompt: str
    system: str | None = None
    expected: Any = None
    tools: tuple[str, ...] = ()
    search_corpus: dict[str, str] = field(default_factory=dict)
    max_turns: int | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> TaskDefinition:
        prompt = raw.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise DefinitionError("task definition requires a non-empty string 'prompt'")
        system = raw.get("system")
        if system is not None and not isinstance(system, str):
            raise DefinitionError("task 'system' must be a string when present")
        tools_raw = raw.get("tools", [])
        if not isinstance(tools_raw, list) or not all(isinstance(t, str) for t in tools_raw):
            raise DefinitionError("task 'tools' must be a list of tool names")
        corpus = raw.get("search_corpus", {})
        if not isinstance(corpus, dict):
            raise DefinitionError("task 'search_corpus' must be an object")
        max_turns = raw.get("max_turns")
        if max_turns is not None and (
            isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1
        ):
            raise DefinitionError("task 'max_turns' must be a positive integer")
        return cls(
            prompt=prompt,
            system=system,
            expected=raw.get("expected"),
            tools=tuple(tools_raw),
            search_corpus={str(k): str(v) for k, v in corpus.items()},
            max_turns=max_turns,
        )


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    system_prompt: str | None = None
    temperature: float | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> AgentDefinition:
        system_prompt = raw.get("system_prompt")
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise DefinitionError("agent 'system_prompt' must be a string when present")
        temperature = raw.get("temperature")
        if temperature is not None:
            if isinstance(temperature, bool) or not isinstance(temperature, int | float):
                raise DefinitionError("agent 'temperature' must be a number when present")
            temperature = float(temperature)
        return cls(system_prompt=system_prompt, temperature=temperature)


RUBRIC_TYPES = ("exact_match", "regex_match", "json_key_match", "llm_judge")


@dataclass(frozen=True, slots=True)
class RubricDefinition:
    type: str
    case_insensitive: bool = False
    strip_whitespace: bool = True
    # llm_judge only (issue #19). The judge call goes through the adapter
    # layer; temperature defaults to zero for approximate reproducibility
    # (ADR-0003).
    judge_provider: str | None = None
    judge_model: str | None = None
    judge_temperature: float = 0.0
    instructions: str | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> RubricDefinition:
        rubric_type = raw.get("type")
        if rubric_type not in RUBRIC_TYPES:
            raise DefinitionError(f"rubric 'type' must be one of {RUBRIC_TYPES}")
        judge_provider = raw.get("judge_provider")
        judge_model = raw.get("judge_model")
        judge_temperature = raw.get("judge_temperature", 0.0)
        instructions = raw.get("instructions")
        if rubric_type == "llm_judge":
            if not isinstance(judge_provider, str) or not judge_provider:
                raise DefinitionError("llm_judge rubrics require a 'judge_provider' string")
            if not isinstance(judge_model, str) or not judge_model:
                raise DefinitionError("llm_judge rubrics require a 'judge_model' string")
            if isinstance(judge_temperature, bool) or not isinstance(
                judge_temperature, int | float
            ):
                raise DefinitionError("'judge_temperature' must be a number")
            if instructions is not None and not isinstance(instructions, str):
                raise DefinitionError("'instructions' must be a string when present")
        return cls(
            type=rubric_type,
            case_insensitive=bool(raw.get("case_insensitive", False)),
            strip_whitespace=bool(raw.get("strip_whitespace", True)),
            judge_provider=judge_provider if rubric_type == "llm_judge" else None,
            judge_model=judge_model if rubric_type == "llm_judge" else None,
            judge_temperature=float(judge_temperature) if rubric_type == "llm_judge" else 0.0,
            instructions=instructions if rubric_type == "llm_judge" else None,
        )
