"""Ranking metrics and bootstrap confidence intervals.

Wins are a lower bound on relevance (lost bids are not public), so only recall-oriented metrics
are reported; precision is not claimed (DECISIONS, evaluation decisions).
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

import numpy as np


def recall_at_k(ranked: Sequence[Hashable], positives: AbstractSet[Hashable], k: int) -> float:
    if not positives:
        return float("nan")
    return len(set(ranked[:k]) & positives) / len(positives)


def ndcg_at_k(ranked: Sequence[Hashable], positives: AbstractSet[Hashable], k: int) -> float:
    if not positives:
        return float("nan")
    dcg = sum(1.0 / np.log2(i + 2) for i, item in enumerate(ranked[:k]) if item in positives)
    ideal = sum(1.0 / np.log2(i + 2) for i in range(min(k, len(positives))))
    return float(dcg / ideal)


def reciprocal_rank(ranked: Sequence[Hashable], positives: AbstractSet[Hashable]) -> float:
    for i, item in enumerate(ranked):
        if item in positives:
            return 1.0 / (i + 1)
    return 0.0


@dataclass(frozen=True)
class Estimate:
    mean: float
    lo: float
    hi: float
    n: int

    def fmt(self, digits: int = 3) -> str:
        if self.n == 0 or np.isnan(self.mean):
            return "—"
        return f"{self.mean:.{digits}f} [{self.lo:.{digits}f}, {self.hi:.{digits}f}]"


def bootstrap(values: Sequence[float], resamples: int, seed: int, alpha: float = 0.05) -> Estimate:
    """Mean with a percentile bootstrap CI, resampling units (companies) with replacement."""
    arr = np.asarray([v for v in values if not np.isnan(v)], dtype=float)
    if arr.size == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(resamples, arr.size))
    means = arr[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return Estimate(float(arr.mean()), float(lo), float(hi), int(arr.size))


def paired_bootstrap_diff(
    a: Sequence[float], b: Sequence[float], resamples: int, seed: int, alpha: float = 0.05
) -> Estimate:
    """Mean of (a - b) over the same units, with a bootstrap CI (for 'X beats Y' claims)."""
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if not (np.isnan(x) or np.isnan(y))]
    return bootstrap([x - y for x, y in pairs], resamples, seed, alpha)
