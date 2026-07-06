"""Round-trip acceptance test for issue #29.

Seeds Postgres and a local trace store, backs up, wipes both, restores, and
asserts every row and body survives byte for byte. Uses the real scripts;
pg_dump and pg_restore run from a postgres:16 container when the host lacks
the client tools.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from agent_arena.trace_store import LocalTraceStore
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration

BODY = b'{"final_answer":"42","steps":[]}'
HASH = "fe" + "3" * 62


def _pg_tool(name: str) -> str:
    if shutil.which(name):
        return name
    return f"docker run --rm --network host -i postgres:16 {name}"


def _run_script(script: str, backup_dir: Path, env: dict[str, str]) -> None:
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / script), str(backup_dir)],
        check=True,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


def test_backup_restore_round_trip(database_url: str, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = database_url
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    # Seed one catalog row and one trace body.
    from agent_arena.db.models import Task

    slug = f"backup-{uuid.uuid4().hex[:8]}"
    with session_factory() as session:
        session.add(Task(slug=slug, version="1", domain="math", definition={"prompt": "p"}))
        session.commit()

    store_dir = tmp_path / "traces"
    store = LocalTraceStore(store_dir)
    store.put(HASH, BODY)

    backup_dir = tmp_path / "backup"
    env = {
        "DATABASE_URL": database_url,
        "TRACE_STORE_URL": str(store_dir),
        "PG_DUMP": _pg_tool("pg_dump"),
        "PG_RESTORE": _pg_tool("pg_restore"),
    }
    _run_script("backup.sh", backup_dir, env)
    assert (backup_dir / "postgres.dump").stat().st_size > 0
    assert (backup_dir / "traces.tar.gz").exists()
    assert (backup_dir / "manifest.txt").exists()

    # Wipe both stores.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for schema in ("aggregates", "traces", "runs", "catalog"):
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    shutil.rmtree(store_dir)

    _run_script("restore.sh", backup_dir, env)

    with session_factory() as session:
        restored = session.execute(
            text("SELECT slug FROM catalog.tasks WHERE slug = :slug"), {"slug": slug}
        ).scalar_one()
        assert restored == slug
    assert LocalTraceStore(store_dir).get(HASH) == BODY

    engine.dispose()
