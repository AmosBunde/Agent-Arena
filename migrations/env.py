"""Alembic migration environment.

The target metadata is the shared ``agent_arena.db.metadata``; importing
``agent_arena.db.models`` registers every table on it. The database URL comes
from the ``DATABASE_URL`` environment variable so the same migrations run
unchanged against Compose, CI, and managed Postgres.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

import agent_arena.db.models  # noqa: F401  (registers tables on metadata)
from agent_arena.db import metadata as target_metadata
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic's own bookkeeping table lives in ``public``; the application schemas
# stay clean. ``include_schemas`` makes autogenerate aware of all namespaces.
_VERSION_TABLE_SCHEMA = "public"


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (``alembic upgrade --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=_VERSION_TABLE_SCHEMA,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=_VERSION_TABLE_SCHEMA,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
