#!/usr/bin/env python3
"""End to end run throughput benchmark (issue #33).

Seeds a task, agent, and rubric through the API, creates N runs against the
mock provider, waits for every run to reach a terminal state, and reports
runs per minute. Exits nonzero when the measured throughput misses the
target or any run fails, so CI can gate on it. Standard library only.

  python scripts/benchmark.py --api-url http://127.0.0.1:8000 \\
      --runs 20 --target-per-minute 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid


def _request(method: str, url: str, payload: dict | None = None) -> dict | list:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-User": "benchmark",
            "X-Forwarded-User-Role": "admin",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--target-per-minute", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    base = args.api_url.rstrip("/")
    unique = uuid.uuid4().hex[:8]

    task = _request(
        "POST",
        f"{base}/api/v1/tasks",
        {
            "slug": f"benchmark-{unique}",
            "version": "1",
            "domain": "benchmark",
            "definition": {
                "prompt": "Benchmark task. Answer with exactly: 42",
                "expected": "42",
            },
        },
    )
    agent = _request(
        "POST",
        f"{base}/api/v1/agents",
        {"slug": f"benchmark-agent-{unique}", "version": "1", "definition": {}},
    )
    rubric = _request(
        "POST",
        f"{base}/api/v1/rubrics",
        {
            "slug": f"benchmark-rubric-{unique}",
            "version": "1",
            "definition": {"type": "exact_match", "salt": unique},
        },
    )

    start = time.monotonic()
    group = _request(
        "POST",
        f"{base}/api/v1/runs",
        {
            "task_id": task["id"],
            "agent_id": agent["id"],
            "rubric_id": rubric["id"],
            "providers": [{"provider": "mock", "model": "mock-1"} for _ in range(args.runs)],
        },
    )
    group_id = group["run_group_id"]
    print(f"created {args.runs} mock runs in group {group_id}")

    deadline = time.monotonic() + args.timeout_seconds
    while True:
        runs = _request("GET", f"{base}/api/v1/runs?run_group_id={group_id}&limit={args.runs}")
        states = [run["status"] for run in runs]
        terminal = [s for s in states if s in ("complete", "failed", "cancelled")]
        if len(terminal) == args.runs:
            break
        if time.monotonic() > deadline:
            print(f"timed out; states: {states}", file=sys.stderr)
            return 2
        time.sleep(1)

    elapsed = time.monotonic() - start
    failures = [run for run in runs if run["status"] != "complete"]
    per_minute = args.runs / (elapsed / 60)
    print(f"{args.runs} runs in {elapsed:.1f}s = {per_minute:.1f} runs/minute")
    if failures:
        for run in failures:
            print(f"run {run['id']}: {run['status']} ({run['failure_reason']})", file=sys.stderr)
        return 3
    if per_minute < args.target_per_minute:
        print(
            f"throughput {per_minute:.1f}/min misses the target {args.target_per_minute}/min",
            file=sys.stderr,
        )
        return 4
    print("target met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
