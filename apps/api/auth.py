"""Authorisation per session-design.md.

The API implements no login flow: an auth proxy owns identity and sends
``X-Forwarded-User`` and ``X-Forwarded-User-Role``. Without the headers the
configured defaults apply (admin in Compose, viewer in fail-safe
deployments). Three roles: viewer < runner < admin.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

ROLE_ORDER = {"viewer": 0, "runner": 1, "admin": 2}


@dataclass(frozen=True, slots=True)
class Principal:
    user: str
    role: str

    def has_role(self, required: str) -> bool:
        return ROLE_ORDER.get(self.role, -1) >= ROLE_ORDER[required]


def get_principal(request: Request) -> Principal:
    settings = request.app.state.settings
    user = request.headers.get("X-Forwarded-User", settings.default_user)
    role = request.headers.get("X-Forwarded-User-Role", settings.default_role)
    if role not in ROLE_ORDER:
        raise HTTPException(status_code=403, detail=f"unknown role {role!r}")
    return Principal(user=user, role=role)


def require_role(required: str):  # noqa: ANN201 - FastAPI dependency factory
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
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
