# ADR-0003: Content-addressed trace store

**Status:** Accepted (target M2)
**Date:** 2026-05-11
**Deciders:** Core maintainers

## Context

Deterministic replay is one of the three differentiators of Agent Arena. The promise is that a benchmark run from six months ago can be re-scored under a new rubric without re-spending tokens. This requires that every interaction with a provider, every tool call, and every intermediate state be captured in a form that is stable, identifiable, and addressable.

The hard requirements are:

- A trace must uniquely identify the agent, the task, the rubric version, the adapter version, and the timestamp.
- Two identical traces (same inputs, same model, same parameters, same tool outputs) must hash to the same identifier. This makes deduplication and audit trivial.
- A trace must be re-scoreable. The scoring pipeline can be re-run against the trace without invoking any LLM.
- Storage must scale to at least one million traces on a single VM without falling over.

The temptation is to store traces as freeform JSON in Postgres, indexed by run_id. This was rejected because it makes the deduplication and re-scoring properties hard to enforce. The deeper temptation is to use a third-party trace tool like Langfuse or Phoenix. This was rejected because those tools optimise for observability, not for benchmark reproducibility. Their schemas evolve, and a trace captured today may not be re-readable in twelve months.

## Decision

Traces are stored content-addressed by the SHA-256 hash of their canonical JSON form. The trace store has two tiers:

1. **Metadata in Postgres.** A `traces` table holds `trace_hash` (primary key), `run_id`, `agent_id`, `task_id`, `adapter_version`, `created_at`, and indexed columns for common queries.
2. **Trace bodies in an object store.** The canonical JSON body is written to `s3://...` or a local filesystem path under `data/traces/{hash[:2]}/{hash}.json`. The Compose deployment uses MinIO; the K8s deployment can use any S3-compatible store.

Canonical JSON form means: sorted keys, no whitespace, UTF-8 encoded, with floating-point numbers rendered through a stable serialiser. This is the only way to guarantee that two structurally identical traces hash to the same value. The canonicalisation rules are defined in `packages/schemas/trace_canonical.py` and are versioned with their own ADR amendment process.

Re-scoring is implemented as a pure function: `score(trace_body, rubric_version) -> Result`. The rubric is itself versioned and content-addressed. A `(trace_hash, rubric_hash)` pair uniquely identifies a score, which means the same trace scored under three different rubrics produces three separate score rows, all reproducible.

## Consequences

### Positive

Reproducibility becomes a property of the system, not a discipline. Two researchers running the same benchmark with the same providers will produce traces with the same hashes for deterministic operations, which makes cross-team validation possible.

Longitudinal benchmarking works. A trace captured in M2 can be re-scored in M5 under a new rubric without re-running the agent. This is the property that makes contamination analysis and rubric evolution tractable.

The storage tier is replaceable. MinIO for the default deployment, S3 for K8s, GCS for whoever wants it. The metadata tier stays in Postgres; the trace bodies are commodity.

### Negative

Canonical JSON serialisation is harder than it looks. Floating-point determinism across platforms, integer vs float ambiguity in JSON, key ordering in nested objects, and Unicode normalisation all have edge cases. The schema package owns this complexity, and the test suite includes a battery of canonicalisation property tests.

Re-scoring is only deterministic if the rubric itself is deterministic. Rubrics that call an LLM judge are non-deterministic by nature. The mitigation is that LLM-judge rubrics are explicitly marked, and their scores are stored with the judge model and temperature so that a "re-score under judge model X at temperature 0" can be reproduced approximately, with explicit caveats in the UI.

The trace bodies can be large. A long agent run with many tool calls can produce tens of KB to MB of JSON per trace. At one million traces, that is hundreds of GB. The default Compose deployment uses a local volume; this is fine for the intended scale. Production deployments use S3 with lifecycle policies; documented in [docs/deployment/storage.md](../deployment/storage.md).

### Neutral

Content addressing means traces cannot be edited. If a bug is discovered in trace capture, the fix produces new traces with new hashes; old traces remain as historical record. This is the right behaviour for a benchmark tool but is unfamiliar for engineers used to mutable observability data.

## Alternatives considered

**JSON in Postgres only.** Rejected. Cannot scale to millions of traces in a single table without partitioning, and partitioning by trace hash defeats the purpose since queries are by run or task.

**Langfuse or Phoenix as the trace store.** Rejected. Their schemas optimise for observability, evolve frequently, and offer no canonicalisation guarantee. They are excellent tools for a different problem.

**Parquet on object storage.** Considered for analytical queries. Will be added as a derived export in M4 for cohort-level analysis, but the primary store remains JSON for individual trace fidelity.

## Revision history

- 2026-05-11: Initial decision recorded.
