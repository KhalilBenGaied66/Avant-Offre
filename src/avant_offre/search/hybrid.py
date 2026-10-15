"""Profile × candidates scoring, reciprocal rank fusion and match explanations.

Every retriever produces a (n_profile_texts, n_candidates) similarity matrix. Two profile
strategies turn it into one score per candidate (SPEC §6.6):
- ``max``  — max-similarity to any past win;
- ``mean`` — centroid: for cosine similarity, ranking by the mean of the rows is identical to
             ranking by similarity to the (normalized) centroid of the past-win vectors.
Fusion is reciprocal rank fusion: score(d) = Σ_r 1 / (k + rank_r(d)).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np

Strategy = Literal["max", "mean"]


def aggregate(matrix: np.ndarray, strategy: Strategy) -> np.ndarray:
    if matrix.shape[0] == 0:
        return np.zeros(matrix.shape[1], dtype=np.float32)
    if strategy == "max":
        return np.asarray(matrix.max(axis=0))
    return np.asarray(matrix.mean(axis=0))


def order(scores: np.ndarray, tiebreak: np.ndarray | None = None) -> np.ndarray:
    """Indices sorted by score desc; ties by ``tiebreak`` desc (e.g. recency), then index."""
    idx = np.arange(scores.shape[0])
    if tiebreak is None:
        return np.lexsort((idx, -scores))
    return np.lexsort((idx, -tiebreak, -scores))


def rrf(rankings: Sequence[np.ndarray], k: int) -> tuple[np.ndarray, np.ndarray]:
    """Fuse rankings (arrays of item ids, best first). Returns (fused ids, fused scores)."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking.tolist()):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    if not scores:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    items = np.fromiter(scores.keys(), dtype=np.int64)
    vals = np.fromiter(scores.values(), dtype=float)
    o = np.lexsort((items, -vals))
    return items[o], vals[o]


def explain(matrix: np.ndarray, column: int, top: int = 3) -> list[tuple[int, float]]:
    """Top profile rows (past wins) that explain a candidate: [(row, similarity)]."""
    if matrix.shape[0] == 0:
        return []
    col = matrix[:, column]
    rows = np.lexsort((np.arange(col.shape[0]), -col))[:top]
    return [(int(r), float(col[r])) for r in rows if col[r] > 0]


def normalize_scores(scores: np.ndarray) -> np.ndarray:
    """Scale to [0, 1] by the max (BM25 scores are unbounded); zeros stay zero."""
    m = float(scores.max()) if scores.size else 0.0
    return scores / m if m > 0 else scores
