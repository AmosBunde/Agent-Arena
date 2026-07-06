# Backup and restore

Two state stores need protecting (ADR-0005): Postgres, which holds the
catalog, runs, trace metadata, and scores, and the object store, which holds
the immutable trace bodies. Redis holds no durable state and is never backed
up.

## Taking a backup

```bash
DATABASE_URL=postgresql+psycopg://arena:arena@localhost:5432/arena \
TRACE_STORE_URL=s3://arena-traces \
S3_ENDPOINT_URL=http://localhost:9000 \
scripts/backup.sh /backups/arena-$(date +%Y%m%d)
```

The script writes:

- `postgres.dump`: a pg_dump custom format archive of the whole database.
- `traces/` (S3 stores) or `traces.tar.gz` (local filesystem stores): every
  trace body, keyed exactly as stored.
- `manifest.txt`: timestamp and source configuration.

For the Compose deployment, run the script from the host with the published
Postgres port, or set `PG_DUMP` to run the client from a container:

```bash
PG_DUMP="docker run --rm --network host postgres:16 pg_dump" \
  scripts/backup.sh /backups/arena
```

## Restoring

```bash
DATABASE_URL=... TRACE_STORE_URL=... scripts/restore.sh /backups/arena-20260706
```

The database restore drops and recreates objects from the dump
(`--clean --if-exists`), so point it at the deployment you intend to
overwrite. Trace bodies are content addressed and immutable, so restoring
them over an existing store never conflicts: identical keys carry identical
bytes.

## Round trip guarantee

The integration suite proves the round trip: it seeds the database and the
trace store, backs up, wipes both, restores, and asserts every row and
every body byte survives. See tests/backup/test_backup_roundtrip.py.

## What to schedule

- Nightly `scripts/backup.sh` to a directory that rotates (seven dailies,
  four weeklies is a sane start).
- Object stores with versioning enabled (the Terraform modules enable it)
  additionally protect against accidental deletion between backups.
- Test the restore quarterly against a scratch database; a backup that has
  never been restored is a hope, not a backup.
