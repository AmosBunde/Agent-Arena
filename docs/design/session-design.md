# Session design

This document describes how user sessions, API authentication, and run-scoped state are handled. Read [system-design.md](system-design.md) first.

## What a session is in Agent Arena

Agent Arena has two distinct notions of session, and they are deliberately kept separate:

1. **User session.** The authenticated context of a human or service interacting with the API. Concerns: who is making the request, what they are allowed to do, how long their credentials are valid.
2. **Run session.** The execution context of a single agent run against a task. Concerns: the agent's state across turns, the conversation history with the provider, tool-call state, the running trace under construction.

Confusing these is a common source of bugs in agent platforms. The user session has nothing to say about agent memory; the run session has nothing to say about authentication.

## User session

### Compose deployment (default)

The Compose deployment is a single-tenant local tool. There is no user session. The API has no authentication. The web UI binds to localhost. This is a deliberate choice for v0.1: deployments that need authentication are expected to run an auth proxy in front.

The trade is that running Agent Arena on a public IP without an auth proxy exposes every API endpoint to anyone who can reach it. The documentation is explicit about this; the default `docker-compose.yml` binds the API to `127.0.0.1`, not `0.0.0.0`.

### Production deployment (auth proxy assumed)

In K8s, the API is expected to sit behind one of:

- OAuth2 Proxy with an upstream IdP (Google Workspace, Okta, GitHub).
- Cloudflare Access or AWS ALB authentication.
- A reverse proxy with basic auth for low-stakes deployments.

The API trusts a `X-Forwarded-User` header set by the proxy. There is no session token, no JWT validation, no login flow in the API itself. The proxy owns identity; the API owns authorisation.

Why not implement auth in the API? Because every deployment has different requirements (SSO provider, MFA policy, audit logging), and an in-process auth implementation would inevitably be wrong for most of them. Delegating to a proxy is the right boundary for an infrastructure tool.

### Authorisation model

Three roles, encoded as values of `X-Forwarded-User-Role`:

- `viewer`: read-only access to runs, leaderboards, tasks, rubrics.
- `runner`: viewer plus ability to create new runs and re-score existing traces.
- `admin`: runner plus ability to register agents, edit tasks and rubrics, manage pricing data.

The default role when no header is present is `admin` in Compose (single-user local) and `viewer` in K8s (fail-safe).

### API tokens for programmatic access

For CI pipelines and scripted use, the API supports long-lived bearer tokens stored in `catalog.api_tokens`. Tokens are hashed at rest (Argon2id), are scoped to a role, and have an optional expiry. Tokens are created through the UI by an admin and shown once at creation; thereafter only their prefix is visible.

This is the only auth primitive Agent Arena implements directly. It exists because CI pipelines cannot easily authenticate through an interactive OAuth flow.

## Run session

### Lifecycle

A run session is created when a `POST /runs` request is accepted. Its lifecycle:

```
pending → queued → running → (complete | failed | cancelled)
```

State transitions are recorded with timestamps. Only `running` allows further state to accumulate; the other states are terminal except for `pending → cancelled` (user cancellation before pickup) and `queued → cancelled` (user cancellation while waiting).

The run session ID is a UUIDv7. UUIDv7 over UUIDv4 because v7 sorts by creation time, which makes pagination and recent-runs queries cheap without needing a separate `created_at` index lookup.

### Agent memory within a run

The agent loop maintains an in-process conversation buffer for the duration of a single run. This buffer is not persisted directly; it is persisted indirectly through the trace, which captures every prompt and response.

Cross-run memory is not a supported feature in v0.1. An agent that needs persistent memory across runs is a different problem (and probably a different tool) than what Agent Arena evaluates. The benchmarking framing assumes each run is independent so that comparisons are well-defined.

### Concurrency within a run

A single run executes serially within one runner worker. The agent's tool-call loop is sequential. Parallelism across providers (the common case of "run agent X on task Y across P1 and P2") is achieved by enqueuing separate runs, one per provider, all sharing a parent `run_group_id`. The leaderboard groups them.

This is simpler than implementing internal parallelism and produces traces that are easier to reason about. The cost is that runs are not parallelised across providers within a single worker; the mitigation is to scale runner replicas, which is cheap.

### Cancellation

Cancellation is cooperative. A `DELETE /runs/{id}` sets a cancel flag in Redis. The runner checks the flag between tool calls and aborts cleanly if set. There is no preemption; a run inside a slow LLM call cannot be killed mid-call without losing the trace, so cancellation waits for the next checkpoint.

Hard timeouts are enforced at the Celery level (default ten minutes per run, configurable). A run that exceeds the timeout is forcibly killed; the trace is marked `failed_timeout` and partial state is discarded.

## Caching

Two caches are surfaced to the user:

- **Leaderboard cache.** The materialised view in Postgres is refreshed every five minutes. The API caches the rendered leaderboard JSON in Redis with the same TTL. A `?refresh=true` query parameter bypasses both caches and triggers an immediate refresh.
- **Trace cache.** Trace bodies fetched from object storage are cached in the API process memory with LRU eviction. The cache is keyed by trace hash and is safe because trace bodies are immutable.

No client-side session caching is specified; the web UI uses TanStack Query with conservative stale times.

## Audit trail

Every state-changing operation (run creation, cancellation, agent registration, rubric edits) writes a row to `catalog.audit_log` with the user identity (from the auth proxy header), the operation, the affected resource, and the request payload. The audit log is append-only and is retained indefinitely in the default deployment; operators can configure a retention policy.

The audit log is not a security feature on its own. It is a forensics tool for understanding why a benchmark result looks the way it does, which is a recurring question in evaluation work.

## See also

- [System design](system-design.md) for the broader architecture.
- [Database schema](database-schema.md) for `catalog.api_tokens` and `catalog.audit_log` definitions.
- [docs/deployment/kubernetes.md](../deployment/kubernetes.md) for the auth proxy setup.
