# Milestones

Five milestones from empty repo to v1.0. Each milestone is a coherent slice that produces something useful on its own; you do not need to complete M5 to get value from M1.

The differentiators land in sequence: provider-agnostic adapters and cost-aware leaderboards together in M1 (they need each other to be meaningful), deterministic replay in M2, statistical rigour in M3. M4 and M5 are extensions, not core differentiators.

## M1: Foundation and core loop

**Goal.** A working end-to-end flow: register an agent, run it on a task across at least two providers, see results on a leaderboard ranked by cost-per-correct-answer.

**Includes.**

- Repository scaffold, CI, contributor docs.
- Postgres schema (M1 subset: catalog, runs, basic traces).
- Provider adapter interface and three adapters: OpenAI, Anthropic, Ollama.
- Cost model with pricing data for the three providers.
- FastAPI service with the endpoints needed for the core loop.
- Celery runner with synchronous scoring for deterministic rubrics.
- Minimal React UI: task list, run creation, leaderboard view.
- Single-VM Docker Compose deployment that works from `git clone` to leaderboard in under five minutes.
- Five example tasks across two domains (general reasoning, simple tool use).
- Three example rubrics (exact match, regex match, JSON-key match).

**Out of scope for M1.** Deterministic replay, statistical rigour on leaderboards, web UI polish beyond functional, more than three providers.

**Exit criteria.** End-to-end run on a fresh clone produces a leaderboard that correctly ranks two models by cost-per-correct-answer. CI green. README accurate.

## M2: Deterministic replay and trace store

**Goal.** Trace capture and re-scoring such that an existing run can be evaluated under a new rubric without re-spending tokens.

**Includes.**

- Content-addressed trace store with canonical JSON serialisation.
- MinIO container in Compose, S3 abstraction for K8s.
- Trace canonicalisation test suite (property tests for determinism).
- Re-scoring endpoint and UI flow.
- Trace browser UI: inspect prompts, responses, tool calls.
- LLM-judge rubric support with judge model and temperature recorded.

**Exit criteria.** A run from M1 can be re-scored under a new M2 rubric, with the new score appearing in the leaderboard alongside the original. The canonicalisation test suite passes on Linux, macOS, and Windows.

## M3: Provider expansion and statistical rigour

**Goal.** Cover the remaining provider matrix and add the methodological rigour a frontier-lab reviewer expects.

**Includes.**

- Google (Vertex AI and AI Studio), AWS Bedrock, vLLM adapters.
- Bootstrap confidence intervals on every leaderboard cell.
- Pareto front view alongside the ranked-by-CPCA view.
- Contamination analysis tooling: detect when a task's exact text appears in known pretraining corpora.
- Task difficulty calibration based on success rate dispersion across providers.
- Audit log surfacing in the UI.

**Exit criteria.** All six providers operational with at least one model each. Leaderboards display 95 percent CIs by default. Contamination report can be run on the task library.

## M4: Operational maturity

**Goal.** Make Agent Arena a tool a small team can run in production without fighting it.

**Includes.**

- Kubernetes Helm charts, tested in CI against a kind cluster.
- Terraform modules for AWS, GCP, and DigitalOcean.
- Prometheus metrics and OpenTelemetry tracing wired through.
- Backup and restore tooling for Postgres and trace store.
- Pricing update workflow with PR-based review.
- API token UI for CI integration.
- Auth proxy integration examples (OAuth2 Proxy, Cloudflare Access).

**Exit criteria.** A fresh user can deploy the K8s topology following the docs in under thirty minutes. Backup and restore round-trip preserves all run history.

## M5: Community and stability for v1.0

**Goal.** Hit v1.0 with a stable interface, clear contribution path, and at least one external production deployment confirmed.

**Includes.**

- Public task and rubric submission process.
- API stability guarantee documented (semver, deprecation policy).
- Performance optimisation pass: target ten runs per minute on the canonical Compose deployment for simple tasks.
- Documentation site, hosted from the repo.
- Reference deployment publishing a public read-only leaderboard.
- Citation file finalised, v1.0 release tagged.

**Exit criteria.** v1.0 tagged. At least three contributors with merged PRs other than the core maintainer. At least one external deployment reachable for verification.

## Out of scope through v1.0

These are noted so contributors do not propose them in v1.0:

- Multi-tenant SaaS.
- Training or fine-tuning workflows.
- Streaming-only adapters (every adapter supports streaming, but streaming is not a separate evaluation modality).
- A general-purpose plugin system. Extensions go through the adapter, task, and rubric interfaces; arbitrary plugins are not supported in v1.0.
