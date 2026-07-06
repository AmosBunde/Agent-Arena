"""Audit trail writes (session-design.md, Audit trail).

Every state-changing operation records who did what to which resource. The
row is added to the caller's session and commits atomically with the
operation it describes.
"""

from __future__ import annotations

from typing import Any

from agent_arena.db.models import AuditLogEntry
from sqlalchemy.ext.asyncio import AsyncSession


def record_audit(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    resource: str,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLogEntry(
            actor=actor,
            operation=operation,
            resource=resource,
            payload=payload,
        )
    )
