"""Acceptance test for issue #2.

``alembic upgrade head`` on a fresh Postgres 16 produces the M1 schema, and
``alembic downgrade base`` reverses it cleanly. Runs against a real Postgres
container, so it is marked ``integration`` and skips when Docker is absent.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Make the namespace package importable even without an editable install.
sys.path.insert(0, str(REPO_ROOT / "packages" / "db"))

pytestmark = pytest.mark.integration

EXPECTED_TABLES: dict[str, set[str]] = {
    "catalog": {
        "tasks",
        "rubrics",
        "agents",
        "providers",
        "pricing",
        "api_tokens",
        "audit_log",
    },
    "runs": {"run_groups", "runs", "attempts"},
    "traces": {"trace_metadata"},
}


@pytest.fixture(scope="module")
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


def _alembic_config(url: str):  # type: ignore[no-untyped-def]
    from alembic.config import Config

    os.environ["DATABASE_URL"] = url
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_upgrade_head_then_downgrade_base(database_url: str) -> None:
    from alembic import command
    from sqlalchemy import create_engine, inspect

    config = _alembic_config(database_url)
    engine = create_engine(database_url)

    command.upgrade(config, "head")

    inspector = inspect(engine)
    schemas = set(inspector.get_schema_names())
    for schema, expected in EXPECTED_TABLES.items():
        assert schema in schemas, f"schema {schema!r} missing after upgrade"
        actual = set(inspector.get_table_names(schema=schema))
        assert expected <= actual, f"missing tables in {schema}: {expected - actual}"

    command.downgrade(config, "base")

    inspector = inspect(engine)
    remaining = set(inspector.get_schema_names())
    for schema in EXPECTED_TABLES:
        assert schema not in remaining, f"schema {schema!r} survived downgrade"

    engine.dispose()
