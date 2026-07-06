"""API token generation and verification (issue #30, session-design.md).

Token format: ``arena_<prefix>_<secret>``. The prefix is stored in clear for
indexed lookup; the full token is hashed with Argon2id at rest and the
plaintext is shown exactly once at creation. Verification loads the row by
prefix and checks the hash, expiry, and revocation on every request, which
is what makes revocation take effect immediately.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_arena.db.models import ApiToken
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

TOKEN_NAMESPACE = "arena"

_hasher = PasswordHasher()


@dataclass(frozen=True, slots=True)
class IssuedToken:
    id: uuid.UUID
    value: str
    prefix: str


def generate_token() -> tuple[str, str, str]:
    """Return (plaintext value, prefix, argon2id hash)."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    value = f"{TOKEN_NAMESPACE}_{prefix}_{secret}"
    return value, prefix, _hasher.hash(value)


def parse_prefix(value: str) -> str | None:
    parts = value.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_NAMESPACE:
        return None
    return parts[1]


async def authenticate_token(session: AsyncSession, value: str) -> ApiToken | None:
    """Resolve a bearer token to a live ApiToken row, or None."""
    prefix = parse_prefix(value)
    if prefix is None:
        return None
    rows = (
        (await session.execute(select(ApiToken).where(ApiToken.prefix == prefix))).scalars().all()
    )
    now = datetime.now(UTC)
    for row in rows:
        if row.revoked_at is not None:
            continue
        if row.expires_at is not None and row.expires_at <= now:
            continue
        try:
            _hasher.verify(row.hash, value)
        except VerifyMismatchError:
            continue
        return row
    return None
