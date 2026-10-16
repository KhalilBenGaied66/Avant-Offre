"""Dense, hybrid and reranker paths with test doubles; vector store; embedding bench harness."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import duckdb
import numpy as np
import pytest

from avant_offre.eval import backtest_matching as bm
from avant_offre.eval import embed_bench
from avant_offre.eval.splits import window
from avant_offre.search import hybrid
from avant_offre.search.rerank import rerank
from avant_offre.settings import reset_caches
from avant_offre.store.vectors import VectorStore
from tests.fakes import HashingEmbedder, OverlapScorer
from tests.helpers import build_store


@pytest.fixture
def ctx(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> bm.Context:
    monkeypatch.setenv("AVANT_OFFRE_EVAL__MIN_WINS_BEFORE_T0", "3")
    monkeypatch.setenv("AVANT_OFFRE_EVAL__BOOTSTRAP_RESAMPLES", "50")
    monkeypatch.setenv("AVANT_OFFRE_EVAL__TUNING_SHARE", "0.5")
    reset_caches()
    build_store(conn, tmp_path)
    w = window()
    return bm.Context(
        conn,
        bm.load_corpus(conn, w.t0, w.t1),
        embedder_factory=lambda m: HashingEmbedder(model_name=m),
        scorer_factory=OverlapScorer,
        store=VectorStore(tmp_path / "vectors"),
    )


def test_vector_store_roundtrip_and_prefilter(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "v")
    vecs = np.eye(3, dtype=np.float32)
    store.upsert("awards", "m/x", ["a", "b", "c"], [10, 20, 30], vecs)
    assert np.allclose(store.get("awards", "m/x", ["c", "a"]), vecs[[2, 0]])
    store.upsert("awards", "m/x", ["a"], [10], np.array([[0, 1, 0]], dtype=np.float32))
    assert np.allclose(store.get("awards", "m/x", ["a"]), [[0, 1, 0]])
    hits = store.search("awards", "m/x", np.array([0, 1, 0], np.float32), k=5, before_day=20)
    assert [h[0] for h in hits] == ["a"]  # b (day 20) is excluded by the prefilter
    with pytest.raises(KeyError):
        store.get("awards", "m/x", ["zzz"])


def test_rrf_fuses_rankings() -> None:
    ids, scores = hybrid.rrf([np.array([1, 2, 3]), np.array([3, 1, 2])], k=60)
    assert ids.tolist()[0] == 1  # ranks 1 and 2 beat ranks 3 and 1
    assert scores[0] == pytest.approx(1 / 61 + 1 / 62)


def test_aggregate_strategies() -> None:
    m = np.array([[0.9, 0.1], [0.0, 0.6]])
    assert hybrid.aggregate(m, "max").tolist() == [0.9, 0.6]
    assert hybrid.aggregate(m, "mean").tolist() == pytest.approx([0.45, 0.35])
    assert hybrid.explain(m, 1, top=1) == [(1, pytest.approx(0.6))]


def test_rerank_reorders_only_the_head() -> None:
    cands = np.array([10, 11, 12, 13])
    first = np.ones((1, 2), dtype=np.float32)
    texts = {10: "voirie", 11: "nettoyage des locaux", 12: "x", 13: "y"}
    out = rerank(
        cands,
        first,
        profile_texts=["nettoyage locaux"],
        candidate_texts=[texts.get(i) for i in range(14)],
        scorer=OverlapScorer(),
        top_n=2,
    )
    assert out.tolist() == [11, 10, 12, 13]


def test_full_matching_run_with_test_doubles(ctx: bm.Context) -> None:
    out = bm.run_full(ctx.conn, ctx=ctx)
    text = Path(out["report"]).read_text(encoding="utf-8")
    assert "hybrid:" in text and "hybrid_rerank:" in text
    assert "Decision rules applied" in text
    assert set(out["chosen"]) >= {"bm25", "dense", "cpv_alert"}
    assert all(v >= 0 for v in out["ms_per_company"].values())


def test_embed_bench_harness(ctx: bm.Context) -> None:
    out = embed_bench.run(
        ctx.conn,
        models=["test/hashing-a", "test/hashing-b"],
        embedder_factory=lambda m: HashingEmbedder(
            model_name=m, dim=32 if m.endswith("a") else 128
        ),
        store=ctx.store,
    )
    text = Path(out["report"]).read_text(encoding="utf-8")
    assert "Selection rule" in text and "s / 1,000 texts" in text


def test_vectors_embed_only_what_a_run_reads(ctx: bm.Context) -> None:
    """A benchmark of several models must not embed every award with each of them."""
    encoded: list[str] = []

    class Counting(HashingEmbedder):
        def encode(self, texts: Sequence[str], kind: str = "query") -> np.ndarray:
            encoded.extend(texts)
            return super().encode(texts, kind)

    ctx.cache["embedder:test/counting"] = Counting(model_name="test/counting")
    ids = ctx.corpus.ids
    assert ctx.vectors("test/counting", ids[:5]).shape[0] == 5 and len(encoded) == 5
    ctx.vectors("test/counting", ids[:7])
    assert len(encoded) == 7  # only the two new awards were embedded

    # An award without objet has nothing to embed: zero vector, aligned with the request.
    ctx.conn.execute("UPDATE awards SET objet = NULL WHERE uid = ?", [ids[10]])
    v = ctx.vectors("test/counting", [ids[10], ids[0]])
    assert v.shape[0] == 2 and not v[0].any() and v[1].any()
