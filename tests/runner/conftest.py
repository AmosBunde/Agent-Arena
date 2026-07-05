"""Shared database fixtures for runner integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def engine(database_url: str):  # type: ignore[no-untyped-def]
    import os

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from tests.conftest import REPO_ROOT

    os.environ["DATABASE_URL"] = database_url
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(engine):  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, expire_on_commit=False)
