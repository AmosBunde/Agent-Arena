# Changelog

## v1.0.0 (2026-07-06)

The first release with the stability guarantee documented in
[docs/STABILITY.md](docs/STABILITY.md). Everything below was delivered
across milestones M1 to M5.

### Foundation and core loop (M1)

- Postgres schema with Alembic migrations across the catalog, runs,
  traces, and aggregates namespaces.
- Provider adapter protocol with capability negotiation and adapters for
  OpenAI, Anthropic, Google, and Ollama.
- Versioned pricing data and Decimal cost computation; cost-per-correct-
  answer as the leaderboard metric, NULL when nothing is correct.
- Celery runner with a sequential agent loop, deterministic built-in
  tools, idempotent restart, cooperative cancellation, and stale run
  repair.
- FastAPI service with the /api/v1 surface, role-based authorisation, and
  audit logging; React UI with tasks, run creation, and the leaderboard.
- Single VM Docker Compose deployment with health checks on every
  service; CI with lint, type, test, and smoke deployment gates.
- Example task and rubric library with a quickstart walkthrough.

### Deterministic replay and the trace store (M2)

- Canonical JSON serialisation with property-tested determinism.
- Content-addressed trace store with local filesystem and S3
  implementations; MinIO in Compose.
- Idempotent re-scoring of stored traces with no LLM calls; trace browser
  UI with a per-call timeline and a re-score control.
- LLM-judge rubrics as follow-up jobs, with judge cost recorded apart from
  run cost.

### Provider expansion and statistical rigour (M3)

- AWS Bedrock adapter through the Converse API and a vLLM adapter for
  OpenAI-compatible endpoints with latency-based local cost.
- Percentile bootstrap confidence intervals on every leaderboard cell,
  computed by a scheduled job.
- Pareto front view over cost and accuracy with dominated points dimmed.
- Contamination analysis tooling with a per-task catalog flag.

### Operational maturity (M4)

- Kubernetes Helm chart with external service values, a migration Job
  hook, runner autoscaling, and a kind smoke suite in CI.
- Terraform modules for AWS, GCP, and DigitalOcean provisioning managed
  Postgres, Redis, object storage, and the Compose VM.
- Prometheus metrics on the api and runner and env-controlled
  OpenTelemetry tracing.
- Backup and restore tooling with a proven round trip.
- API tokens hashed with Argon2id, shown once, revocable immediately, and
  manageable from the UI.

### Community and stability (M5)

- Public documentation site built from docs/ and deployed on release.
- API stability and semver policy with /api/v1 as the boundary.
- Throughput benchmark gating CI at the ten runs per minute target,
  measured two orders of magnitude above it after fixing a cold start
  message loss the benchmark itself exposed.
- Reference deployment automation and runbook.
- This release: CITATION.cff, GOVERNANCE.md, and the v1.0.0 tag.
