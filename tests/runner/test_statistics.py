"""Unit tests for the percentile bootstrap (issue #23)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.runner.statistics import bootstrap_cell

CENT = Decimal("0.010000")


def _samples(correct: int, incorrect: int) -> list[tuple[Decimal, bool]]:
    return [(CENT, True)] * correct + [(CENT, False)] * incorrect


def test_deterministic_for_the_same_seed_key() -> None:
    samples = _samples(3, 5)
    first = bootstrap_cell(samples, seed_key="cell-a", resamples=200)
    second = bootstrap_cell(samples, seed_key="cell-a", resamples=200)
    assert first == second


def test_different_seed_keys_differ() -> None:
    samples = _samples(3, 5)
    a = bootstrap_cell(samples, seed_key="cell-a", resamples=200)
    b = bootstrap_cell(samples, seed_key="cell-b", resamples=200)
    assert (a.accuracy_ci_low, a.accuracy_ci_high) != (b.accuracy_ci_low, b.accuracy_ci_high)


def test_all_correct_has_degenerate_interval() -> None:
    result = bootstrap_cell(_samples(6, 0), seed_key="k", resamples=200)
    assert result.accuracy == 1.0
    assert result.accuracy_ci_low == 1.0
    assert result.accuracy_ci_high == 1.0
    assert result.cpca == CENT
    assert result.cpca_ci_low == CENT
    assert result.cpca_ci_high == CENT


def test_interval_brackets_the_point_estimate() -> None:
    result = bootstrap_cell(_samples(4, 4), seed_key="k", resamples=1000)
    assert result.accuracy == 0.5
    assert result.accuracy_ci_low <= 0.5 <= result.accuracy_ci_high
    assert result.accuracy_ci_low < result.accuracy_ci_high
    assert result.cpca is not None
    assert result.cpca_ci_low is not None and result.cpca_ci_high is not None
    assert result.cpca_ci_low <= result.cpca <= result.cpca_ci_high


def test_zero_correct_has_no_cpca() -> None:
    result = bootstrap_cell(_samples(0, 5), seed_key="k", resamples=200)
    assert result.cpca is None
    assert result.cpca_ci_low is None and result.cpca_ci_high is None
    assert result.accuracy == 0.0


def test_single_sample_cell() -> None:
    result = bootstrap_cell(_samples(1, 0), seed_key="k", resamples=100)
    assert result.accuracy == 1.0
    assert result.cpca == CENT


def test_empty_cell_rejected() -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        bootstrap_cell([], seed_key="k")


@pytest.mark.integration
def test_compute_leaderboard_cis_upserts_cells(session_factory) -> None:  # type: ignore[no-untyped-def]
    from agent_arena.adapters import AdapterRegistry
    from agent_arena.db.models import LeaderboardCi
    from sqlalchemy import select

    from apps.runner.execution import compute_leaderboard_cis, execute_run_sync
    from tests.runner.fakes import FakeAdapter, response
    from tests.runner.test_execution import _seed_run

    adapter = FakeAdapter(responses=[response("42")])
    registry = AdapterRegistry()
    registry.register("fake", adapter)
    run_id = _seed_run(session_factory)
    outcome = execute_run_sync(run_id, session_factory=session_factory, registry=registry)
    assert outcome.run_status == "complete"

    updated = compute_leaderboard_cis(session_factory=session_factory, resamples=100)
    assert updated >= 1

    with session_factory() as session:
        rows = session.execute(select(LeaderboardCi)).scalars().all()
        matching = [row for row in rows if row.resamples == 100]
        assert matching, "expected at least one cell computed with the test resample count"
        cell = matching[0]
        assert Decimal("0") <= cell.accuracy <= Decimal("1")
        assert cell.accuracy_ci_low <= cell.accuracy <= cell.accuracy_ci_high

    # Idempotent: a second computation merges rather than duplicating.
    assert compute_leaderboard_cis(session_factory=session_factory, resamples=100) == updated
