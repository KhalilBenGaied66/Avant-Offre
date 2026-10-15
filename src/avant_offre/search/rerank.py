"""Cross-encoder reranker on the top N fused candidates.

A cross-encoder reads (past win, candidate) pairs jointly. To bound the cost, each of the top
``search.rerank_top_n`` candidates is paired only with the 3 past wins that explain it best
(from the first-stage similarity matrix); its reranked score is the max over those pairs.
The reranker is kept only if the backtest shows a gain worth its latency (DECISIONS step 6).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from avant_offre.search.dense import SemanticUnavailableError
from avant_offre.settings import get_models


class PairScorer(Protocol):
    def score(self, pairs: Sequence[tuple[str, str]]) -> np.ndarray: ...


@dataclass
class CrossEncoderScorer:
    model_name: str
    _model: Any = None

    def score(self, pairs: Sequence[tuple[str, str]]) -> np.ndarray:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - optional extra
                raise SemanticUnavailableError(
                    "the reranker needs the model runtime: `uv sync --extra semantic`"
                ) from exc
            self._model = CrossEncoder(self.model_name, device="cpu")
        if not pairs:
            return np.zeros(0, dtype=np.float32)
        return np.asarray(self._model.predict(list(pairs), show_progress_bar=False), np.float32)


def default_scorer() -> CrossEncoderScorer:
    return CrossEncoderScorer(get_models().reranker)


def rerank(
    candidates: np.ndarray,
    first_stage: np.ndarray,
    *,
    profile_texts: Sequence[str],
    candidate_texts: Sequence[str | None],
    scorer: PairScorer,
    top_n: int,
    per_candidate: int = 3,
) -> np.ndarray:
    """Reorder the first ``top_n`` of ``candidates`` (corpus indices, best first).

    ``first_stage`` is the (n_profile_texts, n_candidates) similarity matrix aligned with
    ``candidates``; ``candidate_texts`` is indexed by corpus index.
    """
    head = candidates[:top_n]
    if head.size == 0 or not profile_texts:
        return candidates
    pairs: list[tuple[str, str]] = []
    owners: list[int] = []
    for j, cand in enumerate(head.tolist()):
        col = first_stage[:, j]
        best_rows = np.argsort(-col, kind="stable")[:per_candidate]
        for r in best_rows.tolist():
            pairs.append((profile_texts[r], candidate_texts[cand] or ""))
            owners.append(j)
    scores = scorer.score(pairs)
    best = np.full(head.size, -np.inf, dtype=np.float32)
    for j, s in zip(owners, scores.tolist(), strict=True):
        best[j] = max(best[j], s)
    new_head = head[np.lexsort((np.arange(head.size), -best))]
    return np.concatenate([new_head, candidates[top_n:]])
