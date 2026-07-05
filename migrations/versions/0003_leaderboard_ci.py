"""Bootstrap confidence intervals for leaderboard cells.

Creates ``aggregates.leaderboard_ci``: one row per leaderboard cell with 95
percent percentile bootstrap intervals on accuracy and CPCA (issue #23).
Rows are upserted by the scheduled statistics job; the leaderboard endpoint
joins them onto the materialised view.

Revision ID: 0003_leaderboard_ci
Revises: 0002_aggregates
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_leaderboard_ci"
down_revision: str | None = "0002_aggregates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "aggregates"


def upgrade() -> None:
    op.create_table(
        "leaderboard_ci",
        sa.Column("agent_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("rubric_hash", sa.Text(), nullable=False),
        sa.Column("accuracy", sa.Numeric(6, 4), nullable=False),
        sa.Column("accuracy_ci_low", sa.Numeric(6, 4), nullable=False),
        sa.Column("accuracy_ci_high", sa.Numeric(6, 4), nullable=False),
        sa.Column("cpca_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("cpca_ci_low_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("cpca_ci_high_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("resamples", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "agent_id",
            "task_id",
            "provider",
            "model",
            "rubric_hash",
            name="leaderboard_ci_pkey",
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("leaderboard_ci", schema=_SCHEMA)
