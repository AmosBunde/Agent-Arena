# System design

This document describes how Agent Arena is put together. It is intended for contributors and for anyone evaluating whether the architecture is fit for their use case.

## Goals and non-goals

**Goals.** Agent Arena exists to compare LLM agents on equal terms across providers, with cost and latency as first-class metrics, and with results that remain reproducible months after they were generated. The system should be deployable in five minutes by a single developer on a 20 USD per month VM, and should scale through a documented path to multi-region Kubernetes for teams that need it.

**Non-goals.** Real-time observability for production agents (use Langfuse or Phoenix). Training or fine-tuning (use the appropriate frameworks). Red-team and safety-specific evaluation (use Inspect AI). Multi-tenant SaaS hosting.

## Architectural style

The system is a small set of long-running services that communicate through a database, a queue, and a shared object store. There is no service mesh, no microservice fan-out, no event-sourcing. The choice is deliberate: a benchmarking tool is not a request-response product, and adding distributed-systems complexity costs reproducibility without buying anything.

The services are:

- **API.** FastAPI application serving the REST API consumed by the web UI and by external clients. Stateless, horizontally scalable when needed.
- **Web.** React frontend, served as static assets from the API container or from a CDN in production.
- **Runner.** Celery worker that consumes run jobs from Redis, invokes the appropriate adapter, captures traces, writes results. Horizontally scalable by replica count.
- **Scheduler.** Periodic refresh of materialised views, cleanup of stale runs, pricing data validation. Single instance, idempotent.

State lives in:

- **Postgres.** Catalog, run state, trace metadata, score aggregates.
- **Object store.** Trace bodies (canonical JSON, content-addressed).
- **Redis.** Celery task queue, leaderboard cache, rate-limit counters. No durable state.

## Request lifecycle

A typical "run agent X on task Y across providers P1 and P2" flow:

1. Web client posts to `POST /runs` with `{agent_id, task_id, providers: [P1, P2], rubric_id}`.
2. API validates the request, creates a `runs.runs` row in `pending`, enqueues one Celery job per provider, returns the run ID.
3. Runner picks up the job, instantiates the adapter for the provider, fetches the agent and task definitions, executes the agent loop.
4. Each LLM call captures: full request, full response, token usage, wall-clock latency. Tool calls and their results are captured similarly.
5. On completion, the runner serialises the trace to canonical JSON, computes its SHA-256, writes the body to the object store, writes metadata to `traces.trace_metadata`.
6. The scoring pipeline applies the rubric to produce a row in `aggregates.scores`. For deterministic rubrics this is synchronous; for LLM-judge rubrics it is a follow-up Celery task.
7. The run is marked `complete`. The leaderboard view picks up the new score on its next refresh.

For replay-only re-scoring under a new rubric, steps 3 through 5 are skipped: the runner reads the existing trace body, runs the rubric, writes a new score row keyed by `(trace_hash, rubric_hash)`. No LLM calls.

## Concurrency model

Runner concurrency is set per deployment via Celery worker concurrency. The default Compose deployment runs four runner workers. Each worker processes one agent run at a time; concurrency comes from running multiple workers, not from within-worker async.

Why not within-worker async? Two reasons. First, agent runs are CPU-modest but capture a lot of state; serial processing per worker keeps memory bounded. Second, async failures inside Celery tasks have historically been a debugging nightmare; sync code with multiple workers is easier to reason about.

The API service is async (FastAPI's default). API requests do no LLM work; they enqueue jobs and serve cached aggregates. Async is the right model there.

## Failure handling

LLM calls are retried with exponential backoff inside the adapter (default three attempts, configurable). Provider rate limits surface as a specific exception type and trigger a longer backoff. After max retries, the attempt is marked `failed_provider_error` with the error captured in the trace. The run can continue with other providers; one provider failing does not fail the whole run.

Adapter bugs surface as `failed_adapter_error` and are escalated: the run is marked failed, no partial trace is written (because partial traces would corrupt the deduplication property), and the error is logged with full stack trace.

Runner crashes mid-run are handled by Celery's visibility timeout. A run job that exceeds the timeout is requeued; the runner is responsible for idempotent restart. Idempotency is achieved by checking whether a trace already exists for the run before starting; if so, the run is marked `complete` from cache.

## Observability

The project ships with structured logging (JSON to stdout), Prometheus metrics on `/metrics`, and OpenTelemetry traces emitted to an optional collector. None of these are required for the project to function; all are off by default in Compose and on by default in K8s.

The principle is that operators of the project should be able to observe it, but the project should not require an observability stack to run.

## Security

Provider API keys live in environment variables loaded into the runner. They are never written to the database, never logged, never exposed in API responses. The trace canonicalisation explicitly strips authorization headers.

The web UI is unauthenticated by default in Compose (single-user local tool). The K8s deployment expects an authentication proxy (OAuth2 Proxy, Cloudflare Access, or similar) in front of the API; the project does not implement its own auth in v0.1 because every deployment context has its own auth requirements.

PII handling: Agent Arena does not collect PII as part of its core function. Tasks and rubrics are public artifacts; runs are scoped to a single deployment. The recommendation in the docs is to not put PII in tasks.

## Scaling path

The canonical Compose deployment supports up to roughly four concurrent runner workers on a 4 vCPU 8 GB instance, which is several hundred runs per day depending on agent complexity. Past that:

1. Add more runner workers, vertical-scale the VM.
2. Move Postgres to a managed external service.
3. Move Redis to a managed external service.
4. Migrate to Kubernetes for horizontal runner scaling.
5. Partition `traces.trace_metadata` and `aggregates.scores` by created_at month.
6. Add read replicas for the API service.

Steps 1 through 3 are mechanical. Step 4 is documented in [docs/deployment/kubernetes.md](../deployment/kubernetes.md). Steps 5 and 6 are uncommon enough that they are not pre-built.

## See also

- [Session design](session-design.md) for how user-facing state flows through the API.
- [Database schema](database-schema.md) for the full schema definition.
- [ADR-0001](../adr/0001-deployment-topology.md) for the deployment choice.
- [ADR-0002](../adr/0002-provider-adapter-pattern.md) for the adapter interface.
- [ADR-0003](../adr/0003-content-addressed-trace-store.md) for trace storage.
