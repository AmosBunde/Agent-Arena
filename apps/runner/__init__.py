"""Agent Arena runner service.

Celery workers that execute agent runs: capability negotiation, the
sequential agent loop, trace capture, run status transitions, and
synchronous scoring for deterministic rubrics. See
docs/design/system-design.md and issue #8.
"""
