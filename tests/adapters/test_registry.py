"""Unit tests for the adapter registry."""

from __future__ import annotations

from decimal import Decimal

import pytest
from agent_arena.adapters import (
    AdapterProtocolError,
    AdapterRegistry,
    AgentAdapter,
    Capability,
    DuplicateAdapterError,
    TokenUsage,
    UnknownProviderError,
    register,
)
from agent_arena.adapters.base import AdapterResponse, Message, Tool
from agent_arena.adapters.registry import default_registry


class GoodAdapter:
    def __init__(self, model: str) -> None:
        self.provider = "good"
        self.model = model

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.CHAT})

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse:
        return AdapterResponse(
            provider=self.provider,
            model=self.model,
            content=None,
            usage=TokenUsage(),
            latency_ms=0,
        )

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        return Decimal("0")


class MissingMethod:
    """Has no ``chat`` method, so it must be rejected at registration."""

    def capabilities(self) -> frozenset[Capability]:
        return frozenset()

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        return Decimal("0")


class MissingInstanceAttrs:
    """Passes the method check but never sets provider/model on instances."""

    def __init__(self, model: str) -> None:
        pass

    def capabilities(self) -> frozenset[Capability]:
        return frozenset()

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = False,
        temperature: float | None = None,
    ) -> AdapterResponse:
        return AdapterResponse(
            provider="x", model="x", content=None, usage=TokenUsage(), latency_ms=0
        )

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        return Decimal("0")


def test_register_and_get_adapter() -> None:
    reg = AdapterRegistry()
    reg.register("good", GoodAdapter)
    adapter = reg.get_adapter("good", "model-1")
    assert isinstance(adapter, AgentAdapter)
    assert adapter.provider == "good"
    assert adapter.model == "model-1"
    assert reg.available_providers() == frozenset({"good"})


def test_duplicate_registration_rejected() -> None:
    reg = AdapterRegistry()
    reg.register("good", GoodAdapter)
    with pytest.raises(DuplicateAdapterError):
        reg.register("good", GoodAdapter)
    # replace=True overrides without error.
    reg.register("good", GoodAdapter, replace=True)


def test_unknown_provider_rejected() -> None:
    reg = AdapterRegistry()
    with pytest.raises(UnknownProviderError):
        reg.get_adapter("nope", "m")
    with pytest.raises(UnknownProviderError):
        reg.unregister("nope")


def test_factory_missing_method_rejected_at_registration() -> None:
    reg = AdapterRegistry()
    with pytest.raises(AdapterProtocolError):
        reg.register("bad", MissingMethod)


def test_instance_not_satisfying_protocol_rejected() -> None:
    reg = AdapterRegistry()
    reg.register("bad", MissingInstanceAttrs)
    with pytest.raises(AdapterProtocolError):
        reg.get_adapter("bad", "m")


def test_unregister() -> None:
    reg = AdapterRegistry()
    reg.register("good", GoodAdapter)
    assert reg.is_registered("good")
    reg.unregister("good")
    assert not reg.is_registered("good")


def test_register_decorator_uses_given_registry() -> None:
    reg = AdapterRegistry()

    @register("good", registry=reg)
    class Decorated(GoodAdapter):
        pass

    assert reg.is_registered("good")
    assert isinstance(reg.get_adapter("good", "m"), AgentAdapter)
    # The default registry is untouched by a scoped registration.
    assert "good" not in default_registry().available_providers()
