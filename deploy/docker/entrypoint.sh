#!/bin/sh
# Migration runner gated by env flag (docs/design/database-schema.md,
# Migration approach): only the api service sets RUN_MIGRATIONS=1, so the
# schema is migrated exactly once per deployment rollout.
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "running database migrations"
  alembic upgrade head
fi

exec "$@"
