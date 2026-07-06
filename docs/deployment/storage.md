# Trace body storage in production

Trace bodies are canonical JSON, content addressed, and immutable
(ADR-0003). The metadata lives in Postgres; the bodies live in an object
store configured through `TRACE_STORE_URL`.

## Sizing

At an average of 50 KB per body, one million traces is roughly 50 GB. The
metadata table stays around 250 MB at that scale, so the object store is
the dominant storage cost.

## Recommendations

- **Compose**: the bundled MinIO with its volume is adequate for the
  canonical single machine deployment.
- **S3 and compatible stores**: enable versioning (the Terraform modules
  do) and add a lifecycle policy moving objects to an infrequent-access
  tier after 90 days. Bodies are immutable and read rarely after their
  first weeks, which is exactly the access pattern those tiers price for.
- **Never mutate or delete bodies** that scores still reference; the
  content hash is the identity the reproducibility guarantee rests on.
  Deletion is safe only for traces whose metadata rows are gone.

## Backups

`scripts/backup.sh` archives or syncs the store alongside the database
dump; see [Backup and restore](backup.md).
