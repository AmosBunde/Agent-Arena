"""Database layer for Agent Arena.

Exposes the declarative ``Base`` and shared ``metadata`` against which the
Alembic migrations are authored. Importing :mod:`agent_arena.db.models`
registers every table on ``metadata``.

See docs/adr/0005-database-architecture.md and docs/design/database-schema.md.
"""

from __future__ import annotations

from agent_arena.db.base import SCHEMAS, Base, metadata

__all__ = ["Base", "SCHEMAS", "metadata"]
