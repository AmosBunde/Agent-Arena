# Kubernetes deployment

The Kubernetes deployment is the documented production migration path, not the canonical one. See [ADR-0001](../adr/0001-deployment-topology.md) for the reasoning.

Use this topology when:

- You need sustained runner concurrency above what a single VM provides (roughly four concurrent workers on a 4 vCPU 8 GB host).
- You have an uptime requirement that single-VM Compose cannot meet.
- You are running Agent Arena as part of a team's shared infrastructure and need integration with your existing identity, observability, and backup systems.

Do not use this topology because it sounds more impressive. It costs more, it has more failure modes, and it does not produce better benchmark results.

## Prerequisites

- A Kubernetes cluster on a recent version (1.28 or newer).
- An external Postgres 16 instance, multi-AZ for production. RDS Multi-AZ, Cloud SQL HA, or self-managed with replication.
- An external Redis 7 instance. ElastiCache replication group, MemoryStore, or self-managed.
- An S3-compatible object store. S3, GCS, MinIO outside the cluster.
- An ingress controller and an auth proxy in front of the API. OAuth2 Proxy with your IdP, Cloudflare Access, or equivalent.

## Install

```bash
helm repo add agent-arena https://agent-arena-org.github.io/charts
helm install agent-arena agent-arena/agent-arena \
  --namespace agent-arena \
  --create-namespace \
  --values your-values.yaml
```

A starter `values.yaml`:

```yaml
postgres:
  external: true
  url: postgres://user:password@host:5432/agent_arena
redis:
  external: true
  url: redis://host:6379/0
objectStore:
  type: s3
  bucket: agent-arena-traces
  region: eu-west-1
runner:
  replicas: 4
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
api:
  replicas: 2
  ingress:
    enabled: true
    host: arena.your-domain.example
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt
auth:
  trustedHeader: X-Forwarded-User
  defaultRole: viewer
```

## Authentication

The API does not implement its own authentication. Run an auth proxy in front of the ingress. The simplest path is OAuth2 Proxy:

```yaml
# oauth2-proxy values, illustrative
config:
  clientID: ...
  clientSecret: ...
  cookieSecret: ...
extraArgs:
  provider: google
  upstream: http://agent-arena-api:8000
  set-xauthrequest: true
  pass-user-headers: true
```

The proxy is responsible for terminating the user session. The API reads `X-Forwarded-User` and `X-Forwarded-User-Role` from the proxy. See [session design](../design/session-design.md).

## Backup and restore

Two state stores need backups:

1. **Postgres.** Use the managed service's automated backups, plus a daily `pg_dump` to the object store as defence in depth.
2. **Object store.** Enable versioning on the bucket; rely on cross-region replication if your durability requirements demand it.

`scripts/backup.sh` covers both. Restore is documented in `docs/deployment/backup.md` (added in M4).

## Migration from Compose

To migrate an existing Compose deployment:

1. Stop the Compose stack.
2. Dump Postgres: `pg_dump -Fc agent_arena > arena.dump`.
3. Copy `data/traces/` to the target object store.
4. Provision the K8s prerequisites.
5. Restore Postgres into the new instance.
6. Deploy via Helm with values pointing at the external services.
7. Run the smoke-test task suite. Verify a few historical traces are reachable through the trace browser.

There is no online migration path; brief downtime is expected.

## What this topology does not give you

- A different evaluation outcome. Benchmark results are the same regardless of topology.
- Reduced cost. This topology costs strictly more than Compose.
- Magical scalability. The bottleneck remains LLM provider rate limits, which K8s cannot help with.

The thing K8s gives you is operational resilience and team-shared infrastructure integration. That is the only reason to use it.
