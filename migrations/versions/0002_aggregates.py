"""Aggregates schema: scores and the leaderboard materialised view.

Creates the ``aggregates`` schema deferred from the M1 subset (0001): the
``scores`` table and the ``leaderboard`` materialised view with
cost-per-correct-answer as defined in ADR-0004 (NULL when a group has zero
correct answers). The unique index on the view enables
``REFRESH MATERIALIZED VIEW CONCURRENTLY``. The view SQL mirrors
docs/design/database-schema.md.

Revision ID: 0002_aggregates
Revises: 0001_m1_subset
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_aggregates"
down_revision: str | None = "0001_m1_subset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "aggregates"

_LEADERBOARD_SQL = """
CREATE MATERIALIZED VIEW aggregates.leaderboard AS
SELECT
    r.agent_id,
    r.task_id,
    r.provider,
    r.model,
    s.rubric_hash,
    COUNT(*) FILTER (WHERE s.is_correct)                              AS correct_count,
    COUNT(*)                                                          AS total_count,
    AVG(s.score)::numeric(6, 4)                                       AS mean_score,
    SUM(t.estimated_cost_usd)::numeric(12, 6)                         AS total_cost_usd,
    CASE WHEN COUNT(*) FILTER (WHERE s.is_correct) = 0
         THEN NULL
         ELSE (SUM(t.estimated_cost_usd) /
               COUNT(*) FILTER (WHERE s.is_correct))::numeric(12, 6)
    END                                                               AS cost_per_correct_usd,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY t.latency_ms)        AS p50_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY t.latency_ms)        AS p95_latency_ms
FROM runs.runs r
JOIN runs.attempts a            ON a.run_id      = r.id
JOIN traces.trace_metadata t    ON t.attempt_id  = a.id
JOIN aggregates.scores s        ON s.trace_hash  = t.hash
WHERE r.status = 'complete'
GROUP BY r.agent_id, r.task_id, r.provider, r.model, s.rubric_hash
"""


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(_SCHEMA))

    op.create_table(
        "scores",
        sa.Column("trace_hash", sa.Text(), nullable=False),
        sa.Column("rubric_hash", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(6, 4), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("score_detail", postgresql.JSONB(), nullable=False),
        sa.Column("judge_model", sa.Text(), nullable=True),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("trace_hash", "rubric_hash", name="scores_pkey"),
        sa.ForeignKeyConstraint(
            ["trace_hash"],
            ["traces.trace_metadata.hash"],
            name="scores_trace_hash_fkey",
            ondelete="CASCADE",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "scores_rubric_correct_idx",
        "scores",
        ["rubric_hash", "is_correct"],
        schema=_SCHEMA,
    )

    op.execute(_LEADERBOARD_SQL)
    op.execute(
        "CREATE UNIQUE INDEX leaderboard_pk_idx ON aggregates.leaderboard "
        "(agent_id, task_id, provider, model, rubric_hash)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW aggregates.leaderboard")
    op.drop_table("scores", schema=_SCHEMA)
    op.execute(sa.schema.DropSchema(_SCHEMA))
