#!/usr/bin/env bash
# Backup Postgres and the trace object store (issue #29).
#
# Usage: DATABASE_URL=... TRACE_STORE_URL=... scripts/backup.sh <backup-dir>
#
# Postgres is dumped in custom format through pg_dump; the trace store is
# archived (local filesystem store) or synced (s3:// store, requires the aws
# CLI; S3_ENDPOINT_URL is honoured for MinIO). PG_DUMP overrides the pg_dump
# command, for example to run it from a container. See
# docs/deployment/backup.md.
set -euo pipefail

BACKUP_DIR=${1:?usage: backup.sh <backup-dir>}
: "${DATABASE_URL:?DATABASE_URL is required}"
TRACE_STORE_URL=${TRACE_STORE_URL:-data/traces}

mkdir -p "${BACKUP_DIR}"
# pg tools speak postgresql://, not the SQLAlchemy driver-qualified form.
PG_URL=${DATABASE_URL/postgresql+psycopg:/postgresql:}

echo "backing up postgres"
${PG_DUMP:-pg_dump} --format=custom --no-owner "${PG_URL}" > "${BACKUP_DIR}/postgres.dump"

echo "backing up trace store ${TRACE_STORE_URL}"
case "${TRACE_STORE_URL}" in
  s3://*)
    aws s3 sync "${TRACE_STORE_URL}" "${BACKUP_DIR}/traces" \
      ${S3_ENDPOINT_URL:+--endpoint-url "${S3_ENDPOINT_URL}"}
    ;;
  file://*|/*|.*|[a-zA-Z]*)
    STORE_PATH=${TRACE_STORE_URL#file://}
    if [ -d "${STORE_PATH}" ]; then
      tar -C "${STORE_PATH}" -czf "${BACKUP_DIR}/traces.tar.gz" .
    else
      echo "trace store path ${STORE_PATH} does not exist; skipping" >&2
    fi
    ;;
esac

{
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "trace_store_url=${TRACE_STORE_URL}"
} > "${BACKUP_DIR}/manifest.txt"
echo "backup complete: ${BACKUP_DIR}"
