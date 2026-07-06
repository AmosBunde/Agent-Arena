"""Authorisation per session-design.md.

Two auth primitives, checked in order:

1. **Bearer tokens** (``Authorization: Bearer arena_...``): long-lived
   API tokens for programmatic access, hashed with Argon2id at rest
   (issue #30). Verified against the database on every request, so
   revocation takes effect immediately. An invalid or revoked token is a
   401, never a silent fallback to header auth.
2. **Proxy headers** (``X-Forwarded-User`` and ``X-Forwarded-User-Role``):
   an auth proxy owns interactive identity. Without headers the configured
   defaults apply (admin in Compose, viewer in fail-safe deployments).

Three roles: viewer < runner < admin.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session

ROLE_ORDER = {"viewer": 0, "runner": 1, "admin": 2}


@dataclass(frozen=True, slots=True)
class Principal:
    user: str
    role: str

    def has_role(self, required: str) -> bool:
        return ROLE_ORDER.get(self.role, -1) >= ROLE_ORDER[required]


async def validate_presented_bearer(
    request: Request, session: AsyncSession = Depends(get_session)
) -> None:
    """App-level dependency: a presented bearer token must be live.

    Runs on every route, including open reads, so a revoked or expired
    token is a 401 everywhere the moment it is presented; credentials are
    never silently ignored. The verified principal is cached on the request
    so protected routes do not hash twice.
    """
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        from apps.api.tokens import authenticate_token

        token = await authenticate_token(session, authorization.removeprefix("Bearer "))
        if token is None:
            raise HTTPException(status_code=401, detail="invalid, expired, or revoked token")
        request.state.principal = Principal(user=f"token:{token.name}", role=token.role)


async def get_principal(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Principal:
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached

    settings = request.app.state.settings
    user = request.headers.get("X-Forwarded-User", settings.default_user)
    role = request.headers.get("X-Forwarded-User-Role", settings.default_role)
    if role not in ROLE_ORDER:
        raise HTTPException(status_code=403, detail=f"unknown role {role!r}")
    return Principal(user=user, role=role)


def require_role(required: str):  # noqa: ANN201 - FastAPI dependency factory
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has_role(required):
            raise HTTPException(
                status_code=403,
                detail=f"role {principal.role!r} may not perform this operation",
            )
        return principal

    return dependency


# Module-level dependency singletons (bugbear B008: no calls in defaults).
REQUIRE_VIEWER = require_role("viewer")
REQUIRE_RUNNER = require_role("runner")
REQUIRE_ADMIN = require_role("admin")
