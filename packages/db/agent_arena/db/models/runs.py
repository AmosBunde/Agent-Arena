"""``runs`` schema: run-scoped state.

Run groups, runs, and per-run attempts. See docs/design/database-schema.md
and docs/design/system-design.md for the run lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from agent_arena.db.base import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

_SCHEMA = "runs"

_RUN_STATUSES = ("pending", "queued", "running", "complete", "failed", "cancelled")
_ATTEMPT_OUTCOMES = (
    "success",
    "failed_provider_error",
    "failed_adapter_error",
    "failed_timeout",
    "skipped_unsupported",
)


def _in_clause(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class RunGroup(Base):
    __tablename__ = "run_groups"
    __table_args__ = ({"schema": _SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in_clause(_RUN_STATUSES)})", name="status"),
        Index("runs_group_idx", "run_group_id"),
        Index(
            "runs_status_idx",
            "status",
            postgresql_where=text("status IN ('pending', 'queued', 'running')"),
        ),
        Index("runs_finished_idx", text("finished_at DESC")),
        {"schema": _SCHEMA},
    )

    # No server-side default: the run id is allocated by the API when the run is
    # created so it can be returned to the caller before the row is committed.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.run_groups.id")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.agents.id"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.tasks.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.rubrics.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(f"outcome IN ({_in_clause(_ATTEMPT_OUTCOMES)})", name="outcome"),
        UniqueConstraint("run_id", "attempt_number"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    adapter_version: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
