"""Database access for the runner.

One synchronous engine per worker process, created lazily. The runner is
deliberately synchronous (system-design.md, Concurrency model).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.runner.settings import RunnerSettings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine(settings: RunnerSettings | None = None) -> Engine:
    global _engine
    if _engine is None:
        resolved = settings or RunnerSettings.from_env()
        _engine = create_engine(resolved.database_url, pool_pre_ping=True)
    return _engine


def get_session_factory(settings: RunnerSettings | None = None) -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(settings), expire_on_commit=False)
    return _session_factory
