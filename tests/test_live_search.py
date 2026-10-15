"""Step 5 filters, live matching with explanations, comparables search."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from avant_offre.ingest import boamp
from avant_offre.intel.comparables import ComparablesIndex
from avant_offre.search import filters, matcher, profile
from avant_offre.search.dense import embed_awards
from avant_offre.store.vectors import VectorStore
from tests.fakes import HashingEmbedder, OverlapScorer
from tests.helpers import build_store

TODAY = date(2026, 10, 15)


def _tender(nid: str, objet: str, deadline: date | None, dept: str = "75") -> dict[str, object]:
    return {
        "idweb": nid,
        "objet": objet,
        "nomacheteur": "VILLE DE TESTVILLE",
        "dateparution": "2026-10-01",
        "datelimitereponse": deadline.isoformat() if deadline else None,
        "code_departement": [dept],
        "procedure_libelle": "Procédure ouverte",
        "donnees": "{}",
    }


@pytest.fixture
def store(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> duckdb.DuckDBPyConnection:
    build_store(conn, tmp_path)
    recs = [
        _tender(
            "T1", "Tierce maintenance applicative du logiciel de gestion", TODAY + timedelta(40)
        ),
        _tender("T2", "Nettoyage des locaux administratifs", TODAY + timedelta(30)),
        _tender("T3", "Travaux de voirie", TODAY + timedelta(5)),  # too close
        _tender("T4", "Développement d'une application web", None),  # no deadline
        _tender(
            "T5", "Migration du système d'information vers le cloud", TODAY + timedelta(60), "13"
        ),
    ]
    p = tmp_path / "boamp.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    boamp.build_tenders(conn, [p])
    return conn


def test_every_exclusion_has_a_reason(store: duckdb.DuckDBPyConnection) -> None:
    rules = filters.FilterRules(min_days_to_deadline=15, allowed_departments=["75"])
    res = {e.notice_id: e for e in filters.eligibility(store, TODAY, rules)}
    assert res["T1"].eligible and res["T2"].eligible
    assert res["T3"].reasons == ["deadline_too_close"]
    assert res["T4"].reasons == ["deadline_missing"]
    assert res["T5"].reasons == ["department_excluded"]
    assert all(e.labels for e in res.values() if not e.eligible)


def test_bm25_matching_ranks_it_tenders_first_for_an_it_company(
    store: duckdb.DuckDBPyConnection,
) -> None:
    key = store.execute(
        "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert key is not None
    prof = profile.from_company(store, key[0], TODAY)
    opts = matcher.MatchOptions(["bm25"], "max", False, "test/hashing")
    out = matcher.match_tenders(store, prof, ["T1", "T2", "T5"], options=opts)
    assert [m.rank for m in out] == [1, 2, 3]
    assert out[-1].notice_id == "T2"  # cleaning is last for an IT company
    assert out[0].explanations and out[0].explanations[0].uid in prof.uids
    assert out[0].fit_percentile == 1.0 and out[-1].fit_percentile == 0.0


def test_hybrid_rerank_matching_with_test_doubles(
    store: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    vs = VectorStore(tmp_path / "v")
    emb = HashingEmbedder()
    embed_awards(store, emb, vs)
    prof = profile.from_free_text("maintenance du logiciel et support applicatif", TODAY)
    opts = matcher.MatchOptions(["bm25", "dense"], "max", True, emb.model_name)
    out = matcher.match_tenders(
        store,
        prof,
        ["T1", "T2", "T5"],
        options=opts,
        embedder_factory=lambda m: HashingEmbedder(model_name=m),
        scorer_factory=OverlapScorer,
        store=vs,
    )
    assert out[0].notice_id == "T1"
    assert out[0].explanations[0].uid is None  # free-text profile has no past contract


def test_comparables_are_strictly_before_reference_date(store: duckdb.DuckDBPyConnection) -> None:
    ref = date(2024, 6, 1)
    idx = ComparablesIndex(store, before=date(2025, 1, 1), use_dense=False)
    comps = idx.search("Nettoyage des locaux administratifs", ref, k=20)
    assert comps
    assert all(c.notified_on < ref for c in comps)
    assert comps[0].similarity == 1.0
    assert all(0 <= c.similarity <= 1 for c in comps)
    only75 = idx.search("Nettoyage des locaux administratifs", ref, k=20, depts=["75"])
    assert only75 and all(c.exec_dept == "75" for c in only75)
