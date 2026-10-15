"""Ranking metrics, bootstrap, company split."""

from __future__ import annotations

import math

import numpy as np
import pytest

from avant_offre.eval.metrics import (
    bootstrap,
    ndcg_at_k,
    paired_bootstrap_diff,
    recall_at_k,
    reciprocal_rank,
)
from avant_offre.eval.splits import company_split


def test_recall() -> None:
    assert recall_at_k([1, 2, 3, 4], {2, 9}, 2) == 0.5
    assert recall_at_k([1, 2, 3, 4], {2, 9}, 10) == 0.5
    assert math.isnan(recall_at_k([1], set(), 1))


def test_ndcg_known_values() -> None:
    assert ndcg_at_k([1, 2, 3], {1}, 3) == pytest.approx(1.0)
    assert ndcg_at_k([2, 1, 3], {1}, 3) == pytest.approx(1 / np.log2(3))
    # two positives at ranks 1 and 3: (1 + 1/log2(4)) / (1 + 1/log2(3))
    assert ndcg_at_k([1, 9, 2], {1, 2}, 3) == pytest.approx((1 + 0.5) / (1 + 1 / np.log2(3)))


def test_mrr() -> None:
    assert reciprocal_rank([5, 6, 7], {7}) == pytest.approx(1 / 3)
    assert reciprocal_rank([5, 6], {7}) == 0.0


def test_bootstrap_is_seeded_and_brackets_mean() -> None:
    vals = [0.1, 0.4, 0.5, 0.9, 0.2, 0.3]
    a = bootstrap(vals, 500, seed=1)
    b = bootstrap(vals, 500, seed=1)
    assert a == b
    assert a.lo <= a.mean <= a.hi
    assert a.n == 6
    assert bootstrap([], 10, 1).n == 0


def test_paired_difference() -> None:
    d = paired_bootstrap_diff([1.0, 1.0, 1.0], [0.0, 0.0, 0.0], 100, 3)
    assert d.mean == 1.0 and d.lo == 1.0


def test_company_split_is_deterministic_and_proportional() -> None:
    keys = [f"{i:09d}" for i in range(4000)]
    first = [company_split(k, seed=7, tuning_share=0.2) for k in keys]
    assert first == [company_split(k, seed=7, tuning_share=0.2) for k in keys]
    share = first.count("tuning") / len(keys)
    assert 0.17 < share < 0.23
    other_seed = [company_split(k, seed=8, tuning_share=0.2) for k in keys]
    assert other_seed != first
