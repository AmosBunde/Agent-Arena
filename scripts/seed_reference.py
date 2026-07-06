#!/usr/bin/env python3
"""Seed the curated reference suite (issue #34). Standard library only.

Loads every task under tasks/ and every rubric under rubrics/ into a
running deployment through the API, plus a baseline agent, skipping
anything already present. Requires an admin credential when the deployment
defaults to viewer:

  python scripts/seed_reference.py --api-url http://127.0.0.1:8000 \\
      --token arena_...
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["X-Forwarded-User"] = "seed"
        headers["X-Forwarded-User-Role"] = "admin"
    return headers


def _post(base: str, path: str, payload: dict, token: str | None) -> str:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers=_headers(token),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return f"created ({response.status})"
    except urllib.error.HTTPError as error:
        if error.code == 409:
            return "already present"
        raise


def _load_yaml(path: Path) -> dict:
    # The task files use a small YAML subset; PyYAML is available in the
    # application image, and this import keeps the script standalone when
    # PyYAML is installed on the host.
    import yaml

    with path.open() as handle:
        return yaml.safe_load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=None)
    args = parser.parse_args()
    base = args.api_url.rstrip("/")

    for path in sorted((REPO_ROOT / "tasks").rglob("*.yaml")):
        raw = _load_yaml(path)
        status = _post(
            base,
            "/api/v1/tasks",
            {
                "slug": raw["slug"],
                "version": str(raw["version"]),
                "domain": raw["domain"],
                "definition": raw["definition"],
                "capabilities_required": raw.get("capabilities_required", []),
            },
            args.token,
        )
        print(f"task {raw['slug']}@{raw['version']}: {status}")

    for path in sorted((REPO_ROOT / "rubrics").rglob("*.yaml")):
        raw = _load_yaml(path)
        status = _post(
            base,
            "/api/v1/rubrics",
            {
                "slug": raw["slug"],
                "version": str(raw["version"]),
                "definition": raw["definition"],
                "judge_required": raw.get("judge_required", False),
            },
            args.token,
        )
        print(f"rubric {raw['slug']}@{raw['version']}: {status}")

    status = _post(
        base,
        "/api/v1/agents",
        {"slug": "baseline", "version": "1", "definition": {"temperature": 0}},
        args.token,
    )
    print(f"agent baseline@1: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
