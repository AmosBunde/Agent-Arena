"""API configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Environment-derived API configuration."""

    database_url: str
    redis_url: str
    # Role assumed when the auth proxy sends no role header. Compose is a
    # single-user local tool and defaults to admin; K8s deployments set
    # API_DEFAULT_ROLE=viewer (fail-safe). See session-design.md.
    default_role: str
    # Identity assumed when the auth proxy sends no user header.
    default_user: str

    @classmethod
    def from_env(cls) -> ApiSettings:
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://arena:arena@localhost:5432/arena",
            ),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            default_role=os.environ.get("API_DEFAULT_ROLE", "admin"),
            default_user=os.environ.get("API_DEFAULT_USER", "local"),
        )
