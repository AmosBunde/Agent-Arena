"""``aggregates`` schema: derived scoring data.

One ``scores`` row per (trace, rubric) pair; the same trace can be re-scored
under a new rubric without touching the original row. The leaderboard
materialised view over this table is defined in migration 0002 because
SQLAlchemy has no first-class materialised view construct; its read and
refresh helpers live in ``agent_arena.db.leaderboard``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from agent_arena.db.base import Base
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

_SCHEMA = "aggregates"


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        Index("scores_rubric_correct_idx", "rubric_hash", "is_correct"),
        {"schema": _SCHEMA},
    )

    trace_hash: Mapped[str] = mapped_column(
        Text,
        ForeignKey("traces.trace_metadata.hash", ondelete="CASCADE"),
        primary_key=True,
    )
    rubric_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    judge_model: Mapped[str | None] = mapped_column(Text)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
