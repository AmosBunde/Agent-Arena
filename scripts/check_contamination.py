#!/usr/bin/env python3
"""Contamination check CLI (issue #25).

Checks task prompts against local corpus snapshots and optionally stores the
per-task flag in the catalog.

Examples:

  # Report over the YAML task library, writing the markdown report.
  python scripts/check_contamination.py --tasks-dir tasks \\
      --corpus-dir /corpora --report docs/reports/contamination-m1.md

  # Also update catalog.tasks.contamination for matching slug and version.
  DATABASE_URL=... python scripts/check_contamination.py --tasks-dir tasks \\
      --corpus-dir /corpora --update-db
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
for _area in ("db",):
    sys.path.insert(0, str(REPO_ROOT / "packages" / _area))

import yaml  # noqa: E402

from apps.runner.contamination import check_prompt, load_corpora, render_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-dir", type=Path, default=REPO_ROOT / "tasks")
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--update-db", action="store_true")
    args = parser.parse_args()

    corpora = load_corpora(args.corpus_dir) if args.corpus_dir else {}
    results = []
    for path in sorted(args.tasks_dir.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        result = check_prompt(
            raw["definition"]["prompt"],
            corpora,
            slug=raw["slug"],
            version=str(raw["version"]),
        )
        results.append(result)
        print(f"{result.slug}@{result.version}: {result.status}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(results, corpora))
        print(f"report written to {args.report}")

    if args.update_db:
        from agent_arena.db.models import Task
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        url = os.environ.get("DATABASE_URL")
        if not url:
            print("DATABASE_URL is required with --update-db", file=sys.stderr)
            return 2
        engine = create_engine(url)
        with Session(engine) as session:
            for result in results:
                task = session.execute(
                    select(Task).where(Task.slug == result.slug, Task.version == result.version)
                ).scalar_one_or_none()
                if task is not None:
                    task.contamination = result.to_record()
            session.commit()
        engine.dispose()
        print("catalog updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
