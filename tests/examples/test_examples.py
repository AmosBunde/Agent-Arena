"""Acceptance tests for issue #14.

Every example task and rubric parses against the runner contracts, every
rubric scores its tasks' reference outputs correctly, and the tasks load
through the API.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from apps.runner.contracts import RubricDefinition, TaskDefinition
from apps.runner.scoring import score_answer
from apps.runner.tools import tool_specs

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_FILES = sorted((REPO_ROOT / "tasks").rglob("*.yaml"))
RUBRIC_FILES = sorted((REPO_ROOT / "rubrics").rglob("*.yaml"))


def _load(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return yaml.safe_load(handle)


def test_expected_example_files_exist() -> None:
    assert [path.name for path in TASK_FILES] == [
        "word-problems-1.yaml",
        "word-problems-2.yaml",
        "word-problems-3.yaml",
        "calculator-1.yaml",
        "search-1.yaml",
    ]
    assert [path.name for path in RUBRIC_FILES] == [
        "exact-match.yaml",
        "json-key-match.yaml",
        "regex-match.yaml",
    ]


@pytest.mark.parametrize("path", TASK_FILES, ids=lambda p: p.stem)
def test_task_files_satisfy_contracts(path: Path) -> None:
    raw = _load(path)
    for field in ("slug", "version", "domain", "definition", "recommended_rubric", "examples"):
        assert field in raw, f"{path.name} misses {field}"
    definition = TaskDefinition.parse(raw["definition"])
    if definition.tools:
        tool_specs(definition.tools)
        assert "tool_calling" in raw.get("capabilities_required", [])
    assert raw["examples"]["correct"] is not None
    assert raw["examples"]["incorrect"] is not None


@pytest.mark.parametrize("path", RUBRIC_FILES, ids=lambda p: p.stem)
def test_rubric_files_satisfy_contracts(path: Path) -> None:
    raw = _load(path)
    assert raw["judge_required"] is False
    RubricDefinition.parse(raw["definition"])


def test_rubrics_score_reference_outputs_correctly() -> None:
    rubrics = {
        path.stem: RubricDefinition.parse(_load(path)["definition"]) for path in RUBRIC_FILES
    }
    for path in TASK_FILES:
        raw = _load(path)
        task = TaskDefinition.parse(raw["definition"])
        rubric = rubrics[raw["recommended_rubric"]]
        correct = score_answer(rubric, task, str(raw["examples"]["correct"]))
        incorrect = score_answer(rubric, task, str(raw["examples"]["incorrect"]))
        assert correct.is_correct, f"{path.name}: reference correct output scored incorrect"
        assert not incorrect.is_correct, f"{path.name}: reference incorrect output scored correct"


@pytest.mark.integration
def test_examples_load_via_api(database_url: str) -> None:
    import os

    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from apps.api.db import get_session
    from apps.api.main import create_app
    from apps.api.settings import ApiSettings
    from tests.conftest import REPO_ROOT as ROOT

    os.environ["DATABASE_URL"] = database_url
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_session():  # type: ignore[no-untyped-def]
        async with factory() as session:
            yield session

    app = create_app(
        ApiSettings(
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            default_role="admin",
            default_user="local",
        )
    )
    app.dependency_overrides[get_session] = override_session

    # Version suffix keeps reruns against a shared container conflict-free.
    version = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
        for path in TASK_FILES:
            raw = _load(path)
            response = client.post(
                "/api/v1/tasks",
                json={
                    "slug": raw["slug"],
                    "version": version,
                    "domain": raw["domain"],
                    "definition": raw["definition"],
                    "capabilities_required": raw.get("capabilities_required", []),
                },
            )
            assert response.status_code == 201, f"{path.name}: {response.text}"
        for path in RUBRIC_FILES:
            raw = _load(path)
            definition = {**raw["definition"], "example_version": version}
            response = client.post(
                "/api/v1/rubrics",
                json={
                    "slug": raw["slug"],
                    "version": version,
                    "definition": definition,
                    "judge_required": raw["judge_required"],
                },
            )
            assert response.status_code == 201, f"{path.name}: {response.text}"
        listed = client.get("/api/v1/tasks", params={"limit": 200}).json()
        slugs = {row["slug"] for row in listed if row["version"] == version}
        assert {"word-problems-1", "calculator-1", "search-1"} <= slugs
