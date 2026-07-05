"""Per-task contamination flag.

Adds ``catalog.tasks.contamination`` (JSONB, nullable): the stored result of
the contamination check from issue #25. NULL means never checked. Expand
only; no contract step needed.

Revision ID: 0004_task_contamination
Revises: 0003_leaderboard_ci
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_task_contamination"
down_revision: str | None = "0003_leaderboard_ci"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("contamination", postgresql.JSONB(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("tasks", "contamination", schema="catalog")
