# API stability and versioning policy

This document is the stability guarantee for Agent Arena from v1.0 onward.
It is referenced from the README and from the contributor guide.

## Versioning scheme

Agent Arena follows semantic versioning (semver):

- **Major** (`X.0.0`): breaking changes to any stable surface listed below.
- **Minor** (`1.X.0`): backward compatible features. Cut monthly when there
  is anything to release; milestone boundaries usually align with minors.
- **Patch** (`1.0.X`): backward compatible fixes, cut as needed.

Release tags are `vX.Y.Z` on `main`. Every release carries a CHANGELOG
entry.

## The stability boundary

The stable surface is exactly:

1. **The HTTP API under `/api/v1`.** Paths, methods, request fields,
   response fields, and status codes. New optional request fields and new
   response fields may appear in minors; nothing is removed or changes
   meaning short of a major.
2. **The trace body schema** (`schema_version` field) and the canonical
   JSON rules in `agent_arena.schemas.trace_canonical`. A change to the
   canonicalisation rules changes every future hash and is therefore a
   major, with an ADR amendment (ADR-0003).
3. **The task, rubric, and agent definition contracts** documented in
   `apps/runner/contracts.py`. New optional fields in minors; anything
   else is a major.
4. **The database schema migration chain.** Migrations are append only;
   schema changes use expand and contract across releases
   (docs/design/database-schema.md).

Everything else is internal: Python package APIs under `packages/`, the
runner internals, the web UI, Compose and Helm internals, and any endpoint
outside `/api/v1`. Internal surfaces can change in any release.

## Deprecation policy

- A deprecated API element keeps working for at least one minor release
  after the release that deprecates it, and never disappears outside a
  major.
- Deprecations are announced in the CHANGELOG and, where possible, in the
  OpenAPI description of the affected element.
- Removals list their replacement in the CHANGELOG entry.

## What a breaking change requires

1. An issue describing the change and its migration path.
2. An ADR or ADR amendment when the change touches an architectural
   decision.
3. A major version bump and a CHANGELOG entry with the migration path.

## Pre-1.0 history

Versions before v1.0 carried no stability guarantee; this policy starts at
the v1.0 tag.
