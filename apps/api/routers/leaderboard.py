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

from agent_arena.db.leaderboard import leaderboard_with_ci_query, refresh_statement
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import Principal, get_principal
from apps.api.db import get_session
from apps.api.schemas import LeaderboardRowOut

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
