"""Percentile bootstrap confidence intervals for leaderboard cells.

95 percent intervals on accuracy and cost-per-correct-answer via the
percentile bootstrap, 1000 resamples by default (issue #23). The random
stream is seeded from the cell key, so the same samples always produce the
same interval: reproducibility is a platform property (ADR-0003 spirit),
and a scheduled recomputation must not make the leaderboard jitter.

CPCA is undefined for a resample with zero correct answers (ADR-0004). A
cell whose resamples are mostly undefined has no meaningful CPCA interval;
below the defined-resample threshold the interval is None and the UI shows
the point estimate alone.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from decimal import Decimal

DEFAULT_RESAMPLES = 1000
CONFIDENCE = 0.95
# Fraction of resamples that must have a defined CPCA for the interval to
# be reported at all.
MIN_DEFINED_FRACTION = 0.5


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    accuracy: float
    accuracy_ci_low: float
    accuracy_ci_high: float
    cpca: Decimal | None
    cpca_ci_low: Decimal | None
    cpca_ci_high: Decimal | None
    resamples: int


def bootstrap_cell(
    samples: list[tuple[Decimal, bool]],
    *,
    seed_key: str,
    resamples: int = DEFAULT_RESAMPLES,
) -> BootstrapResult:
    """Bootstrap one leaderboard cell from (cost, is_correct) samples."""
    if not samples:
        raise ValueError("bootstrap requires at least one sample")

    count = len(samples)
    correct_total = sum(1 for _, correct in samples if correct)
    cost_total = sum((cost for cost, _ in samples), Decimal("0"))
    accuracy = correct_total / count
    cpca = (cost_total / correct_total) if correct_total else None

    rng = random.Random(_seed_from_key(seed_key))
    accuracy_samples: list[float] = []
    cpca_samples: list[Decimal] = []
    for _ in range(resamples):
        resample = [samples[rng.randrange(count)] for _ in range(count)]
        resample_correct = sum(1 for _, correct in resample if correct)
        accuracy_samples.append(resample_correct / count)
        if resample_correct:
            resample_cost = sum((cost for cost, _ in resample), Decimal("0"))
            cpca_samples.append(resample_cost / resample_correct)

    accuracy_low, accuracy_high = _percentile_interval(sorted(accuracy_samples))
    cpca_low: Decimal | None = None
    cpca_high: Decimal | None = None
    if cpca is not None and len(cpca_samples) >= resamples * MIN_DEFINED_FRACTION:
        cpca_low, cpca_high = _percentile_interval(sorted(cpca_samples))

    return BootstrapResult(
        accuracy=accuracy,
        accuracy_ci_low=accuracy_low,
        accuracy_ci_high=accuracy_high,
        cpca=cpca,
        cpca_ci_low=cpca_low,
        cpca_ci_high=cpca_high,
        resamples=resamples,
    )


def _seed_from_key(seed_key: str) -> int:
    return int.from_bytes(hashlib.sha256(seed_key.encode("utf-8")).digest()[:8], "big")


def _percentile_interval[T: (float, Decimal)](ordered: list[T]) -> tuple[T, T]:
    alpha = (1.0 - CONFIDENCE) / 2.0
    low_index = int(alpha * (len(ordered) - 1))
    high_index = int((1.0 - alpha) * (len(ordered) - 1))
    return ordered[low_index], ordered[high_index]
