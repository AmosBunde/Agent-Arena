"""M1 subset: catalog, runs, and traces schemas.

Creates the M1 portion of the schema described in docs/design/database-schema.md:
the ``catalog``, ``runs``, and ``traces`` namespaces. The ``aggregates`` schema
(scores and the leaderboard materialised view) is intentionally excluded; it
lands with issue #10. ``traces.trace_metadata.body_uri`` is nullable here
because the content-addressed trace store arrives in M2 (issue #16).

Revision ID: 0001_m1_subset
Revises:
Create Date: 2026-06-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_m1_subset"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMAS = ("catalog", "runs", "traces")


def upgrade() -> None:
    for schema in _SCHEMAS:
        op.execute(sa.schema.CreateSchema(schema))

    _create_catalog()
    _create_runs()
    _create_traces()


def downgrade() -> None:
    op.drop_table("trace_metadata", schema="traces")
    op.drop_table("attempts", schema="runs")
    op.drop_table("runs", schema="runs")
    op.drop_table("run_groups", schema="runs")
    op.drop_table("audit_log", schema="catalog")
    op.drop_table("api_tokens", schema="catalog")
    op.drop_table("pricing", schema="catalog")
    op.drop_table("providers", schema="catalog")
    op.drop_table("agents", schema="catalog")
    op.drop_table("rubrics", schema="catalog")
    op.drop_table("tasks", schema="catalog")

    for schema in reversed(_SCHEMAS):
        op.execute(sa.schema.DropSchema(schema))


def _create_catalog() -> None:
    op.create_table(
        "tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "capabilities_required",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="tasks_pkey"),
        sa.UniqueConstraint("slug", "version", name="tasks_slug_version_key"),
        schema="catalog",
    )
    op.create_index("tasks_domain_idx", "tasks", ["domain"], schema="catalog")

    op.create_table(
        "rubrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("definition_hash", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "judge_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="rubrics_pkey"),
        sa.UniqueConstraint("slug", "version", name="rubrics_slug_version_key"),
        sa.UniqueConstraint("definition_hash", name="rubrics_definition_hash_key"),
        schema="catalog",
    )

    op.create_table(
        "agents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="agents_pkey"),
        sa.UniqueConstraint("slug", "version", name="agents_slug_version_key"),
        schema="catalog",
    )

    op.create_table(
        "providers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "is_local", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="providers_pkey"),
        sa.UniqueConstraint("name", name="providers_name_key"),
        schema="catalog",
    )

    op.create_table(
        "pricing",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("prices", postgresql.JSONB(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pricing_pkey"),
        sa.UniqueConstraint(
            "provider", "model", "valid_from", name="pricing_provider_model_valid_from_key"
        ),
        schema="catalog",
    )
    op.create_index(
        "pricing_lookup_idx",
        "pricing",
        ["provider", "model", sa.text("valid_from DESC")],
        schema="catalog",
    )

    op.create_table(
        "api_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('viewer', 'runner', 'admin')", name="api_tokens_role_check"
        ),
        sa.PrimaryKeyConstraint("id", name="api_tokens_pkey"),
        schema="catalog",
    )
    op.create_index("api_tokens_prefix_idx", "api_tokens", ["prefix"], schema="catalog")

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="audit_log_pkey"),
        schema="catalog",
    )
    op.create_index(
        "audit_log_occurred_at_idx",
        "audit_log",
        [sa.text("occurred_at DESC")],
        schema="catalog",
    )
    op.create_index("audit_log_resource_idx", "audit_log", ["resource"], schema="catalog")


def _create_runs() -> None:
    op.create_table(
        "run_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="run_groups_pkey"),
        schema="runs",
    )

    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("rubric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', "
            "'complete', 'failed', 'cancelled')",
            name="runs_status_check",
        ),
        sa.PrimaryKeyConstraint("id", name="runs_pkey"),
        sa.ForeignKeyConstraint(
            ["run_group_id"],
            ["runs.run_groups.id"],
            name="runs_run_group_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["catalog.agents.id"], name="runs_agent_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["catalog.tasks.id"], name="runs_task_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["rubric_id"], ["catalog.rubrics.id"], name="runs_rubric_id_fkey"
        ),
        schema="runs",
    )
    op.create_index("runs_group_idx", "runs", ["run_group_id"], schema="runs")
    op.create_index(
        "runs_status_idx",
        "runs",
        ["status"],
        schema="runs",
        postgresql_where=sa.text("status IN ('pending', 'queued', 'running')"),
    )
    op.create_index(
        "runs_finished_idx", "runs", [sa.text("finished_at DESC")], schema="runs"
    )

    op.create_table(
        "attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('success', 'failed_provider_error', "
            "'failed_adapter_error', 'failed_timeout', 'skipped_unsupported')",
            name="attempts_outcome_check",
        ),
        sa.PrimaryKeyConstraint("id", name="attempts_pkey"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.runs.id"],
            name="attempts_run_id_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id", "attempt_number", name="attempts_run_id_attempt_number_key"
        ),
        schema="runs",
    )


def _create_traces() -> None:
    op.create_table(
        "trace_metadata",
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Nullable in M1; tightened to NOT NULL in M2 (issue #16).
        sa.Column("body_uri", sa.Text(), nullable=True),
        sa.Column(
            "body_size_bytes", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "total_input_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_output_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_cached_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(12, 6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "tool_call_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("hash", name="trace_metadata_pkey"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.runs.id"],
            name="trace_metadata_run_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["runs.attempts.id"],
            name="trace_metadata_attempt_id_fkey",
            ondelete="CASCADE",
        ),
        schema="traces",
    )
    op.create_index("traces_run_idx", "trace_metadata", ["run_id"], schema="traces")
    op.create_index(
        "traces_created_at_idx",
        "trace_metadata",
        [sa.text("created_at DESC")],
        schema="traces",
    )
