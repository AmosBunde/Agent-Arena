# Agent Arena

**A cost-aware, provider-agnostic evaluation platform for LLM agents, with deterministic replay.**

Most agent benchmarks measure accuracy and stop there. Agent Arena treats cost-per-correct-answer and latency as first-class leaderboard axes, runs the same task across six LLM backends through a single adapter, and captures every tool call so an agent run can be re-scored under a new rubric six months later without re-spending tokens.

The project is designed to run from one command on a single VM, with a documented production migration path to Kubernetes for teams that need it. The API stability guarantee and semver policy live in [docs/STABILITY.md](docs/STABILITY.md).

---

## Status

Pre-alpha. Milestone M1 is in progress. See [docs/MILESTONES.md](docs/MILESTONES.md) for the roadmap and [docs/adr/](docs/adr/) for the architecture decisions that shape what gets built and what does not.

## Why this exists

The agent evaluation space already has Inspect AI, Promptfoo, DeepEval, AgentBench, and a dozen commercial platforms. Agent Arena exists because none of them combine the following three properties in one tool:

1. **Cost is a first-class metric.** Most leaderboards rank by accuracy and bury cost in a footnote. Agent Arena ranks agents by cost-per-correct-answer, dollars-per-task, and latency tier, computed from per-token billing data that updates when vendor pricing changes.
2. **Provider neutrality is enforced by the architecture.** A single adapter interface covers OpenAI, Anthropic, Google, Bedrock, Ollama, and vLLM. Switching backends requires no code change in the agent itself, only a configuration toggle.
3. **Runs are reproducible without re-execution.** Every tool call, prompt, and response is captured to a content-addressed trace store. A new rubric can be applied to old traces without calling any LLM again. This makes longitudinal benchmarking actually feasible.

None of these are revolutionary individually. The contribution is the combination, made available behind a single `docker compose up`.

## Quick start

The canonical deployment is single-VM Docker Compose, sized for a 20 USD per month cloud instance or a developer laptop. The production migration path is documented in [docs/deployment/kubernetes.md](docs/deployment/kubernetes.md) and is not required for any normal use of the project.

```bash
git clone https://github.com/AmosBunde/Agent-Arena.git
cd Agent-Arena
cp .env.example .env
# Edit .env with at least one provider API key
set -a; . ./.env; set +a
docker compose -f deploy/compose/docker-compose.yml up -d --build --wait
open http://127.0.0.1:3000
```

Time from clone to first leaderboard result: under five minutes on a fresh machine, assuming an API key is available. The full walkthrough, including seeding the example tasks and creating a first run, is in [docs/guides/quickstart.md](docs/guides/quickstart.md).

## How it works

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│   Task      │    │   Adapter    │    │   Scoring    │
│   library   │───▶│   layer      │───▶│   pipeline   │
│  (YAML)     │    │ (6 providers)│    │  (rubrics)   │
└─────────────┘    └──────────────┘    └──────────────┘
                          │                    │
                          ▼                    ▼
                   ┌──────────────┐    ┌──────────────┐
                   │   Trace      │    │ Leaderboard  │
                   │   store      │    │  + cost      │
                   │ (content-    │    │  metrics     │
                   │  addressed)  │    │              │
                   └──────────────┘    └──────────────┘
```

A task is a YAML file describing inputs, expected outputs, and the rubric. The runner executes the task through the adapter for the chosen provider, capturing every prompt, response, tool call, and token count to the trace store. The scoring pipeline applies the rubric to produce a per-task result. The leaderboard aggregates results across runs, attaches confidence intervals via bootstrap resampling, and exposes cost-per-correct-answer as the primary sort key.

For the detailed architecture, see [docs/design/system-design.md](docs/design/system-design.md). For the rationale behind each major decision, see [docs/adr/](docs/adr/).

## Architecture decisions

The shape of this project is defined by five decisions, each with its own ADR. Read these before opening an issue that proposes changing the architecture:

| ADR | Decision |
|-----|----------|
| [ADR-0001](docs/adr/0001-deployment-topology.md) | Single-VM Docker Compose canonical, Kubernetes as documented production path |
| [ADR-0002](docs/adr/0002-provider-adapter-pattern.md) | Provider-agnostic adapter interface with capability negotiation |
| [ADR-0003](docs/adr/0003-content-addressed-trace-store.md) | Content-addressed trace store with rubric-versioned re-scoring |
| [ADR-0004](docs/adr/0004-cost-model.md) | Vendor pricing as versioned data, cost-per-correct-answer as primary metric |
| [ADR-0005](docs/adr/0005-database-architecture.md) | PostgreSQL with logical separation, no premature sharding |

## What this is not

To save everyone time:

- **Not a hosted SaaS.** Self-host or fork. No managed offering planned.
- **Not a training framework.** Agents are evaluated, not trained.
- **Not a replacement for Inspect AI on safety-specific evals.** If you need red-team or capability-uplift evaluation, use Inspect AI. Agent Arena is for general-purpose agent benchmarking with cost-awareness.
- **Not Kubernetes-first.** The K8s manifests are real and tested, but they are not the canonical deployment path. See ADR-0001 for the reasoning.

## Tech stack

Python 3.12 on the backend (FastAPI, SQLAlchemy, Celery), TypeScript on the frontend (React, Vite, TanStack Query), PostgreSQL 16 for state, Redis 7 for queues and caching, and Docker Compose for orchestration. The LLM orchestration uses LangGraph where graph semantics genuinely help (multi-step tool-using agents) and direct adapter calls where they do not.

Provider adapters cover OpenAI, Anthropic, Google (Vertex AI and AI Studio), AWS Bedrock, Ollama (local), and vLLM (self-hosted). Adding a new provider is a single file in `packages/adapters/` and an entry in the registry.

## Repository layout

```
agent-arena/
├── apps/
│   ├── api/          FastAPI service: tasks, runs, results, leaderboards
│   ├── web/          React frontend
│   └── runner/       Celery worker that executes agent tasks
├── packages/
│   ├── adapters/     Provider adapter implementations
│   ├── schemas/      Shared Pydantic and TypeScript schemas
│   └── cost-models/  Versioned vendor pricing data
├── tasks/            Task library, organised by domain
├── rubrics/          Scoring rubrics, versioned independently of tasks
├── deploy/
│   ├── compose/      Canonical single-VM deployment
│   ├── k8s/          Helm charts for production migration
│   └── terraform/    Optional IaC for cloud provisioning
├── docs/
│   ├── adr/          Architecture decision records
│   ├── design/       System and component designs
│   ├── deployment/   Operational guides for each topology
│   └── guides/       Contributor and user guides
└── scripts/          Operational and developer scripts
```

## Contributing

Read the relevant ADRs first. If you disagree with one, open a discussion before a PR; ADRs are amended through a documented process, not silently overridden. Contributor guide lives at [docs/guides/contributing.md](docs/guides/contributing.md).

The development branch is `dev`. The default branch is `main` and only receives release merges. All feature work happens on issue-numbered branches off `dev`, named `{issue-number}-{slug}` (for example `42-bedrock-adapter`).

## License

Apache 2.0. See [LICENSE](LICENSE).

## Citation

If Agent Arena contributes to published research, please cite the repository. A canonical citation will be added at v0.1.0 release. See [CITATION.cff](CITATION.cff).

## Maintainers

Project initiated and maintained by [@AmosBunde](https://github.com/AmosBunde). Maintainer additions will be announced in [GOVERNANCE.md](GOVERNANCE.md).
