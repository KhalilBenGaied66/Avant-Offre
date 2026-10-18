"""Comparable past awards for a tender via step-6 search, dated before the reference date.

The search index only contains awards notified before ``before`` (live: every past award;
backtests: awards before t0), so corpus statistics (IDF) cannot leak the future either. Results
are then restricted to awards dated strictly before the reference date.

``similarity`` is in [0, 1]: the cosine similarity when dense retrieval is configured, else the
BM25 score divided by the best score of the query. It weights competitor evidence (step 7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from avant_offre.search import hybrid
from avant_offre.search.bm25 import Bm25Index
from avant_offre.search.dense import Embedder, default_embedder
from avant_offre.settings import get_models, get_settings
from avant_offre.store.vectors import VectorStore, to_day

FIELDS = (
    "uid, notified_on, buyer_siret, buyer_name, objet, cpv, exec_dept, amount_eur, "
    "is_framework, amount_anomaly, bids_received, is_dynamic_system"
)


@dataclass(frozen=True)
class Comparable:
    uid: str
    similarity: float
    notified_on: date
    buyer_siret: str | None
    buyer_name: str | None
    objet: str | None
    cpv: str | None
    exec_dept: str | None
    amount_eur: float | None
    is_framework: bool
    amount_anomaly: str | None
    bids_received: int | None
    is_dynamic_system: bool = False


class ComparablesIndex:
    """BM25 (and optionally dense) search over awards notified before ``before``."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        before: date | None = None,
        *,
        bm25: Bm25Index | None = None,
        use_dense: bool | None = None,
        embedder_factory: Callable[[str], Embedder] = default_embedder,
        store: VectorStore | None = None,
    ) -> None:
        self.conn = conn
        self.before = before
        self._where = "objet IS NOT NULL AND notified_on IS NOT NULL" + (
            " AND notified_on < ?" if before else ""
        )
        self._params: list[Any] = [before] if before else []
        self._by_uid: dict[str, tuple[Any, ...]] | None = None
        rows = conn.execute(
            f"SELECT uid, objet, notified_on FROM awards WHERE {self._where} ORDER BY uid",  # noqa: S608
            self._params,
        ).fetchall()
        self.ids = [r[0] for r in rows]
        self.days = np.array([to_day(r[2]) for r in rows], dtype=np.int64)
        b = get_settings().search.bm25
        self.bm25 = bm25 or Bm25Index.build(self.ids, [r[1] for r in rows], k1=b.k1, b=b.b)
        if self.bm25.ids != self.ids:
            raise ValueError("loaded BM25 index does not match the awards table: re-run `index`")
        retrievers = get_settings().search.retrievers
        self.use_dense = ("dense" in retrievers) if use_dense is None else use_dense
        self.model = get_models().embeddings.default
        self.embedder_factory = embedder_factory
        self.store = store

    def search(
        self,
        text: str,
        ref_date: date,
        k: int | None = None,
        depts: list[str] | None = None,
    ) -> list[Comparable]:
        k = k or get_settings().intel.k_comparables
        cutoff = to_day(ref_date)
        bm = self.bm25.scores(text)
        bm[self.days >= cutoff] = 0.0
        sims: dict[int, float] = {}
        rankings: list[np.ndarray] = []
        cand = np.flatnonzero(bm > 0)
        cand = cand[np.lexsort((cand, -bm[cand]))][: k * 5]
        rankings.append(cand)
        top = float(bm[cand[0]]) if cand.size else 0.0
        for i in cand.tolist():
            sims[i] = float(bm[i]) / top if top > 0 else 0.0
        if self.use_dense:
            store = self.store or VectorStore()
            vec = self.embedder_factory(self.model).encode([text])[0]
            hits = store.search("awards", self.model, vec, k * 5, before_day=cutoff)
            pos = {u: i for i, u in enumerate(self.ids)}
            dense_ids = np.array([pos[u] for u, _ in hits if u in pos], dtype=np.int64)
            rankings.append(dense_ids)
            for u, s in hits:
                if u in pos:
                    sims[pos[u]] = max(0.0, s)  # cosine wins over BM25 when both exist
        if len(rankings) > 1:
            fused, _ = hybrid.rrf(rankings, get_settings().search.rrf_k)
        else:
            fused = rankings[0]
        uids = [self.ids[i] for i in fused.tolist()]
        sim_by_uid = {self.ids[i]: sims.get(i, 0.0) for i in fused.tolist()}
        return self._load(uids, sim_by_uid, ref_date, k, depts)

    def _load(
        self,
        uids: list[str],
        sims: dict[str, float],
        ref_date: date,
        k: int,
        depts: list[str] | None,
    ) -> list[Comparable]:
        if not uids:
            return []
        by_uid = self._rows()
        wanted = None if depts is None else set(depts)
        out: list[Comparable] = []
        for u in uids:
            r = by_uid.get(u)
            if r is None or not r[1] < ref_date or (wanted is not None and r[6] not in wanted):
                continue
            out.append(
                Comparable(
                    uid=r[0],
                    similarity=round(sims[u], 4),
                    notified_on=r[1],
                    buyer_siret=r[2],
                    buyer_name=r[3],
                    objet=r[4],
                    cpv=r[5],
                    exec_dept=r[6],
                    amount_eur=r[7],
                    is_framework=bool(r[8]),
                    amount_anomaly=r[9],
                    bids_received=r[10],
                    is_dynamic_system=bool(r[11]),
                )
            )
            if len(out) >= k:
                break
        return out

    def _rows(self) -> dict[str, tuple[Any, ...]]:
        """Fields of every indexed award, read once. One query per search made a weekly
        shortlist slow: it searches comparables for every tender of the week."""
        if self._by_uid is None:
            rows = self.conn.execute(
                f"SELECT {FIELDS} FROM awards WHERE {self._where}",  # noqa: S608
                self._params,
            ).fetchall()
            self._by_uid = {r[0]: r for r in rows}
        return self._by_uid


def index_dir() -> Path:
    return get_settings().vectors_dir / "bm25_awards"


def save_awards_index(conn: duckdb.DuckDBPyConnection) -> Path:
    """Persist the live BM25 index (all past awards) so the API does not rebuild it."""
    idx = ComparablesIndex(conn, before=None, use_dense=False)
    path = index_dir()
    idx.bm25.save(path)
    return path


def live_index(conn: duckdb.DuckDBPyConnection) -> ComparablesIndex:
    path = index_dir()
    bm25 = Bm25Index.load(path) if (path / "ids.json").exists() else None
    try:
        return ComparablesIndex(conn, before=None, bm25=bm25)
    except ValueError:
        return ComparablesIndex(conn, before=None)
