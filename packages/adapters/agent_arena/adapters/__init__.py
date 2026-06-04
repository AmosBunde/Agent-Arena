"""Provider adapter layer for Agent Arena.

The ``AgentAdapter`` protocol and value types live in :mod:`.base`; the central
registry lives in :mod:`.registry`. See docs/adr/0002-provider-adapter-pattern.md.
"""

from __future__ import annotations

from agent_arena.adapters.base import (
    AdapterError,
    AdapterProtocolError,
    AdapterResponse,
    AgentAdapter,
    Capability,
    DuplicateAdapterError,
    Message,
    Role,
    TokenUsage,
    Tool,
    ToolCall,
    UnknownProviderError,
    missing_capabilities,
    supports,
)
from agent_arena.adapters.registry import (
    AdapterFactory,
    AdapterRegistry,
    available_providers,
    default_registry,
    get_adapter,
    register,
)

__all__ = [
    "AdapterError",
    "AdapterFactory",
    "AdapterProtocolError",
    "AdapterRegistry",
    "AdapterResponse",
    "AgentAdapter",
    "Capability",
    "DuplicateAdapterError",
    "Message",
    "Role",
    "TokenUsage",
    "Tool",
    "ToolCall",
    "UnknownProviderError",
    "available_providers",
    "default_registry",
    "get_adapter",
    "missing_capabilities",
    "register",
    "supports",
]
