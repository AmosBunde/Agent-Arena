"""Contract tests for issue #30: API tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.db import get_session
from apps.api.main import create_app
from apps.api.settings import ApiSettings

pytestmark = pytest.mark.integration

VIEWER = {"X-Forwarded-User": "alice", "X-Forwarded-User-Role": "viewer"}


@pytest.fixture(scope="module")
def migrated_url(database_url: str) -> str:
    import os

    from alembic import command
    from alembic.config import Config

    from tests.conftest import REPO_ROOT

    os.environ["DATABASE_URL"] = database_url
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


@pytest.fixture(scope="module")
def client(migrated_url: str):  # type: ignore[no-untyped-def]
    engine = create_async_engine(migrated_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_session():  # type: ignore[no-untyped-def]
        async with factory() as session:
            yield session

    app = create_app(
        ApiSettings(
            database_url=migrated_url,
            redis_url="redis://localhost:6379/0",
            default_role="admin",
            default_user="local",
        )
    )
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_shows_token_once_and_list_hides_it(client: TestClient) -> None:
    name = f"ci-{uuid.uuid4().hex[:6]}"
    created = client.post("/api/v1/tokens", json={"name": name, "role": "viewer"})
    assert created.status_code == 201
    body = created.json()
    assert body["token"].startswith("arena_")
    assert body["prefix"] in body["token"]

    listed = client.get("/api/v1/tokens").json()
    row = next(item for item in listed if item["name"] == name)
    assert "token" not in row
    assert "hash" not in row
    assert row["prefix"] == body["prefix"]


def test_created_token_authenticates_with_its_role(client: TestClient) -> None:
    created = client.post(
        "/api/v1/tokens", json={"name": f"runner-{uuid.uuid4().hex[:6]}", "role": "runner"}
    ).json()
    token = created["token"]

    # A runner token reads and may attempt runner operations, and its
    # identity is the token name.
    assert client.get("/api/v1/tasks", headers=_bearer(token)).status_code == 200
    payload = {"slug": "t", "version": "1", "domain": "x", "definition": {"prompt": "p"}}
    denied = client.post("/api/v1/tasks", json=payload, headers=_bearer(token))
    assert denied.status_code == 403

    # Admin-only token management is refused to a runner token.
    assert client.get("/api/v1/tokens", headers=_bearer(token)).status_code == 403


def test_garbage_token_is_401_not_header_fallback(client: TestClient) -> None:
    assert client.get("/api/v1/tokens", headers=_bearer("arena_dead_beef")).status_code == 401
    assert client.get("/api/v1/tokens", headers=_bearer("not-even-shaped")).status_code == 401


def test_revocation_takes_effect_immediately(client: TestClient) -> None:
    created = client.post(
        "/api/v1/tokens", json={"name": f"revoke-{uuid.uuid4().hex[:6]}", "role": "viewer"}
    ).json()
    token = created["token"]
    assert client.get("/api/v1/tasks", headers=_bearer(token)).status_code == 200

    revoked = client.delete(f"/api/v1/tokens/{created['id']}")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None

    assert client.get("/api/v1/tasks", headers=_bearer(token)).status_code == 401


def test_expired_token_is_rejected(client: TestClient) -> None:
    expiry = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    created = client.post(
        "/api/v1/tokens",
        json={"name": f"expired-{uuid.uuid4().hex[:6]}", "role": "viewer", "expires_at": expiry},
    ).json()
    assert client.get("/api/v1/tasks", headers=_bearer(created["token"])).status_code == 401


def test_token_management_requires_admin(client: TestClient) -> None:
    assert client.get("/api/v1/tokens", headers=VIEWER).status_code == 403
    assert (
        client.post(
            "/api/v1/tokens", json={"name": "x", "role": "viewer"}, headers=VIEWER
        ).status_code
        == 403
    )


def test_unknown_role_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/tokens", json={"name": "x", "role": "root"}).status_code == 422
