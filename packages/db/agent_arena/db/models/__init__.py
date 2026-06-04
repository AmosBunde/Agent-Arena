"""ORM models for the M1 schema subset.

Importing this package registers every table on ``agent_arena.db.metadata``.
The Alembic environment imports it for exactly that side effect.
"""

from __future__ import annotations

from agent_arena.db.models.catalog import (
    Agent,
    ApiToken,
    AuditLogEntry,
    Pricing,
    Provider,
    Rubric,
    Task,
)
from agent_arena.db.models.runs import Attempt, Run, RunGroup
from agent_arena.db.models.traces import TraceMetadata

__all__ = [
    "Agent",
    "ApiToken",
    "AuditLogEntry",
    "Attempt",
    "Pricing",
    "Provider",
    "Rubric",
    "Run",
    "RunGroup",
    "Task",
    "TraceMetadata",
]
