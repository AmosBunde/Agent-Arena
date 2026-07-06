# Quickstart

From clone to a scored run on the leaderboard in about five minutes. The only
requirements are git, Docker with the Compose plugin, and optionally one
provider API key.

## 1. Clone and configure

```bash
git clone https://github.com/AmosBunde/Agent-Arena.git
cd Agent-Arena
cp .env.example .env
# Edit .env and set at least one provider API key, for example OPENAI_API_KEY.
```

Runs against a commercial provider need a key. Runs against a local Ollama
server need none; set `OLLAMA_BASE_URL` if your server is not on the default
port.

## 2. Start the stack

```bash
set -a; . ./.env; set +a
docker compose -f deploy/compose/docker-compose.yml up -d --build --wait
```

The first start builds the images and takes two to four minutes. When the
command returns, every service is healthy:

- Web UI: http://127.0.0.1:3000
- API and generated OpenAPI document: http://127.0.0.1:8000/docs

Both ports bind to 127.0.0.1 on purpose. The Compose deployment is an
unauthenticated single-user tool; do not expose it on a public interface
without an auth proxy in front (see docs/design/session-design.md).

## 3. Seed the catalog

The repository ships example tasks and rubrics under `tasks/` and `rubrics/`.
Register one task, one rubric, and one agent through the API:

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "slug": "word-problems-1",
    "version": "1",
    "domain": "general-reasoning",
    "definition": {
      "system": "You are a careful assistant. Answer with the number only, no units and no prose.",
      "prompt": "A train travels at 50 kilometres per hour for 3 hours. How many kilometres does it travel?",
      "expected": "150"
    }
  }'

curl -fsS -X POST http://127.0.0.1:8000/api/v1/rubrics \
  -H 'Content-Type: application/json' \
  -d '{
    "slug": "exact-match",
    "version": "1",
    "definition": {"type": "exact_match", "strip_whitespace": true}
  }'

curl -fsS -X POST http://127.0.0.1:8000/api/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{
    "slug": "baseline",
    "version": "1",
    "definition": {"temperature": 0}
  }'
```

Each call returns the created row including its id. The other example task
and rubric files follow the same shape; their YAML keys map directly onto the
JSON fields above.

## 4. Create a run

Open http://127.0.0.1:3000, switch to the New run view, pick the task, agent,
and rubric you just created, choose a provider and model (for example
`openai` and `gpt-4o-mini`), and press Create runs. The run statuses refresh
every three seconds: `queued`, then `running`, then `complete`.

The same operation through the API:

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "TASK_ID",
    "agent_id": "AGENT_ID",
    "rubric_id": "RUBRIC_ID",
    "providers": [{"provider": "openai", "model": "gpt-4o-mini"}]
  }'
```

To run the same task across several providers at once, add more entries to
`providers`; each becomes its own run inside one run group.

## 5. See the leaderboard

Switch to the Leaderboard view and press Refresh now. The row for your run
shows accuracy, total cost, and cost-per-correct-answer, the headline metric
(ADR-0004). The leaderboard also refreshes automatically every five minutes.

Groups with zero correct answers show "no correct answers" instead of a
number and sort last.

## 6. Where things are

| What | Where |
|------|-------|
| Run statuses and failure reasons | `GET /api/v1/runs`, or the New run view |
| Cancel a run | `DELETE /api/v1/runs/{id}` |
| OpenAPI document | http://127.0.0.1:8000/docs |
| Service logs | `docker compose -f deploy/compose/docker-compose.yml logs -f api runner` |
| Example task and rubric files | `tasks/`, `rubrics/` |

## Troubleshooting

- A run finishes as `failed` with reason `provider error`: the provider
  rejected the call. Check that the key in `.env` is valid and that the model
  identifier exists; then recreate the run.
- A run finishes as `failed` with reason starting `skipped_unsupported`: the
  chosen model does not support a capability the task requires (for example
  tool calling). Pick a model that does.
- The stack does not become healthy: run
  `docker compose -f deploy/compose/docker-compose.yml logs` and look at the
  first failing service. The api container runs database migrations on start,
  so Postgres problems surface there.

## Teardown

```bash
docker compose -f deploy/compose/docker-compose.yml down
```

Add `-v` to also delete the database volume.
