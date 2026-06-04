"""Central adapter registry.

Adapters are registered per provider name; ``get_adapter(provider, model)``
instantiates the provider's adapter for a specific model. Registration is
validated at runtime against the ``AgentAdapter`` protocol (ADR-0002).
"""

from __future__ import annotations

from collections.abc import Callable

from agent_arena.adapters.base import (
    AdapterProtocolError,
    AgentAdapter,
    DuplicateAdapterError,
    UnknownProviderError,
)

# A factory takes a model identifier (and optional adapter-specific kwargs) and
# returns a ready adapter instance. Provider adapter classes satisfy this.
AdapterFactory = Callable[..., AgentAdapter]

# Methods the protocol requires; checked at registration time, before any
# instance exists. The data attributes (provider, model) are verified on the
# instance in get_adapter via isinstance.
_REQUIRED_METHODS = ("capabilities", "chat", "estimate_cost")


class AdapterRegistry:
    """A mutable mapping of provider name to adapter factory."""

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, provider: str, factory: AdapterFactory, *, replace: bool = False) -> None:
        """Register ``factory`` under ``provider``.

        Raises ``DuplicateAdapterError`` if the provider is already registered
        and ``replace`` is false, and ``AdapterProtocolError`` if the factory
        clearly cannot produce an ``AgentAdapter``.
        """
        if not replace and provider in self._factories:
            raise DuplicateAdapterError(f"adapter already registered for provider {provider!r}")
        for method in _REQUIRED_METHODS:
            if not callable(getattr(factory, method, None)):
                raise AdapterProtocolError(
                    f"factory {factory!r} for provider {provider!r} is missing "
                    f"required method {method!r}"
                )
        self._factories[provider] = factory

    def get_adapter(self, provider: str, model: str, **kwargs: object) -> AgentAdapter:
        """Instantiate the adapter for ``provider`` and ``model``."""
        try:
            factory = self._factories[provider]
        except KeyError as exc:
            raise UnknownProviderError(f"no adapter registered for provider {provider!r}") from exc
        adapter = factory(model=model, **kwargs)
        if not isinstance(adapter, AgentAdapter):
            raise AdapterProtocolError(
                f"adapter for provider {provider!r} does not satisfy AgentAdapter"
            )
        return adapter

    def available_providers(self) -> frozenset[str]:
        """Return the set of registered provider names."""
        return frozenset(self._factories)

    def is_registered(self, provider: str) -> bool:
        return provider in self._factories

    def unregister(self, provider: str) -> None:
        """Remove a provider. Raises ``UnknownProviderError`` if absent."""
        try:
            del self._factories[provider]
        except KeyError as exc:
            raise UnknownProviderError(f"no adapter registered for provider {provider!r}") from exc


# The process-wide default registry that provider adapters register into.
_DEFAULT_REGISTRY = AdapterRegistry()


def register(
    provider: str, *, registry: AdapterRegistry | None = None, replace: bool = False
) -> Callable[[type], type]:
    """Class decorator registering an adapter class for ``provider``.

    Usage::

        @register("openai")
        class OpenAIAdapter:
            ...
    """
    target = registry or _DEFAULT_REGISTRY

    def decorator(cls: type) -> type:
        target.register(provider, cls, replace=replace)
        return cls

    return decorator


def get_adapter(provider: str, model: str, **kwargs: object) -> AgentAdapter:
    """Instantiate an adapter from the default registry."""
    return _DEFAULT_REGISTRY.get_adapter(provider, model, **kwargs)


def available_providers() -> frozenset[str]:
    """Return the providers registered in the default registry."""
    return _DEFAULT_REGISTRY.available_providers()


def default_registry() -> AdapterRegistry:
    """Return the process-wide default registry."""
    return _DEFAULT_REGISTRY


__all__ = [
    "AdapterFactory",
    "AdapterRegistry",
    "available_providers",
    "default_registry",
    "get_adapter",
    "register",
]
