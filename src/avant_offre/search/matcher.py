"""Live matching: rank open tenders against a company profile, with explanations.

Same building blocks as the backtest (``search.bm25``, ``search.dense``, ``search.hybrid``,
``search.rerank``) and the configuration chosen from ``reports/matching.md``
(``search.retrievers``, ``search.profile_strategy``, ``search.rerank``). Each match carries the
three past contracts that explain it best (ids + text), so a bid manager can check why it is
there.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import duckdb
import numpy as np

from avant_offre.search import hybrid
from avant_offre.search.bm25 import Bm25Index
from avant_offre.search.dense import Embedder, default_embedder, embed_tenders, similarity
from avant_offre.search.profile import Profile
from avant_offre.search.rerank import PairScorer, default_scorer, rerank
from avant_offre.settings import Retriever, get_models, get_settings
from avant_offre.store.vectors import VectorStore


@dataclass
class Explanation:
    uid: str | None
    objet: str
    notified_on: date | None
    similarity: float


@dataclass
class Match:
    notice_id: str
    rank: int
    score: float
    fit_percentile: float
    explanations: list[Explanation] = field(default_factory=list)


@dataclass
class MatchOptions:
    retrievers: list[Retriever]
    strategy: hybrid.Strategy
    rerank: bool
    model: str

    @classmethod
    def from_settings(cls) -> MatchOptions:
        s = get_settings().search
        return cls(
            list(s.retrievers), s.profile_strategy, s.rerank, get_models().embeddings.default
        )


def _tender_texts(
    conn: duckdb.DuckDBPyConnection, notice_ids: list[str]
) -> tuple[list[str], list[str]]:
    rows = conn.execute(
        "SELECT notice_id, coalesce(objet, '') FROM tenders "
        "WHERE notice_id IN (SELECT unnest(?)) ORDER BY notice_id",
        [notice_ids],
    ).fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]


def _percentiles(n: int) -> np.ndarray:
    """Rank-based percentile of each position among the batch (best = 1.0)."""
    if n <= 1:
        return np.ones(n)
    return 1.0 - np.arange(n) / (n - 1)


def match_tenders(
    conn: duckdb.DuckDBPyConnection,
    profile: Profile,
    notice_ids: list[str],
    *,
    options: MatchOptions | None = None,
    embedder_factory: Callable[[str], Embedder] = default_embedder,
    scorer_factory: Callable[[], PairScorer] = default_scorer,
    store: VectorStore | None = None,
) -> list[Match]:
    """Rank ``notice_ids`` (already filtered by step 5) for ``profile``."""
    opts = options or MatchOptions.from_settings()
    ids, texts = _tender_texts(conn, notice_ids)
    if not ids or profile.empty:
        return []
    queries = profile.queries
    matrices: dict[str, np.ndarray] = {}
    rankings: list[np.ndarray] = []
    if "bm25" in opts.retrievers:
        b = get_settings().search.bm25
        index = Bm25Index.build(ids, texts, k1=b.k1, b=b.b)
        m = index.score_matrix(queries)
        matrices["bm25"] = m / m.max() if m.size and m.max() > 0 else m
        rankings.append(hybrid.order(hybrid.aggregate(m, opts.strategy)))
    if "dense" in opts.retrievers:
        store = store or VectorStore()
        embedder = embedder_factory(opts.model)
        embed_tenders(conn, embedder, store)
        docs = store.get("tenders", opts.model, ids)
        if profile.uids:
            qv = store.get("awards", opts.model, profile.uids)
        else:
            qv = embedder.encode(queries)
        m = similarity(qv, docs)
        matrices["dense"] = m
        rankings.append(hybrid.order(hybrid.aggregate(m, opts.strategy)))
    if not rankings:
        raise ValueError("search.retrievers must contain bm25 and/or dense")
    if len(rankings) == 1:
        order = rankings[0]
        base = matrices.get("dense", matrices.get("bm25"))
        assert base is not None
        scores = hybrid.aggregate(base, opts.strategy)[order]
    else:
        order, scores = hybrid.rrf(rankings, get_settings().search.rrf_k)
    explain_m = matrices.get("dense", matrices.get("bm25"))
    assert explain_m is not None
    if opts.rerank:
        top_n = get_settings().search.rerank_top_n
        head = order[:top_n]
        order = rerank(
            order,
            explain_m[:, head],
            profile_texts=queries,
            candidate_texts=texts,
            scorer=scorer_factory(),
            top_n=top_n,
        )
        scores = _percentiles(len(order))  # reranked: the score is rank-based
    pct = _percentiles(len(order))
    out = []
    for rank, (doc, score) in enumerate(
        zip(order.tolist(), np.asarray(scores).tolist(), strict=True)
    ):
        expl = [
            Explanation(
                uid=profile.uids[r] if profile.uids else None,
                objet=queries[r],
                notified_on=profile.dates[r] if profile.dates else None,
                similarity=round(sim, 4),
            )
            for r, sim in hybrid.explain(explain_m, doc, top=3)
        ]
        out.append(Match(ids[doc], rank + 1, float(score), float(pct[rank]), expl))
    return out
