"""Shared fixtures for the test suite.

One Postgres 16 container per test session for integration tests. Every test
is self-contained: it migrates to the state it needs before asserting, so
tests do not depend on execution order across modules sharing the container.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# Make the namespace packages and the apps importable even without an
# editable install.
for _path in ("packages/db", "packages/adapters", "packages/cost-models", "."):
    sys.path.insert(0, str(REPO_ROOT / _path))


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - dev dependency missing
        pytest.skip("testcontainers is not installed")

    try:
        with PostgresContainer("postgres:16", driver="psycopg") as postgres:
            yield postgres.get_connection_url()
    except Exception as exc:  # pragma: no cover - Docker unavailable
        pytest.skip(f"could not start Postgres container: {exc}")


@pytest.fixture()
def alembic_config(database_url: str) -> Any:
    from alembic.config import Config

    os.environ["DATABASE_URL"] = database_url
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config
