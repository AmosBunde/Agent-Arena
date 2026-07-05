#!/usr/bin/env bash
# bootstrap-issues.sh (fixed)
#
# Fix vs previous version: `gh issue create --milestone` takes the milestone
# TITLE, not its number. The previous run failed every issue create with
# "'1' not found" because it passed the numeric ID.
#
# Idempotent: skips labels/milestones/issues that already exist.
#
# Usage:
#   ORG=AmosBunde REPO=Agent-Arena bash scripts/bootstrap-issues.sh

set -euo pipefail

ORG="${ORG:?set ORG, e.g. AmosBunde}"
REPO="${REPO:?set REPO, e.g. Agent-Arena}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
DEV_BRANCH="${DEV_BRANCH:-dev}"

command -v gh >/dev/null || { echo "gh CLI required"; exit 1; }

echo "==> Target: ${ORG}/${REPO}"
gh api "repos/${ORG}/${REPO}" --jq '.full_name' \
  || { echo "Repo ${ORG}/${REPO} not reachable via gh."; exit 1; }

echo "==> Ensuring labels exist (idempotent via --force)"
while IFS='|' read -r name color description; do
  gh label create "$name" --repo "${ORG}/${REPO}" --color "$color" --description "$description" --force >/dev/null
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
echo "   labels ok"

# Milestone titles passed verbatim to gh issue create.
declare -A MS_TITLE
MS_TITLE[m1]="M1: Foundation and core loop"
MS_TITLE[m2]="M2: Deterministic replay and trace store"
MS_TITLE[m3]="M3: Provider expansion and statistical rigour"
MS_TITLE[m4]="M4: Operational maturity"
MS_TITLE[m5]="M5: Community and stability for v1.0"

declare -A MS_DESC
MS_DESC[m1]="Working end-to-end loop with three providers and cost-aware leaderboards."
MS_DESC[m2]="Content-addressed trace store with re-scoring."
MS_DESC[m3]="Six providers, bootstrap CIs, contamination analysis."
MS_DESC[m4]="K8s charts, observability, backup, auth integration."
MS_DESC[m5]="API stability, documentation site, public reference deployment."

echo "==> Ensuring milestones exist"
for m in m1 m2 m3 m4 m5; do
  title="${MS_TITLE[$m]}"
  existing=$(gh api "repos/${ORG}/${REPO}/milestones?state=all" \
    --jq ".[] | select(.title==\"$title\") | .number" || true)
  if [[ -n "$existing" ]]; then
    echo "   $m exists (#$existing): $title"
  else
    gh api -X POST "repos/${ORG}/${REPO}/milestones" \
      -f title="$title" -f description="${MS_DESC[$m]}" -f state="open" \
      --jq '.number' >/dev/null
    echo "   $m created: $title"
  fi
done

echo "==> Ensuring local dev branch tracking origin/${DEV_BRANCH}"
git fetch origin "${DEV_BRANCH}" >/dev/null 2>&1
git checkout "${DEFAULT_BRANCH}" >/dev/null 2>&1 || true

echo "==> Creating issues and per-issue branches off ${DEV_BRANCH}"

create_issue() {
  local mkey="$1" labels="$2" title="$3" body="$4"
  local milestone_title="${MS_TITLE[$mkey]}"

  # Skip if an issue with this exact title already exists.
  local existing
  existing=$(gh issue list --repo "${ORG}/${REPO}" --state all \
    --search "in:title \"$title\"" \
    --json number,title \
    --jq ".[] | select(.title==\"$title\") | .number" | head -n1 || true)
  if [[ -n "$existing" ]]; then
    echo "  #${existing} (exists) ${title}"
    return
  fi

  # CRITICAL FIX: --milestone takes the TITLE, not the number.
  local issue_url
  issue_url=$(gh issue create \
    --repo "${ORG}/${REPO}" \
    --title "$title" \
    --body "$body" \
    --milestone "$milestone_title" \
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

  if git ls-remote --exit-code --heads origin "${branch}" >/dev/null 2>&1; then
    echo "     (remote branch ${branch} already exists, skipping)"
  else
    git checkout -b "$branch" "origin/${DEV_BRANCH}" >/dev/null 2>&1
    git push -u origin "$branch" >/dev/null 2>&1
    git checkout "${DEFAULT_BRANCH}" >/dev/null 2>&1
  fi
}

# ---------------- M1 ----------------
create_issue m1 "milestone:m1,area:ci,type:infra" \
  "Set up CI: lint, type-check, unit tests, smoke deploy" \
  "GitHub Actions workflow on PRs into dev. Python: ruff, mypy, pytest. TypeScript: eslint, tsc, vitest. Smoke deploy: docker compose up, hit /health. Caches keyed by lockfiles. Acceptance: failing lint blocks merge; smoke under 4 minutes."

create_issue m1 "milestone:m1,area:db,type:infra" \
  "Postgres schema and Alembic migrations (M1 subset)" \
  "Create the M1 subset per docs/design/database-schema.md: catalog (tasks, rubrics, agents, providers, pricing, api_tokens, audit_log), runs (run_groups, runs, attempts), traces (trace_metadata with nullable body_uri). Acceptance: alembic upgrade head on fresh Postgres 16 produces the schema; downgrade base reverses cleanly."

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "Provider adapter protocol and registry" \
  "Implement the AgentAdapter protocol from ADR-0002. packages/adapters/base.py with Protocol, Capability enum, AdapterResponse, TokenUsage. packages/adapters/registry.py with registration and lookup. Unit tests for registry and capability negotiation."

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "OpenAI adapter implementation" \
  "Use openai Python SDK directly. Capabilities: chat, tool_use, streaming. Token usage normalised to TokenUsage. Exponential backoff on rate-limit and transient errors. Mocked unit tests plus env-gated live integration test."

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "Anthropic adapter implementation" \
  "Use anthropic Python SDK. Capabilities: chat, tool_use, streaming, prompt_caching where supported. Normalise tool-use schema. Cached-token accounting separate from input tokens."

create_issue m1 "milestone:m1,area:adapters,type:feature" \
  "Ollama adapter for local models" \
  "Adapter for local Ollama. Capabilities: chat, tool_use where model supports it. Latency-based cost via configurable hourly rate (default 0 with documented warning). Acceptance: works against real Ollama in CI."

create_issue m1 "milestone:m1,area:cost,type:feature" \
  "Cost model and pricing data for OpenAI, Anthropic, Ollama" \
  "packages/cost-models/{openai,anthropic,ollama}.yaml plus loader.py with valid_from-aware lookup. Decimal arithmetic, never floats. Acceptance: estimate_cost returns expected Decimal per provider; historical lookup correct."

create_issue m1 "milestone:m1,area:runner,type:feature" \
  "Celery runner and agent loop" \
  "apps/runner Celery task execute_run(run_id). Sequential agent loop, capture LLM I/O to trace. Write trace metadata row. Mark run status transitions. Synchronous scoring for deterministic rubrics."

create_issue m1 "milestone:m1,area:api,type:feature" \
  "FastAPI service with M1 endpoints" \
  "GET /health; CRUD-ish for /api/v1/tasks, rubrics, agents, runs; GET /api/v1/leaderboard. OpenAPI spec generated. Contract tests pass."

create_issue m1 "milestone:m1,area:api,type:feature" \
  "Leaderboard materialised view and CPCA computation" \
  "Postgres materialised view per docs/design/database-schema.md. Refresh job every 5 min. CPCA in SQL, NULL when zero correct. Acceptance: leaderboard sorts by CPCA asc with NULLs last; refresh idempotent."

create_issue m1 "milestone:m1,area:web,type:feature" \
  "Minimal React UI: tasks, new run, leaderboard" \
  "Three views with TanStack Query, no auth in M1, function over form. Acceptance: a user can create a run and see it on the leaderboard."

create_issue m1 "milestone:m1,area:deploy,type:infra" \
  "Single-VM Docker Compose deployment" \
  "deploy/compose/docker-compose.yml with api, web, runner, scheduler, postgres, redis. Health checks on every service. API bound to 127.0.0.1. Acceptance: docker compose up on fresh machine produces working stack in under 5 minutes."

create_issue m1 "milestone:m1,area:docs,type:doc" \
  "Quick start guide and contributor guide" \
  "docs/guides/quickstart.md (5-minute walkthrough). docs/guides/contributing.md exists already but extend with PR template references. Acceptance: a fresh user follows quickstart end-to-end without external help."

create_issue m1 "milestone:m1,area:docs,type:doc" \
  "Five example tasks and three example rubrics for M1" \
  "tasks/general-reasoning/word-problems-{1,2,3}.yaml, tasks/tool-use/calculator-1.yaml, tasks/tool-use/search-1.yaml. rubrics/{exact-match,regex-match,json-key-match}.yaml. Acceptance: tasks load via API; rubrics score reference outputs correctly."

# ---------------- M2 ----------------
create_issue m2 "milestone:m2,area:traces,type:feature" \
  "Canonical JSON serialisation for traces" \
  "packages/schemas/trace_canonical.py with sorted-key serialiser, stable float rendering, UTF-8 NFC, no whitespace. Property tests prove equivalent traces hash equal across Linux, macOS, Windows."

create_issue m2 "milestone:m2,area:traces,type:feature" \
  "Content-addressed trace store with MinIO backend" \
  "MinIO container in Compose. packages/adapters-storage with S3 and local-fs implementations. Write canonical JSON body to {hash[:2]}/{hash}.json. Acceptance: byte-identical round-trip."

create_issue m2 "milestone:m2,area:api,type:feature" \
  "Re-scoring endpoint and UI flow" \
  "POST /api/v1/traces/{hash}/score with {rubric_id}. Idempotent. UI button on trace detail page. Acceptance: re-scoring an M1 trace under a new rubric produces a new score row with no LLM calls."

create_issue m2 "milestone:m2,area:web,type:feature" \
  "Trace browser UI" \
  "Trace detail page: prompt/response/tool-call timeline, token usage and cost breakdown per call, per-trace metadata. Acceptance: operator can inspect any past run's full trace."

create_issue m2 "milestone:m2,area:runner,type:feature" \
  "LLM-judge rubric support" \
  "Rubric definition gains judge_model and judge_temperature. Judge call routed through adapter layer, captured in score detail. Judge cost recorded separately so it does not pollute run CPCA."

# ---------------- M3 ----------------
create_issue m3 "milestone:m3,area:adapters,type:feature" \
  "Google adapter (Vertex AI and AI Studio)" \
  "Single adapter, two auth modes. Tool-use schema translation. Safety-settings pass-through. Live test against Gemini 2.x."

create_issue m3 "milestone:m3,area:adapters,type:feature" \
  "AWS Bedrock adapter" \
  "Bedrock Runtime via boto3. Per-model request shape dispatch. Token usage and cost normalised. Live test against at least one Claude and one Mistral on Bedrock."

create_issue m3 "milestone:m3,area:adapters,type:feature" \
  "vLLM adapter (OpenAI-compatible endpoint)" \
  "Adapter for self-hosted vLLM with OpenAI-compatible API. Latency-based cost like Ollama. Smoke test against vLLM container in CI."

create_issue m3 "milestone:m3,area:api,type:feature" \
  "Bootstrap confidence intervals on leaderboard cells" \
  "95 percent CIs on accuracy and CPCA via percentile bootstrap, 1000 resamples by default. Computed in scheduled job, cached. Acceptance: every cell shows point estimate plus CI."

create_issue m3 "milestone:m3,area:api,type:feature" \
  "Pareto front leaderboard view" \
  "Alternative view surfacing (cost, accuracy) Pareto front. Dominated points dimmed in UI. Synthetic test cases produce known fronts."

create_issue m3 "milestone:m3,area:docs,type:feature" \
  "Contamination analysis tooling" \
  "Check whether a task's exact text appears in known public corpora. Per-task contamination flag in catalog. Acceptance: contamination report for M1 task library; flag visible in UI."

# ---------------- M4 ----------------
create_issue m4 "milestone:m4,area:deploy,type:infra" \
  "Kubernetes Helm chart" \
  "deploy/k8s/helm/agent-arena with values for external Postgres, external Redis, S3-compatible store, ingress, runner autoscaling. CI runs smoke suite against kind cluster."

create_issue m4 "milestone:m4,area:deploy,type:infra" \
  "Terraform modules for AWS, GCP, DigitalOcean" \
  "deploy/terraform/{aws,gcp,digitalocean}. Each provisions managed Postgres, Redis, object store, K8s or single VM. terraform plan succeeds in CI."

create_issue m4 "milestone:m4,area:api,type:infra" \
  "Prometheus metrics and OpenTelemetry tracing" \
  "/metrics endpoint on api and runner. OTel SDK with env-controlled exporter. Off by default in Compose, on by default in K8s values."

create_issue m4 "milestone:m4,area:db,type:infra" \
  "Backup and restore tooling" \
  "scripts/backup.sh and scripts/restore.sh for Postgres and trace object store. docs/deployment/backup.md. Round-trip preserves all rows and bodies."

create_issue m4 "milestone:m4,area:api,type:feature" \
  "API token UI for programmatic access" \
  "Admin-only UI to create, list, revoke tokens. Tokens shown once. Argon2id at rest. Acceptance: created token authenticates; revocation takes effect immediately."

# ---------------- M5 ----------------
create_issue m5 "milestone:m5,area:docs,type:doc" \
  "Public documentation site" \
  "Static site generated from docs/, hosted via GitHub Pages. CI rebuilds on merge."

create_issue m5 "milestone:m5,area:docs,type:doc" \
  "API stability and semver policy" \
  "Document stability guarantee, deprecation policy, semver scheme. /api/v1 as stability boundary. docs/STABILITY.md linked from README."

create_issue m5 "milestone:m5,area:api,type:feature" \
  "Performance pass to hit 10 runs per minute on canonical Compose" \
  "Profile and fix bottlenecks for end-to-end run throughput on the canonical deployment with simple tasks. Benchmark in CI confirms target."

create_issue m5 "milestone:m5,area:docs,type:doc" \
  "Public reference deployment with read-only leaderboard" \
  "Deploy Agent Arena to a public URL with curated task suite. README links it. Leaderboard updates daily."

create_issue m5 "milestone:m5,area:docs,type:doc" \
  "Tag v1.0 and finalise CITATION.cff" \
  "v1.0 release. CITATION.cff with maintainer list, Zenodo DOI. GOVERNANCE.md describing maintainer addition process."

echo "==> Setting branch protections (best-effort; may require paid plan for private repos)"
gh api -X PUT "repos/${ORG}/${REPO}/branches/${DEFAULT_BRANCH}/protection" \
  -F required_pull_request_reviews.required_approving_review_count=1 \
  -F required_status_checks.strict=true \
  -F required_status_checks.contexts='["ci/lint","ci/test","ci/smoke"]' \
  -F enforce_admins=false \
  -F restrictions= >/dev/null 2>&1 \
  || echo "   protection on ${DEFAULT_BRANCH} skipped"

gh api -X PUT "repos/${ORG}/${REPO}/branches/${DEV_BRANCH}/protection" \
  -F required_pull_request_reviews.required_approving_review_count=1 \
  -F required_status_checks.strict=true \
  -F required_status_checks.contexts='["ci/lint","ci/test"]' \
  -F enforce_admins=false \
  -F restrictions= >/dev/null 2>&1 \
  || echo "   protection on ${DEV_BRANCH} skipped"

echo
echo "==> Done. ${ORG}/${REPO} now has labels, milestones, issues, and per-issue branches off ${DEV_BRANCH}."
