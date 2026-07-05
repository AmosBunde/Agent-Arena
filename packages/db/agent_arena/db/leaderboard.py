"""Leaderboard read side and refresh entry point.

The ``aggregates.leaderboard`` materialised view is created in migration
0002_aggregates from the SQL in docs/design/database-schema.md. This module
gives the scheduler its refresh entry point and the API its presentation
query. Cost-per-correct-answer semantics follow ADR-0004; the materialised
view decision is ADR-0005.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    MetaData,
    Numeric,
    Select,
    Table,
    Text,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Engine

# The scheduler refreshes the view on this interval (ADR-0005: five minutes).
REFRESH_INTERVAL_SECONDS = 300

# Deliberately NOT ``Base.metadata``: the migration environment autogenerates
# against the shared metadata, and registering the view there would make
# autogenerate emit a spurious ``create_table`` colliding with the
# materialised view. Keep this Table on its own MetaData.
_metadata = MetaData(schema="aggregates")

# Static description of the materialised view for query building. The
# authoritative definition is the migration; columns here must match it.
leaderboard = Table(
    "leaderboard",
    _metadata,
    Column("agent_id", UUID(as_uuid=True)),
    Column("task_id", UUID(as_uuid=True)),
    Column("provider", Text),
    Column("model", Text),
    Column("rubric_hash", Text),
    Column("correct_count", BigInteger),
    Column("total_count", BigInteger),
    Column("mean_score", Numeric(6, 4)),
    Column("total_cost_usd", Numeric(12, 6)),
    Column("cost_per_correct_usd", Numeric(12, 6)),
    Column("p50_latency_ms", Float),
    Column("p95_latency_ms", Float),
)


def refresh_leaderboard(engine: Engine, *, concurrently: bool = True) -> None:
    """Refresh the materialised view. Idempotent; safe to run on a schedule.

    A concurrent refresh does not block readers and requires the unique index
    from migration 0002. ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` cannot run
    inside a transaction block, so the statement executes on an autocommit
    connection.
    """
    keyword = " CONCURRENTLY" if concurrently else ""
    statement = text(f"REFRESH MATERIALIZED VIEW{keyword} aggregates.leaderboard")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(statement)


def leaderboard_query() -> Select[tuple[object, ...]]:
    """The leaderboard in presentation order.

    CPCA ascending with NULLs last per ADR-0004: a group with zero correct
    answers has no defined CPCA and sorts after every priced group. The
    governing documents specify only the CPCA sort; the remaining keys are a
    presentation-level decision (higher mean score, then lower total cost)
    with the view's unique key last so pagination is deterministic.
    """
    return select(leaderboard).order_by(
        leaderboard.c.cost_per_correct_usd.asc().nulls_last(),
        leaderboard.c.mean_score.desc(),
        leaderboard.c.total_cost_usd.asc(),
        leaderboard.c.agent_id,
        leaderboard.c.task_id,
        leaderboard.c.provider,
        leaderboard.c.model,
        leaderboard.c.rubric_hash,
    )
