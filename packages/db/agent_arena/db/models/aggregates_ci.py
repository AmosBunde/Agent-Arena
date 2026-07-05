"""``aggregates.leaderboard_ci``: bootstrap intervals per leaderboard cell.

Upserted by the scheduled statistics job (issue #23); read by the
leaderboard endpoint, which joins it onto the materialised view.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from agent_arena.db.base import Base
from sqlalchemy import DateTime, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

_SCHEMA = "aggregates"


class LeaderboardCi(Base):
    __tablename__ = "leaderboard_ci"
    __table_args__ = ({"schema": _SCHEMA},)

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    rubric_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    accuracy: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    accuracy_ci_low: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    accuracy_ci_high: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    cpca_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cpca_ci_low_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cpca_ci_high_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    resamples: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
