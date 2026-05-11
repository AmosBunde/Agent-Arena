# Database schema

Schema for Agent Arena's Postgres state. All tables live in one Postgres database, separated by schema namespace. See [ADR-0005](../adr/0005-database-architecture.md) for the rationale.

## Schemas

- `catalog` for slow-changing reference data (tasks, rubrics, agents, pricing, tokens, audit).
- `runs` for run-scoped state.
- `traces` for trace metadata (bodies live in object storage).
- `aggregates` for derived data and materialised views.

## Catalog

```sql
CREATE SCHEMA catalog;

CREATE TABLE catalog.tasks (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                  TEXT NOT NULL,
    version               TEXT NOT NULL,
    domain                TEXT NOT NULL,
    definition            JSONB NOT NULL,
    capabilities_required TEXT[] NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    deprecated_at         TIMESTAMPTZ,
    UNIQUE (slug, version)
);
CREATE INDEX tasks_domain_idx ON catalog.tasks (domain);

CREATE TABLE catalog.rubrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT NOT NULL,
    version         TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    definition      JSONB NOT NULL,
    judge_required  BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (slug, version),
    UNIQUE (definition_hash)
);

CREATE TABLE catalog.agents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        TEXT NOT NULL,
    version     TEXT NOT NULL,
    definition  JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (slug, version)
);

CREATE TABLE catalog.providers (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    is_local     BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE catalog.pricing (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    valid_from  DATE NOT NULL,
    valid_to    DATE,
    prices      JSONB NOT NULL,
    source_url  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, model, valid_from)
);
CREATE INDEX pricing_lookup_idx ON catalog.pricing (provider, model, valid_from DESC);

CREATE TABLE catalog.api_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    prefix      TEXT NOT NULL,
    hash        TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('viewer', 'runner', 'admin')),
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ
);
CREATE INDEX api_tokens_prefix_idx ON catalog.api_tokens (prefix);

CREATE TABLE catalog.audit_log (
    id          BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT NOT NULL,
    operation   TEXT NOT NULL,
    resource    TEXT NOT NULL,
    payload     JSONB
);
CREATE INDEX audit_log_occurred_at_idx ON catalog.audit_log (occurred_at DESC);
CREATE INDEX audit_log_resource_idx ON catalog.audit_log (resource);
```

## Runs

```sql
CREATE SCHEMA runs;

CREATE TABLE runs.run_groups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  TEXT NOT NULL
);

CREATE TABLE runs.runs (
    id              UUID PRIMARY KEY,
    run_group_id    UUID REFERENCES runs.run_groups(id),
    agent_id        UUID NOT NULL REFERENCES catalog.agents(id),
    task_id         UUID NOT NULL REFERENCES catalog.tasks(id),
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    rubric_id       UUID NOT NULL REFERENCES catalog.rubrics(id),
    status          TEXT NOT NULL CHECK (status IN (
                        'pending', 'queued', 'running',
                        'complete', 'failed', 'cancelled'
                    )),
    failure_reason  TEXT,
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_by      TEXT NOT NULL
);
CREATE INDEX runs_group_idx    ON runs.runs (run_group_id);
CREATE INDEX runs_status_idx   ON runs.runs (status) WHERE status IN ('pending','queued','running');
CREATE INDEX runs_finished_idx ON runs.runs (finished_at DESC);

CREATE TABLE runs.attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES runs.runs(id) ON DELETE CASCADE,
    attempt_number  INT NOT NULL,
    adapter_version TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    outcome         TEXT NOT NULL CHECK (outcome IN (
                        'success', 'failed_provider_error',
                        'failed_adapter_error', 'failed_timeout',
                        'skipped_unsupported'
                    )),
    UNIQUE (run_id, attempt_number)
);
```

## Traces

```sql
CREATE SCHEMA traces;

CREATE TABLE traces.trace_metadata (
    hash            TEXT PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES runs.runs(id) ON DELETE CASCADE,
    attempt_id      UUID NOT NULL REFERENCES runs.attempts(id) ON DELETE CASCADE,
    body_uri        TEXT NOT NULL,
    body_size_bytes INT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    total_input_tokens   INT NOT NULL DEFAULT 0,
    total_output_tokens  INT NOT NULL DEFAULT 0,
    total_cached_tokens  INT NOT NULL DEFAULT 0,
    estimated_cost_usd   NUMERIC(12, 6) NOT NULL DEFAULT 0,
    latency_ms      INT NOT NULL,
    tool_call_count INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX traces_run_idx        ON traces.trace_metadata (run_id);
CREATE INDEX traces_created_at_idx ON traces.trace_metadata (created_at DESC);
```

## Aggregates

```sql
CREATE SCHEMA aggregates;

CREATE TABLE aggregates.scores (
    trace_hash    TEXT NOT NULL REFERENCES traces.trace_metadata(hash) ON DELETE CASCADE,
    rubric_hash   TEXT NOT NULL,
    score         NUMERIC(6, 4) NOT NULL,
    is_correct    BOOLEAN NOT NULL,
    score_detail  JSONB NOT NULL,
    judge_model   TEXT,
    scored_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trace_hash, rubric_hash)
);
CREATE INDEX scores_rubric_correct_idx ON aggregates.scores (rubric_hash, is_correct);

CREATE MATERIALIZED VIEW aggregates.leaderboard AS
SELECT
    r.agent_id,
    r.task_id,
    r.provider,
    r.model,
    s.rubric_hash,
    COUNT(*) FILTER (WHERE s.is_correct)                              AS correct_count,
    COUNT(*)                                                          AS total_count,
    AVG(s.score)::numeric(6, 4)                                       AS mean_score,
    SUM(t.estimated_cost_usd)::numeric(12, 6)                         AS total_cost_usd,
    CASE WHEN COUNT(*) FILTER (WHERE s.is_correct) = 0
         THEN NULL
         ELSE (SUM(t.estimated_cost_usd) /
               COUNT(*) FILTER (WHERE s.is_correct))::numeric(12, 6)
    END                                                               AS cost_per_correct_usd,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY t.latency_ms)        AS p50_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY t.latency_ms)        AS p95_latency_ms
FROM runs.runs r
JOIN runs.attempts a            ON a.run_id      = r.id
JOIN traces.trace_metadata t    ON t.attempt_id  = a.id
JOIN aggregates.scores s        ON s.trace_hash  = t.hash
WHERE r.status = 'complete'
GROUP BY r.agent_id, r.task_id, r.provider, r.model, s.rubric_hash;

CREATE UNIQUE INDEX leaderboard_pk_idx
    ON aggregates.leaderboard (agent_id, task_id, provider, model, rubric_hash);
```

## Migration approach

Alembic for schema migrations. Migrations are append-only in main; schema changes that require column drops use the expand-contract pattern over two releases (expand in version N, contract in version N+1). The migration runner is part of the API container's entrypoint, gated by an env flag to allow controlled rollout in production.

## Sizing notes

At one million traces:

- `traces.trace_metadata` ~250 MB, comfortable on any modest Postgres instance.
- `aggregates.scores` ~150 MB per rubric, multiple rubrics scale linearly.
- `runs.runs` ~100 MB.
- Materialised view ~50 MB.

Object storage for trace bodies: dominant cost. At average 50 KB per body, one million traces is 50 GB. Use S3 lifecycle policies to move old traces to infrequent-access tier after 90 days.

## See also

- [ADR-0003](../adr/0003-content-addressed-trace-store.md) for trace store decisions.
- [ADR-0005](../adr/0005-database-architecture.md) for the single-DB choice.
- [System design](system-design.md) for the broader picture.
