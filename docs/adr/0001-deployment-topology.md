# ADR-0001: Deployment topology

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** Core maintainers

## Context

Agent Arena needs a canonical deployment topology that gets documented in the README, used in CI smoke tests, and assumed by every operational guide. The choice affects time-to-first-result for new users, monthly running cost for anyone running the project, and the credibility of the project as a piece of infrastructure engineering.

The candidates considered were:

1. **Single VM with Docker Compose.** One host, all services as containers, SQLite or single Postgres container, Redis container, no managed services.
2. **AWS ECS Fargate with managed RDS and ElastiCache.** Containers without server management, managed Postgres, managed Redis.
3. **AWS EKS with multi-AZ RDS Multi-AZ and ElastiCache replication groups.** Full Kubernetes, multi-zone high availability, autoscaling.

A naive read of "production-grade open source project" pushes toward option 3. The cost-awareness positioning of Agent Arena pushes hard the other way.

## Decision

The canonical deployment is option 1: single VM with Docker Compose. Kubernetes manifests live in `deploy/k8s/` as a documented migration path for teams that need it, and ECS Fargate Terraform lives in `deploy/terraform/` as an intermediate option, but neither is the default and neither is what the README points users at.

## Consequences

### Positive

The fork-and-run path is preserved. A user who clones the repo and runs `docker compose up` sees a working leaderboard in under five minutes on a 20 USD per month VM. This is the single most important property a self-hosted evaluation tool can have, because researchers and engineers do not adopt tools that require a half-day of infrastructure setup before they can be evaluated.

The project's cost-awareness positioning is internally consistent. A tool that ranks LLM agents by dollars-per-correct-answer cannot credibly recommend a 400 USD per month default deployment. The architectural choice and the headline metric reinforce each other.

The architecture decision becomes a credibility signal rather than a limitation. Reviewers reading the ADR see a deliberate engineering choice with stated tradeoffs, not a default driven by what was easiest.

### Negative

The default deployment is a single point of failure. The VM going down means the leaderboard goes down. For the intended user (a research engineer running benchmarks, not a SaaS operator) this is acceptable. For anyone who needs higher availability, the K8s path is documented and tested.

Horizontal scaling of the runner service requires either upgrading to the K8s deployment or adding more VMs and a shared Postgres. The single-VM topology supports vertical scaling and runner concurrency tuning, but past a certain throughput a topology migration is required. The migration path is documented; the timing is the operator's call.

Postgres in a container with a local volume is fine for the canonical deployment but is not what anyone running this at scale should use. The K8s path uses external managed Postgres, and the documentation is explicit about when to migrate.

### Neutral

The K8s manifests must be maintained alongside the Compose setup. This is real ongoing cost, paid in CI time and contributor attention. The mitigation is that the Helm chart wraps the same containers used in Compose, so feature parity is mostly automatic; the divergence is in storage, networking, and secrets.

## Migration path to Kubernetes

When the single-VM topology stops being adequate (typically when sustained runner concurrency exceeds four or five workers, or when the team has uptime requirements), the documented migration is:

1. Provision external Postgres (RDS Multi-AZ, Cloud SQL, or self-managed).
2. Provision external Redis (ElastiCache, MemoryStore, or self-managed).
3. Migrate the Postgres data via standard `pg_dump` and `pg_restore`.
4. Deploy via `deploy/k8s/helm/agent-arena/` with values pointing at the external services.
5. Verify with the smoke-test task suite before cutting traffic over.

Step-by-step instructions in [docs/deployment/kubernetes.md](../deployment/kubernetes.md).

## References

- Inspect AI deploys as a Python library, not a service. Different model.
- Promptfoo defaults to local CLI and offers cloud as a separate product. Similar reasoning to ours.
- AgentBench defaults to local Docker Compose for the same reason.

## Revision history

- 2026-05-11: Initial decision recorded.
