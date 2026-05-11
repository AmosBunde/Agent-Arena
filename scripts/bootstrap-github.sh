#!/usr/bin/env bash
# scripts/bootstrap-github.sh
#
# One-shot bootstrap. Run this once after creating the GitHub org.
# Creates: repo, milestones, issues, dev-based branches per issue,
# branch protections on main and dev.
#
# Requires: gh (authenticated), git, jq.
# Set ORG before running. ORG must already exist (create it manually in the GitHub UI).

set -euo pipefail

ORG="${ORG:-agent-arena-org}"
REPO="${REPO:-agent-arena}"
DEFAULT_BRANCH="main"
DEV_BRANCH="dev"

command -v gh >/dev/null || { echo "gh CLI required"; exit 1; }
command -v jq >/dev/null || { echo "jq required"; exit 1; }

echo "==> Creating repo ${ORG}/${REPO} (public, with description)"
gh repo create "${ORG}/${REPO}" \
  --public \
  --description "Cost-aware, provider-agnostic LLM agent evaluation with deterministic replay." \
  --homepage "https://github.com/${ORG}/${REPO}" \
  --disable-wiki \
  --confirm || echo "Repo may already exist; continuing."

# Push local scaffold to main, then branch dev from main.
git init -b "${DEFAULT_BRANCH}"
git remote add origin "git@github.com:${ORG}/${REPO}.git" 2>/dev/null || true
git add .
git -c user.email="bootstrap@agent-arena.local" -c user.name="bootstrap" \
    commit -m "chore: initial scaffold (M1 prep)" || true
git push -u origin "${DEFAULT_BRANCH}"

echo "==> Creating dev branch from main"
git checkout -b "${DEV_BRANCH}"
git push -u origin "${DEV_BRANCH}"
git checkout "${DEFAULT_BRANCH}"

echo "==> Setting dev as the default for PRs (default_branch stays main for releases)"
# main remains the default branch; dev is the integration branch per contributor docs.

echo "==> Creating labels"
while IFS='|' read -r name color description; do
  gh label create "$name" --repo "${ORG}/${REPO}" --color "$color" --description "$description" --force
done <<'LABELS'
milestone:m1|0E8A16|Foundation and core loop
milestone:m2|0E8A16|Deterministic replay and trace store
milestone:m3|0E8A16|Provider expansion and statistical rigour
milestone:m4|0E8A16|Operational maturity
milestone:m5|0E8A16|Community and stability for v1.0
area:adapters|1D76DB|Provider adapter layer
area:api|1D76DB|FastAPI service
area:web|1D76DB|React frontend
area:runner|1D76DB|Celery runner and agent loop
area:db|1D76DB|Database schema and migrations
area:traces|1D76DB|Trace store and replay
area:cost|1D76DB|Cost model and pricing data
area:deploy|1D76DB|Deployment, Compose, K8s, Terraform
area:docs|1D76DB|Documentation and ADRs
area:ci|1D76DB|CI and developer workflow
type:feature|A2EEEF|New capability
type:infra|A2EEEF|Infrastructure or tooling
type:doc|A2EEEF|Documentation
type:test|A2EEEF|Tests
good-first-issue|7057FF|Good for new contributors
LABELS

echo "==> Creating milestones"
declare -A MILESTONES
for m in m1 m2 m3 m4 m5; do
  case "$m" in
    m1) title="M1: Foundation and core loop"
        desc="Working end-to-end loop with three providers and cost-aware leaderboards." ;;
    m2) title="M2: Deterministic replay and trace store"
        desc="Content-addressed trace store with re-scoring." ;;
    m3) title="M3: Provider expansion and statistical rigour"
        desc="Six providers, bootstrap CIs, contamination analysis." ;;
    m4) title="M4: Operational maturity"
        desc="K8s charts, observability, backup, auth integration." ;;
    m5) title="M5: Community and stability for v1.0"
        desc="API stability, documentation site, public reference deployment." ;;
  esac
  number=$(gh api -X POST "repos/${ORG}/${REPO}/milestones" \
    -f title="$title" -f description="$desc" -f state="open" \
    --jq '.number' 2>/dev/null || \
    gh api "repos/${ORG}/${REPO}/milestones?state=all" \
      --jq ".[] | select(.title==\"$title\") | .number")
  MILESTONES[$m]=$number
  echo "  $m -> #$number $title"
done

echo "==> Creating issues and per-issue branches off dev"
# Format per row: milestone|labels|title|body
create_issue() {
  local milestone="$1" labels="$2" title="$3" body="$4"
  local mnum="${MILESTONES[$milestone]}"
  local issue_url
  issue_url=$(gh issue create \
    --repo "${ORG}/${REPO}" \
    --title "$title" \
    --body "$body" \
    --milestone "$mnum" \
    --label "$labels")
  local issue_number
  issue_number=$(echo "$issue_url" | grep -oE '[0-9]+$')
  local slug
  slug=$(echo "$title" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
    | cut -c1-50)
  local branch="${issue_number}-${slug}"
  echo "  #${issue_number} ${title}  ->  branch ${branch}"
  git fetch origin "${DEV_BRANCH}"
  git checkout -b "$branch" "origin/${DEV_BRANCH}"
  git push -u origin "$branch"
  git checkout "${DEFAULT_BRANCH}"
}

# ---------------- M1 ----------------
create_issue m1 "milestone:m1,area:ci,type:infra" \
  "Set up CI: lint, type-check, unit tests, smoke deploy" \
  "$(cat <<'BODY'
GitHub Actions workflow that runs on PRs into dev:
- Python: ruff, mypy, pytest
- TypeScript: eslint, tsc, vitest
- Smoke deploy: docker compose up, hit /health, hit /api/v1/tasks
- Cache: pip and pnpm caches keyed by lockfiles

Acceptance: failing lint blocks merge into dev; smoke deploy step under 4 minutes.
BODY
)"

create_issue m1 "milestone:m1,area:db,type:infra" \
  "Postgres schema and Alembic migrations (M1 subset)" \
  "$(cat <<'BODY'
Create the M1 subset of the schema described in docs/design/database-schema.md:
- catalog: tasks, rubrics, agents, providers, pricing, api_tokens, audit_log
- runs: run_groups, runs, attempts
- traces: trace_metadata (body_uri can be null in M1, populated in M2)

Acceptance: alembic upgrade head on a fresh Postgres 16 produces the schema; alembic downgrade base reverses it cleanly.
BODY
)"

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "Provider adapter protocol and registry" \
  "$(cat <<'BODY'
Implement the AgentAdapter protocol from ADR-0002:
- packages/adapters/base.py with the Protocol, Capability enum, AdapterResponse, TokenUsage
- packages/adapters/registry.py with registration and lookup by (provider, model)
- Unit tests for registry behaviour and capability negotiation

Acceptance: a stub adapter registers, is retrievable, reports capabilities, returns a well-typed AdapterResponse.
BODY
)"

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "OpenAI adapter implementation" \
  "$(cat <<'BODY'
First concrete adapter. Use the openai Python SDK directly. Capabilities: chat, tool_use, streaming. Token usage from the API response normalised to TokenUsage. Retry with exponential backoff on rate-limit and transient errors.

Acceptance: integration test (mocked) covers chat with and without tools; live test (env-gated) hits the real API with a tiny prompt.
BODY
)"

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "Anthropic adapter implementation" \
  "$(cat <<'BODY'
Use the anthropic Python SDK. Capabilities: chat, tool_use, streaming, prompt_caching (where supported). Normalise tool-use schema to the common Tool format. Cached-token accounting separate from input tokens.

Acceptance: same as OpenAI adapter; tool_use round-trip works.
BODY
)"

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "Ollama adapter for local models" \
  "$(cat <<'BODY'
Adapter for a locally running Ollama instance. Capabilities: chat, tool_use (where the underlying model supports it). Latency-based cost via configurable hourly rate (default 0 with documented warning). Model availability check.

Acceptance: adapter works against a real Ollama instance in CI; capability advertisement reflects underlying model.
BODY
)"

create_issue m1 "milestone:m1,area:cost,type:feature" \
  "Cost model and pricing data files for OpenAI, Anthropic, Ollama" \
  "$(cat <<'BODY'
- packages/cost-models/openai.yaml
- packages/cost-models/anthropic.yaml
- packages/cost-models/ollama.yaml (rate-based, defaults to 0)
- packages/cost-models/loader.py with valid_from-aware lookup
- Decimal-based cost arithmetic, never floats

Acceptance: estimate_cost on a synthetic TokenUsage returns the expected Decimal for each provider; historical price lookup works.
BODY
)"

create_issue m1 "milestone:m1,area:runner,type:feature" \
  "Celery runner and agent loop" \
  "$(cat <<'BODY'
- apps/runner with one Celery task: execute_run(run_id)
- Sequential agent loop: load agent, load task, dispatch adapter calls, capture LLM I/O to in-memory trace
- Write trace metadata row (body_uri null in M1)
- Mark run status transitions
- Apply scoring synchronously for deterministic rubrics

Acceptance: enqueue a run, observe status pending -> running -> complete, score row appears.
BODY
)"

create_issue m1 "milestone:m1,area:api,type:feature" \
  "FastAPI service with M1 endpoints" \
  "$(cat <<'BODY'
Endpoints:
- GET /health
- GET, POST /api/v1/tasks
- GET, POST /api/v1/rubrics
- GET, POST /api/v1/agents
- GET, POST /api/v1/runs
- GET /api/v1/runs/{id}
- DELETE /api/v1/runs/{id}
- GET /api/v1/leaderboard?task_id=...&rubric_id=...

Acceptance: OpenAPI spec generated; contract tests pass.
BODY
)"

create_issue m1 "milestone:m1,area:api,type:feature" \
  "Leaderboard materialised view and CPCA computation" \
  "$(cat <<'BODY'
Postgres materialised view per docs/design/database-schema.md. Refresh job in the scheduler service every 5 minutes. CPCA computed in SQL, with NULL when no correct answers. Leaderboard endpoint returns view rows joined with agent and task display data.

Acceptance: leaderboard correctly sorts by CPCA ascending with NULLs last; refresh job idempotent.
BODY
)"

create_issue m1 "milestone:m1,area:web,type:feature" \
  "Minimal React UI for task list, run creation, leaderboard" \
  "$(cat <<'BODY'
Three views:
- Tasks: list with filter by domain
- New Run: pick agent, task, providers, rubric; submit
- Leaderboard: sortable table per (task, rubric), default sort CPCA asc

Use TanStack Query, no auth in M1, no design system commitment yet. Function over form.

Acceptance: a user can create a run and see it on the leaderboard once complete.
BODY
)"

create_issue m1 "milestone:m1,area:deploy,type:infra" \
  "Single-VM Docker Compose deployment" \
  "$(cat <<'BODY'
deploy/compose/docker-compose.yml with services: api, web, runner, scheduler, postgres, redis. .env.example with required keys. Health checks on every service. API bound to 127.0.0.1 by default.

Acceptance: docker compose up on a fresh machine produces a working stack in under 5 minutes; smoke run passes.
BODY
)"

create_issue m1 "milestone:m1,area:docs,type:doc" \
  "Quick start guide and contributor guide" \
  "$(cat <<'BODY'
- docs/guides/quickstart.md: 5-minute clone-to-leaderboard walkthrough
- docs/guides/contributing.md: branch model (dev-based), commit style (Conventional Commits), PR template, ADR amendment process

Acceptance: a fresh user can follow quickstart end-to-end without external help.
BODY
)"

create_issue m1 "milestone:m1,area:docs,type:doc" \
  "Five example tasks and three example rubrics for M1" \
  "$(cat <<'BODY'
- tasks/general-reasoning/word-problems-1.yaml ... -3.yaml
- tasks/tool-use/calculator-1.yaml, search-1.yaml
- rubrics/exact-match.yaml
- rubrics/regex-match.yaml
- rubrics/json-key-match.yaml

Acceptance: tasks load via API; rubrics score reference outputs correctly.
BODY
)"

# ---------------- M2 ----------------
create_issue m2 "milestone:m2,area:traces,type:feature" \
  "Canonical JSON serialisation for traces" \
  "$(cat <<'BODY'
Implement deterministic canonical JSON per ADR-0003:
- packages/schemas/trace_canonical.py with sorted-key serialiser
- Stable float rendering, UTF-8 NFC normalisation, no whitespace
- Property tests: equivalent traces hash equal across platforms

Acceptance: property test suite green on Linux, macOS, Windows runners.
BODY
)"

create_issue m2 "milestone:m2,area:traces,type:feature" \
  "Content-addressed trace store with MinIO backend" \
  "$(cat <<'BODY'
- MinIO container in Compose
- packages/adapters-storage with S3 and local-filesystem implementations
- Write canonical JSON body to {hash[:2]}/{hash}.json
- trace_metadata row populated with body_uri and body_size_bytes

Acceptance: runner writes a trace, reader fetches it by hash, byte-identical round-trip.
BODY
)"

create_issue m2 "milestone:m2,area:api,type:feature" \
  "Re-scoring endpoint and UI flow" \
  "$(cat <<'BODY'
- POST /api/v1/traces/{hash}/score with body {rubric_id}
- Idempotent: re-scoring with the same rubric returns the existing row
- UI: button on trace detail page to apply another rubric

Acceptance: re-scoring an M1 trace under a new rubric produces a new score row without LLM calls.
BODY
)"

create_issue m2 "milestone:m2,area:web,type:feature" \
  "Trace browser UI" \
  "$(cat <<'BODY'
- Trace detail page: full prompt/response/tool-call timeline
- Token usage and cost breakdown per call
- Per-trace metadata (hash, adapter version, created_at)

Acceptance: an operator can inspect any past run's full trace in the UI.
BODY
)"

create_issue m2 "milestone:m2,area:runner,type:feature" \
  "LLM-judge rubric support" \
  "$(cat <<'BODY'
- Rubric definition gains judge_model and judge_temperature fields
- Judge call routed through the adapter layer, captured as part of the score detail
- Score row records judge model and the judge's own token usage and cost (separately from the run's cost)

Acceptance: an LLM-judge rubric correctly scores a trace; the judge cost is visible in the UI but does not pollute the run's CPCA.
BODY
)"

# ---------------- M3 ----------------
create_issue m3 "milestone:m3,area:adapters,type:feature" \
  "Google adapter (Vertex AI and AI Studio)" \
  "$(cat <<'BODY'
Single adapter file with two auth modes: Vertex AI service account and AI Studio API key. Tool-use schema translation. Safety-settings pass-through.

Acceptance: live test against Gemini 2.x; capability advertisement correct.
BODY
)"

create_issue m3 "milestone:m3,area:adapters,type:feature" \
  "AWS Bedrock adapter" \
  "$(cat <<'BODY'
Bedrock Runtime via boto3. Each model on Bedrock has a different request shape; the adapter handles dispatch by model id. Token usage and cost normalised.

Acceptance: live test against at least one Bedrock-hosted Claude and one Bedrock-hosted Mistral.
BODY
)"

create_issue m3 "milestone:m3,area:adapters,type:feature" \
  "vLLM adapter (OpenAI-compatible endpoint)" \
  "$(cat <<'BODY'
Adapter for a self-hosted vLLM server that exposes the OpenAI-compatible endpoint. Latency-based cost like Ollama.

Acceptance: smoke test against a vLLM container in CI.
BODY
)"

create_issue m3 "milestone:m3,area:api,type:feature" \
  "Bootstrap confidence intervals on leaderboard cells" \
  "$(cat <<'BODY'
- 95% CIs on accuracy and on CPCA via percentile bootstrap
- 1000 resamples by default, configurable
- CI computation in a scheduled job, cached in aggregates table

Acceptance: every leaderboard cell shows point estimate plus CI; CIs collapse to zero width for fully deterministic single-run cells.
BODY
)"

create_issue m3 "milestone:m3,area:api,type:feature" \
  "Pareto front leaderboard view" \
  "$(cat <<'BODY'
Alternative leaderboard view that surfaces the (cost, accuracy) Pareto front. Dominated points dimmed in the UI. Endpoint returns Pareto-optimal entries plus full set for context.

Acceptance: synthetic test cases produce known Pareto fronts.
BODY
)"

create_issue m3 "milestone:m3,area:docs,type:feature" \
  "Contamination analysis tooling" \
  "$(cat <<'BODY'
Tool to check whether a task's exact text appears in known public corpora. Initial corpus list: a small set of public web archives. Output: per-task contamination flag in the task catalog.

Acceptance: contamination report for the M1 task library; UI flag visible on contaminated tasks.
BODY
)"

# ---------------- M4 ----------------
create_issue m4 "milestone:m4,area:deploy,type:infra" \
  "Kubernetes Helm chart" \
  "$(cat <<'BODY'
deploy/k8s/helm/agent-arena with values for: external Postgres URL, external Redis URL, S3-compatible object store credentials, ingress, autoscaling for the runner deployment.

Acceptance: helm install on a kind cluster yields a working deployment; CI runs the smoke suite against it.
BODY
)"

create_issue m4 "milestone:m4,area:deploy,type:infra" \
  "Terraform modules for AWS, GCP, DigitalOcean" \
  "$(cat <<'BODY'
deploy/terraform/aws, gcp, digitalocean. Each provisions: managed Postgres, managed Redis, object store, K8s cluster (or single VM, configurable).

Acceptance: terraform plan succeeds for each cloud; documented apply path produces a working environment.
BODY
)"

create_issue m4 "milestone:m4,area:api,type:infra" \
  "Prometheus metrics and OpenTelemetry tracing" \
  "$(cat <<'BODY'
- /metrics endpoint on api and runner
- OTel SDK wired through with env-controlled exporter
- Compose stays metrics-off by default; K8s values turn it on

Acceptance: a Prometheus scrape returns request counts, run statuses, queue depth, adapter latencies.
BODY
)"

create_issue m4 "milestone:m4,area:db,type:infra" \
  "Backup and restore tooling" \
  "$(cat <<'BODY'
scripts/backup.sh and scripts/restore.sh covering Postgres and trace object store. Documented in docs/deployment/backup.md.

Acceptance: round-trip backup and restore preserves all rows and all trace bodies; smoke test runs against the restored DB.
BODY
)"

create_issue m4 "milestone:m4,area:api,type:feature" \
  "API token UI for programmatic access" \
  "$(cat <<'BODY'
Admin-only UI to create, list, and revoke API tokens. Tokens shown once at creation, Argon2id at rest, prefix indexed.

Acceptance: a token created in the UI can authenticate against the API; revocation takes effect immediately.
BODY
)"

# ---------------- M5 ----------------
create_issue m5 "milestone:m5,area:docs,type:doc" \
  "Public documentation site" \
  "$(cat <<'BODY'
Static site generated from docs/, hosted from the repo via GitHub Pages or a similar zero-cost option.

Acceptance: docs site reflects current main; CI rebuilds on merge.
BODY
)"

create_issue m5 "milestone:m5,area:docs,type:doc" \
  "API stability and semver policy" \
  "$(cat <<'BODY'
Document the API stability guarantee, deprecation policy, and the semver scheme for the project. Add the /api/v1 prefix as a stability boundary.

Acceptance: docs/STABILITY.md exists and is linked from the README.
BODY
)"

create_issue m5 "milestone:m5,area:api,type:feature" \
  "Performance pass to hit 10 runs per minute on canonical Compose" \
  "$(cat <<'BODY'
Profile end-to-end run throughput on the canonical Compose deployment with simple tasks. Identify and fix bottlenecks. Target: 10 runs per minute with the four-worker default.

Acceptance: benchmark in CI confirms the throughput target on the standard runner spec.
BODY
)"

create_issue m5 "milestone:m5,area:docs,type:doc" \
  "Public reference deployment with read-only leaderboard" \
  "$(cat <<'BODY'
Deploy Agent Arena to a public URL with a read-only leaderboard populated by a curated task suite. Linked from the README.

Acceptance: URL is live, leaderboard updates daily, README links it.
BODY
)"

create_issue m5 "milestone:m5,area:docs,type:doc" \
  "Tag v1.0 and finalise CITATION.cff" \
  "$(cat <<'BODY'
Final v1.0 release. CITATION.cff with maintainer list and DOI from Zenodo integration. GOVERNANCE.md describing maintainer addition process.

Acceptance: v1.0 tag exists; release notes summarise M1 through M5; Zenodo DOI minted.
BODY
)"

echo "==> Setting branch protections on main and dev"
gh api -X PUT "repos/${ORG}/${REPO}/branches/${DEFAULT_BRANCH}/protection" \
  -F required_pull_request_reviews.required_approving_review_count=1 \
  -F required_status_checks.strict=true \
  -F required_status_checks.contexts='["ci/lint","ci/test","ci/smoke"]' \
  -F enforce_admins=false \
  -F restrictions= >/dev/null
gh api -X PUT "repos/${ORG}/${REPO}/branches/${DEV_BRANCH}/protection" \
  -F required_pull_request_reviews.required_approving_review_count=1 \
  -F required_status_checks.strict=true \
  -F required_status_checks.contexts='["ci/lint","ci/test"]' \
  -F enforce_admins=false \
  -F restrictions= >/dev/null

echo "==> Done. ${ORG}/${REPO} bootstrapped with milestones, issues, and per-issue branches off ${DEV_BRANCH}."
