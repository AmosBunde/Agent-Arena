# Public reference deployment

The reference deployment is a read-only, public instance of Agent Arena
serving the curated task suite so anyone can inspect a live leaderboard
without installing anything. This runbook takes an operator from a fresh
VM to the public URL.

## What it consists of

- The canonical Compose stack plus
  `deploy/reference/docker-compose.override.yml`, which pins anonymous
  requests to the read-only viewer role.
- The curated suite: the task and rubric library under `tasks/` and
  `rubrics/`, seeded by `scripts/seed_reference.py`.
- A daily benchmark run of the suite, so the leaderboard updates every day.
- An HTTPS reverse proxy in front of the web port.

## Steps

1. Provision a VM (the Terraform modules under `deploy/terraform/` build
   one with managed state) and clone the repository.
2. Start the stack with the reference override:

   ```bash
   docker compose -f deploy/compose/docker-compose.yml \
     -f deploy/reference/docker-compose.override.yml up -d --build --wait
   ```

3. Create an admin API token from inside the host (the Tokens view or
   `POST /api/v1/tokens` with the local admin identity), then seed the
   curated suite:

   ```bash
   python3 scripts/seed_reference.py --api-url http://127.0.0.1:8000 --token arena_...
   ```

4. Schedule the daily update. The leaderboard view itself refreshes every
   five minutes; the daily job re-runs the curated suite so fresh runs
   arrive at most a day old. With cron:

   ```cron
   15 4 * * * cd /opt/agent-arena && python3 scripts/benchmark.py \
     --api-url http://127.0.0.1:8000 --runs 10 --target-per-minute 1 \
     >> /var/log/arena-daily.log 2>&1
   ```

   Replace the mock benchmark with real provider runs once keys are
   configured on the runner; the daily cadence is the same either way.

5. Put an HTTPS proxy in front of `127.0.0.1:3000` (Caddy shown). The
   proxy MUST strip the identity headers, because the API trusts them
   (session-design.md); without stripping, any visitor could claim the
   admin role by sending the header themselves:

   ```
   arena.example.org {
       reverse_proxy 127.0.0.1:3000 {
           header_up -X-Forwarded-User
           header_up -X-Forwarded-User-Role
       }
   }
   ```

6. Update the README badge link to the public URL.

## Safety properties

- Anonymous requests are viewer role: no run creation, no catalog writes,
  no token management, no spend.
- The proxy strips `X-Forwarded-User` and `X-Forwarded-User-Role` from
  client requests, so identity cannot be forged from outside; management
  happens from the host or with admin API tokens.
- Provider keys live only in the runner container environment.
- The database and object store ports are never published.

## Costs

A curated suite of five tasks across two commercial providers, run daily,
spends a few cents per day at current prices; the exact figure is on the
leaderboard itself, which is the point of the project.
