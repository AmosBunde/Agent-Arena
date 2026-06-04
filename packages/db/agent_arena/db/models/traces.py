"""``traces`` schema: trace metadata.

Trace bodies live in object storage (ADR-0003); this table holds the indexed
metadata. In the M1 subset ``body_uri`` is nullable because the content-
addressed trace store does not exist yet (it lands in M2, issue #16). The
column is tightened to ``NOT NULL`` then, via the expand-contract pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from agent_arena.db.base import Base
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

_SCHEMA = "traces"


class TraceMetadata(Base):
    __tablename__ = "trace_metadata"
    __table_args__ = (
        Index("traces_run_idx", "run_id"),
        Index("traces_created_at_idx", text("created_at DESC")),
        {"schema": _SCHEMA},
    )

    hash: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Nullable in M1 only; see module docstring.
    body_uri: Mapped[str | None] = mapped_column(Text)
    body_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_cached_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
