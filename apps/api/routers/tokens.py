"""API token management endpoints (issue #30). Admin only.

The plaintext token appears exactly once, in the creation response; the
database stores the Argon2id hash and the prefix. Revocation sets
``revoked_at``, and because every bearer request re-verifies against the
row, it takes effect immediately.
"""

from __future__ import annotations

import uuid

from agent_arena.db.models import ApiToken
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.audit import record_audit
from apps.api.auth import REQUIRE_ADMIN, ROLE_ORDER, Principal
from apps.api.db import get_session
from apps.api.schemas import TokenCreatedOut, TokenIn, TokenOut
from apps.api.tokens import generate_token

router = APIRouter(prefix="/api/v1", tags=["tokens"])


@router.get("/tokens", response_model=list[TokenOut])
async def list_tokens(
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(REQUIRE_ADMIN),
) -> list[ApiToken]:
    result = await session.execute(select(ApiToken).order_by(ApiToken.created_at.desc()))
    return list(result.scalars().all())


@router.post("/tokens", response_model=TokenCreatedOut, status_code=201)
async def create_token(
    payload: TokenIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(REQUIRE_ADMIN),
) -> TokenCreatedOut:
    if payload.role not in ROLE_ORDER:
        raise HTTPException(status_code=422, detail=f"unknown role {payload.role!r}")
    value, prefix, digest = generate_token()
    token = ApiToken(
        name=payload.name,
        prefix=prefix,
        hash=digest,
        role=payload.role,
        created_by=principal.user,
        expires_at=payload.expires_at,
    )
    session.add(token)
    record_audit(
        session,
        actor=principal.user,
        operation="token.create",
        resource=f"token:{payload.name}",
        payload={"role": payload.role},
    )
    await session.commit()
    await session.refresh(token)
    return TokenCreatedOut(
        **TokenOut.model_validate(token).model_dump(),
        token=value,
    )


@router.delete("/tokens/{token_id}", response_model=TokenOut)
async def revoke_token(
    token_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(REQUIRE_ADMIN),
) -> ApiToken:
    from datetime import UTC, datetime

    token = await session.get(ApiToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="token not found")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        record_audit(
            session,
            actor=principal.user,
            operation="token.revoke",
            resource=f"token:{token.name}",
        )
        await session.commit()
        await session.refresh(token)
    return token
