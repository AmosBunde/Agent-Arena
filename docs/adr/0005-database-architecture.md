# ADR-0005: Database architecture

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** Core maintainers

## Context

The state Agent Arena needs to persist falls into five categories:

1. **Catalog data:** Tasks, rubrics, agents, providers, pricing. Slow-changing, read-heavy.
2. **Run state:** Run metadata, status, timing. Write-once for most fields, updated for status transitions.
3. **Trace metadata:** Hash, run association, indexed fields for lookup. Write-once, content-addressed.
4. **Trace bodies:** Canonical JSON. Large, immutable, written to object storage rather than the database (see ADR-0003).
5. **Aggregates and leaderboards:** Computed views over runs and traces. Refreshed on schedule or on demand.

The temptation is to reach for a polyglot setup early: Postgres for catalog, Clickhouse for aggregates, Elasticsearch for trace search, vector DB for embedding-based task similarity. This is the wrong move for a v0.1 of a single-VM project. Operational surface area kills self-hosted tools.

## Decision

**One Postgres 16 instance for all relational state.** No sharding, no read replicas in the canonical deployment, no service-per-database split. Logical separation through schemas: `catalog`, `runs`, `traces`, `aggregates`. The K8s deployment supports external managed Postgres but uses the same schema.

**Object storage for trace bodies.** MinIO in Compose, any S3-compatible store in K8s. See ADR-0003.

**Redis for queues and short-lived state.** Celery task queue, leaderboard cache with TTL, rate-limit counters. No persistent state in Redis; it can be wiped without data loss.

**Materialised views for leaderboards.** Not application-side caching, not a separate analytics DB. Postgres materialised views refreshed by a scheduled job; the leaderboard query reads the view, not the underlying tables.

**No vector database in v0.1.** Task similarity is computed at task-author time and stored as edges in a Postgres table. If this proves inadequate, pgvector is the upgrade path; a separate vector DB is not.

## Schema overview

```
catalog.tasks         (id, slug, version, definition_yaml, capabilities_required, ...)
catalog.rubrics       (id, slug, version, definition_yaml, judge_required, ...)
catalog.agents        (id, slug, version, definition_yaml, ...)
catalog.providers     (id, name, ...)
catalog.pricing       (id, provider, model, valid_from, prices_jsonb, ...)

runs.runs             (id, agent_id, task_id, status, started_at, finished_at, ...)
runs.attempts         (id, run_id, attempt_number, adapter_version, ...)

traces.trace_metadata (hash PK, run_id, attempt_id, body_uri, created_at, ...)

aggregates.scores              (trace_hash, rubric_hash, score, score_detail_jsonb, ...)
aggregates.leaderboard_view    (materialised, refreshed every 5 minutes)
```

Full schema in [docs/design/database-schema.md](../design/database-schema.md).

## Consequences

### Positive

One database to back up, monitor, and tune. New contributors do not need to learn multiple data systems to be productive. The operational documentation has one section, not five.

Postgres is more than capable of the load. At the v0.1 target scale (one million traces, ten million scores, hundred thousand runs), a single Postgres instance on modest hardware is not stressed. The bottleneck is the LLM API rate limits, not the database.

Migration paths are clear when needed. Read replicas via streaming replication when read load grows. Partitioning of `traces.trace_metadata` and `aggregates.scores` by `created_at` when individual tables exceed comfortable size. pgvector when vector search is actually needed.

### Negative

Postgres is a single point of failure in the canonical deployment. Mitigated by the K8s migration path documented in ADR-0001 and by the trace store being separate (so Postgres outage does not corrupt traces, only makes them temporarily unfindable).

Materialised view refresh adds latency to leaderboard updates. The default refresh interval is five minutes; users who need real-time leaderboards can refresh manually via a UI button or an API endpoint. The tradeoff is acceptable because leaderboards are read orders of magnitude more often than they need to be perfectly fresh.

JSON-in-Postgres for some fields (task definitions, rubric definitions, score details) means schema evolution is the application's job, not the database's. This is fine for the fields where JSON is used (which have legitimately variable shape) but is a discipline to maintain.

### Neutral

The choice forecloses some optimisations that a purpose-built analytics database would enable (Clickhouse-style columnar aggregates over hundreds of millions of rows). At the project's intended scale this does not matter. At a scale where it would matter, the project has different problems to solve first.

## Alternatives considered

**Postgres + Clickhouse split.** Rejected for v0.1. Doubles operational complexity for a problem we do not yet have.

**Single Postgres database with no schema separation.** Rejected. Schema separation is cheap and makes future service splits possible without renaming.

**SQLite for the canonical deployment.** Rejected. SQLite is excellent for embedded use but does not handle concurrent writers from multiple worker processes well, and the runner is intentionally concurrent.

## Revision history

- 2026-05-11: Initial decision recorded.
