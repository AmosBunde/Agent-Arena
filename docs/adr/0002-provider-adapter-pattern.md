# ADR-0002: Provider adapter pattern

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** Core maintainers

## Context

The core value proposition of Agent Arena is comparing agents across LLM providers on equal terms. This is impossible if the runner is coupled to any single provider's SDK or if provider-specific quirks leak into agent code. The adapter layer is the load-bearing abstraction for the entire project.

The naive approach is "we use LangChain or LiteLLM, which already abstract providers." This was rejected for three reasons. First, LangChain's abstraction is leaky in exactly the dimensions Agent Arena cares about (token accounting, retry semantics, structured tool calls). Second, LiteLLM is a proxy, which adds a network hop and an operational dependency for a benchmarking tool that needs deterministic timing. Third, depending on a third-party abstraction means the project's most important interface is owned by someone else.

The adapter must support, at minimum:

- Chat completion with system, user, and assistant turns.
- Tool calling with structured JSON outputs.
- Streaming for latency measurement.
- Token-level usage reporting (prompt tokens, completion tokens, cached tokens where applicable).
- Provider-specific cost calculation from usage and current pricing.
- Graceful degradation when a feature is not supported (capability negotiation).

## Decision

A single Python protocol `AgentAdapter` defines the interface, with one concrete implementation per provider. Adapters are registered in a central registry indexed by provider name and model identifier. Capability negotiation is explicit through a `capabilities()` method that returns a frozen set of supported features.

```python
class AgentAdapter(Protocol):
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
```

The runner queries `capabilities()` before dispatching a task. If a task requires tool calling and the adapter does not support it, the run is marked `skipped_unsupported` rather than failed. This makes the leaderboard honest: a model that cannot do tool calling does not score zero on a tool-calling task, it does not appear in that task's ranking.

Token usage is normalised across providers into a single `TokenUsage` schema. Each adapter is responsible for translating provider-specific usage objects into this schema. Cost calculation reads from versioned pricing data in `packages/cost-models/`; see ADR-0004.

## Consequences

### Positive

Adding a provider is a contained change: one adapter file, one pricing data file, one entry in the registry, one test. The interface is small enough that contributors can add new providers without understanding the rest of the codebase.

Provider-specific quirks are isolated. The Anthropic adapter handles Anthropic's tool-use schema; the OpenAI adapter handles OpenAI's. The runner code calls `adapter.chat(...)` and is provider-agnostic by construction.

Capability negotiation makes feature support explicit. The leaderboard can be filtered by required capabilities, and skipped runs are distinct from failed runs in the database and in the UI.

### Negative

The adapter interface is a moving target. New provider features (extended thinking, prompt caching, batched calls) require interface updates, which require updating every existing adapter. The mitigation is a strict policy: interface changes go through an ADR amendment and a deprecation window of at least one minor version.

Some genuine provider features cannot be exposed through a uniform interface without losing information. The escape hatch is `AdapterResponse.provider_metadata`, a free-form dict for provider-specific fields. This is a leak, deliberately scoped. Consumers that touch `provider_metadata` are expected to handle the case where the field is missing or has different shape across providers.

### Neutral

The protocol is enforced at runtime via a registration check, not via static typing alone. This is a tradeoff: the Python type system's protocol support is good enough for IDE help but not strict enough to catch every interface violation at import time.

## Alternatives considered

**LangChain as the abstraction.** Rejected. The abstraction is too broad (covers chains, agents, retrievers, memory, callbacks) and leaks provider quirks in the dimensions we care about. Token accounting in particular is inconsistent across LangChain provider integrations.

**LiteLLM proxy.** Rejected as the primary integration, accepted as an optional adapter. A proxy adds a network hop and an operational dependency. The optional adapter exists for users who already run a LiteLLM proxy and want to route Agent Arena through it.

**OpenAI-compatible interface for everything.** Rejected. Forcing Anthropic, Google, and Bedrock into an OpenAI-shaped interface throws away the genuine semantic differences (Anthropic's system prompt placement, Google's safety settings, Bedrock's model-specific request shapes) and produces a lowest-common-denominator interface.

## References

- LangChain provider integrations: https://python.langchain.com/docs/integrations/providers/
- LiteLLM: https://github.com/BerriAI/litellm
- The Python typing.Protocol specification: PEP 544

## Amendment: 2026-06-04

**Change.** Added a `PROMPT_CACHING` member to the `Capability` enum.

**Rationale.** The original decision named prompt caching as a feature that adapters would eventually expose and that capability negotiation should cover. The Anthropic adapter (issue #5) records cache-read tokens separately and bills them at the cached rate, so it advertises `PROMPT_CACHING`; adapters without it simply do not report it. The runner can therefore filter or annotate runs by caching support.

**Consequences.** The addition is backward compatible: it is a new enum value, not a change to any method signature, so existing adapters and callers are unaffected. No deprecation window is required. Capabilities remain a frozen set returned per adapter instance; nothing about the negotiation contract changes.

## Revision history

- 2026-05-11: Initial decision recorded.
- 2026-06-04: Added `PROMPT_CACHING` capability (see amendment above).
