"""Acceptance test for issue #2.

``alembic upgrade head`` on a fresh Postgres 16 produces the schema, and
``alembic downgrade base`` reverses it cleanly. Runs against a real Postgres
container, so it is marked ``integration`` and skips when Docker is absent.
"""

from __future__ import annotations

import pytest

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
    "aggregates": {"scores"},
}


def test_upgrade_head_then_downgrade_base(database_url: str, alembic_config) -> None:  # type: ignore[no-untyped-def]
    from alembic import command
    from sqlalchemy import create_engine, inspect

    engine = create_engine(database_url)

    command.upgrade(alembic_config, "head")

    inspector = inspect(engine)
    schemas = set(inspector.get_schema_names())
    for schema, expected in EXPECTED_TABLES.items():
        assert schema in schemas, f"schema {schema!r} missing after upgrade"
        actual = set(inspector.get_table_names(schema=schema))
        assert expected <= actual, f"missing tables in {schema}: {expected - actual}"

    command.downgrade(alembic_config, "base")

    inspector = inspect(engine)
    remaining = set(inspector.get_schema_names())
    for schema in EXPECTED_TABLES:
        assert schema not in remaining, f"schema {schema!r} survived downgrade"

    engine.dispose()
