"""Versioned pricing data and cost computation.

Pricing lives in per-provider YAML files (ADR-0004). A price line is valid from
its ``valid_from`` date until the next line's ``valid_from`` for the same model,
so historical leaderboards are stable: a trace is always costed with the price
that was valid at its ``created_at``.

All money is ``Decimal``. The YAML float scalars are parsed straight into
``Decimal`` from their source text; plain ``yaml.safe_load`` would lose
precision by going through ``float`` first.
"""

from __future__ import annotations

import functools
import importlib.resources
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import yaml
from agent_arena.adapters import TokenUsage

DATA_PACKAGE = "agent_arena.cost_models.data"
_PER_MILLION = Decimal(1_000_000)
_SECONDS_PER_HOUR = Decimal(3600)
_MS_PER_SECOND = Decimal(1000)


class CostModelError(Exception):
    """Base class for cost-model errors."""


class UnknownModelError(CostModelError, KeyError):
    """Raised when no pricing exists for a provider/model."""


class NoPriceForDateError(CostModelError):
    """Raised when no price line covers the requested date."""


@dataclass(frozen=True, slots=True)
class PriceLine:
    """A single price record, valid from ``valid_from`` onward."""

    provider: str
    model: str
    valid_from: date
    is_local: bool = False
    input_per_million: Decimal = Decimal(0)
    output_per_million: Decimal = Decimal(0)
    cached_input_per_million: Decimal | None = None


class _DecimalSafeLoader(yaml.SafeLoader):
    """SafeLoader that yields ``Decimal`` for float scalars."""


def _construct_decimal(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> Decimal:
    return Decimal(node.value)


_DecimalSafeLoader.add_constructor("tag:yaml.org,2002:float", _construct_decimal)


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _parse_document(text: str) -> list[PriceLine]:
    document = yaml.load(text, Loader=_DecimalSafeLoader)
    provider = document["provider"]
    is_local = bool(document.get("is_local", False))
    lines: list[PriceLine] = []
    for entry in document.get("prices", []):
        cached = entry.get("cached_input_per_million_tokens")
        lines.append(
            PriceLine(
                provider=provider,
                model=entry["model"],
                valid_from=entry["valid_from"],
                is_local=is_local,
                input_per_million=_as_decimal(entry.get("input_per_million_tokens", 0)),
                output_per_million=_as_decimal(entry.get("output_per_million_tokens", 0)),
                cached_input_per_million=(None if cached is None else _as_decimal(cached)),
            )
        )
    return lines


class PricingTable:
    """An in-memory pricing table with ``valid_from``-aware lookup."""

    def __init__(self, lines: Iterable[PriceLine]) -> None:
        self._by_model: dict[tuple[str, str], list[PriceLine]] = {}
        for line in lines:
            self._by_model.setdefault((line.provider, line.model), []).append(line)
        for records in self._by_model.values():
            records.sort(key=lambda line: line.valid_from)

    @classmethod
    def load(cls, *, package: str = DATA_PACKAGE) -> PricingTable:
        """Load every YAML file packaged under ``package``."""
        lines: list[PriceLine] = []
        for resource in importlib.resources.files(package).iterdir():
            if resource.name.endswith((".yaml", ".yml")):
                lines.extend(_parse_document(resource.read_text(encoding="utf-8")))
        return cls(lines)

    def lookup(self, provider: str, model: str, at: date) -> PriceLine:
        """Return the price line valid for ``provider``/``model`` on ``at``."""
        try:
            records = self._by_model[(provider, model)]
        except KeyError as exc:
            raise UnknownModelError(
                f"no pricing for provider {provider!r} model {model!r}"
            ) from exc
        valid = [line for line in records if line.valid_from <= at]
        if not valid:
            raise NoPriceForDateError(
                f"no price for {provider!r}/{model!r} on or before {at.isoformat()}"
            )
        return valid[-1]

    def estimate_cost(
        self,
        provider: str,
        model: str,
        usage: TokenUsage,
        at: date,
        *,
        latency_ms: int = 0,
        hourly_rate: Decimal = Decimal("0"),
    ) -> Decimal:
        """Cost in USD for one call, using the price valid on ``at``.

        Local models (``is_local``) are billed by wall-clock time at
        ``hourly_rate`` (default 0); commercial models are billed per token,
        with cached input tokens charged at the cached rate when present.
        """
        line = self.lookup(provider, model, at)
        if line.is_local:
            seconds = Decimal(latency_ms) / _MS_PER_SECOND
            return (seconds / _SECONDS_PER_HOUR) * hourly_rate

        cached = usage.cached_tokens
        non_cached_input = max(usage.prompt_tokens - cached, 0)
        cached_rate = (
            line.input_per_million
            if line.cached_input_per_million is None
            else line.cached_input_per_million
        )
        total = (
            non_cached_input * line.input_per_million
            + cached * cached_rate
            + usage.completion_tokens * line.output_per_million
        )
        return total / _PER_MILLION


@functools.lru_cache(maxsize=1)
def default_pricing() -> PricingTable:
    """Return the process-wide pricing table loaded from packaged data."""
    return PricingTable.load()
