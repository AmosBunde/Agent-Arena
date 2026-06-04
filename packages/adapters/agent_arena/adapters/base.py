"""The provider adapter interface.

Defines the ``AgentAdapter`` protocol and its value types per ADR-0002. One
concrete adapter per provider implements this protocol; the runner talks only
to the protocol and is provider-agnostic by construction.

See docs/adr/0002-provider-adapter-pattern.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Protocol, runtime_checkable


class Capability(Enum):
    """A feature an adapter may or may not support.

    The runner negotiates required capabilities before dispatching a task; a
    model that lacks a required capability yields ``skipped_unsupported`` rather
    than a zero score, which keeps the leaderboard honest (ADR-0002). New
    capabilities are added through the ADR amendment process.
    """

    CHAT = "chat"
    TOOL_CALLING = "tool_calling"
    STREAMING = "streaming"
    VISION = "vision"
    JSON_MODE = "json_mode"


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider-normalised token accounting.

    Each adapter translates its provider's usage object into this shape.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class Tool:
    """A tool offered to the model, described by a JSON Schema parameter spec."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A structured tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    """A single chat turn.

    ``tool_calls`` is populated on assistant turns that invoke tools;
    ``tool_call_id`` links a ``tool`` turn back to the call it answers.
    """

    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    """The normalised result of a single ``chat`` call."""

    provider: str
    model: str
    content: str | None
    usage: TokenUsage
    latency_ms: int
    finish_reason: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    # Deliberate, scoped leak for genuine provider-specific fields that cannot
    # be expressed uniformly (ADR-0002). Consumers must tolerate it being empty
    # or differently shaped across providers.
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentAdapter(Protocol):
    """The interface every provider adapter implements.

    Enforced at runtime by the registry's registration check; static typing
    alone is not relied upon (ADR-0002).
    """

    provider: str
    model: str

    def capabilities(self) -> frozenset[Capability]: ...

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse: ...

    def estimate_cost(self, usage: TokenUsage) -> Decimal: ...


class AdapterError(Exception):
    """Base class for adapter-layer errors."""


class UnknownProviderError(AdapterError, KeyError):
    """Raised when no adapter is registered for a requested provider."""


class DuplicateAdapterError(AdapterError):
    """Raised when registering a provider that is already registered."""


class AdapterProtocolError(AdapterError, TypeError):
    """Raised when a registered object does not satisfy ``AgentAdapter``."""


def missing_capabilities(
    adapter: AgentAdapter, required: Iterable[Capability]
) -> frozenset[Capability]:
    """Return the required capabilities the adapter does not support."""
    return frozenset(required) - adapter.capabilities()


def supports(adapter: AgentAdapter, required: Iterable[Capability]) -> bool:
    """Return whether the adapter supports every required capability."""
    return not missing_capabilities(adapter, required)
