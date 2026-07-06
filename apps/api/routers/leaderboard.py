"""Leaderboard endpoint.

Reads the materialised view through the presentation query from issue #10.
``?refresh=true`` triggers an immediate refresh before reading
(session-design.md, Caching) and requires the runner role, since it does
write-class work on the database. The refresh here is non-concurrent because
it runs inside the request transaction; the scheduler's five minute refresh
is the concurrent one. The Redis JSON cache layer is deferred with the M2
caching work; the view itself is the cache in M1.
"""

from __future__ import annotations

from decimal import Decimal

from agent_arena.db.leaderboard import (
    leaderboard_query,
    leaderboard_with_ci_query,
    refresh_statement,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import Principal, get_principal
from apps.api.db import get_session
from apps.api.pareto import ParetoPoint, front_keys
from apps.api.schemas import LeaderboardRowOut, ParetoRowOut

router = APIRouter(prefix="/api/v1", tags=["leaderboard"])


@router.get("/leaderboard", response_model=list[LeaderboardRowOut])
async def get_leaderboard(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
    refresh: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[LeaderboardRowOut]:
    if refresh:
        if not principal.has_role("runner"):
            raise HTTPException(
                status_code=403,
                detail="refresh requires the runner role",
            )
        await session.execute(refresh_statement(concurrently=False))
        await session.commit()
    result = await session.execute(leaderboard_with_ci_query().limit(limit).offset(offset))
    return [LeaderboardRowOut(**dict(row)) for row in result.mappings().all()]


@router.get("/leaderboard/pareto", response_model=list[ParetoRowOut])
async def get_pareto_front(
    session: AsyncSession = Depends(get_session),
) -> list[ParetoRowOut]:
    """The (cost, accuracy) view: dominated cells are marked, not hidden.

    Cost is mean dollars per task; accuracy is the pass rate. The UI dims
    dominated points (issue #24).
    """
    result = await session.execute(leaderboard_query())
    rows = result.mappings().all()
    points: list[ParetoPoint] = []
    prepared: list[dict[str, object]] = []
    for row in rows:
        key = (
            f"{row['agent_id']}:{row['task_id']}:{row['provider']}:"
            f"{row['model']}:{row['rubric_hash']}"
        )
        total = int(row["total_count"])
        accuracy = Decimal(row["correct_count"]) / Decimal(total)
        mean_cost = Decimal(row["total_cost_usd"]) / Decimal(total)
        points.append(ParetoPoint(key=key, mean_cost_usd=mean_cost, accuracy=accuracy))
        prepared.append(
            {
                "key": key,
                "agent_id": row["agent_id"],
                "task_id": row["task_id"],
                "provider": row["provider"],
                "model": row["model"],
                "rubric_hash": row["rubric_hash"],
                "correct_count": row["correct_count"],
                "total_count": row["total_count"],
                "accuracy": accuracy,
                "mean_cost_usd": mean_cost,
                "cost_per_correct_usd": row["cost_per_correct_usd"],
            }
        )
    front = front_keys(points)
    output = [
        ParetoRowOut(
            **{k: v for k, v in item.items() if k != "key"},  # type: ignore[arg-type]
            on_front=item["key"] in front,
        )
        for item in prepared
    ]
    # Front first, then by cost, so the reading order matches the tradeoff.
    output.sort(key=lambda row: (not row.on_front, row.mean_cost_usd))
    return output
