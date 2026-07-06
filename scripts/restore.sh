#!/usr/bin/env bash
# Restore Postgres and the trace object store from a backup (issue #29).
#
# Usage: DATABASE_URL=... TRACE_STORE_URL=... scripts/restore.sh <backup-dir>
#
# The database restore is destructive: existing objects are dropped and
# recreated from the dump. PG_RESTORE overrides the pg_restore command. See
# docs/deployment/backup.md.
set -euo pipefail

BACKUP_DIR=${1:?usage: restore.sh <backup-dir>}
: "${DATABASE_URL:?DATABASE_URL is required}"
TRACE_STORE_URL=${TRACE_STORE_URL:-data/traces}

PG_URL=${DATABASE_URL/postgresql+psycopg:/postgresql:}

echo "restoring postgres"
${PG_RESTORE:-pg_restore} --clean --if-exists --no-owner \
  --dbname="${PG_URL}" < "${BACKUP_DIR}/postgres.dump"

echo "restoring trace store ${TRACE_STORE_URL}"
case "${TRACE_STORE_URL}" in
  s3://*)
    aws s3 sync "${BACKUP_DIR}/traces" "${TRACE_STORE_URL}" \
      ${S3_ENDPOINT_URL:+--endpoint-url "${S3_ENDPOINT_URL}"}
    ;;
  file://*|/*|.*|[a-zA-Z]*)
    STORE_PATH=${TRACE_STORE_URL#file://}
    if [ -f "${BACKUP_DIR}/traces.tar.gz" ]; then
      mkdir -p "${STORE_PATH}"
      tar -C "${STORE_PATH}" -xzf "${BACKUP_DIR}/traces.tar.gz"
    else
      echo "no traces archive in ${BACKUP_DIR}; skipping" >&2
    fi
    ;;
esac
echo "restore complete"
