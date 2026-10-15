"""Matching backtest harness on the fixture store (fictitious data; numbers not reported)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pytest

from avant_offre.eval import backtest_matching as bm
from avant_offre.eval.splits import window
from avant_offre.settings import get_settings, reset_caches
from tests.helpers import build_store


@pytest.fixture
def ctx(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> bm.Context:
    monkeypatch.setenv("AVANT_OFFRE_EVAL__MIN_WINS_BEFORE_T0", "3")
    monkeypatch.setenv("AVANT_OFFRE_EVAL__BOOTSTRAP_RESAMPLES", "50")
    reset_caches()
    build_store(conn, tmp_path)
    w = window()
    return bm.Context(conn, bm.load_corpus(conn, w.t0, w.t1))


def test_cpv_alert_only_returns_matching_groups(ctx: bm.Context) -> None:
    w = window()
    cases = bm.build_cases(ctx, w.t0, w.t1)
    rank = bm.make_ranker(ctx, "cpv_alert")
    digits = get_settings().search.cpv_group_digits
    for case in cases:
        ranked = rank(case)
        groups = {c[:digits] for c in case.profile.cpvs}
        assert all((ctx.corpus.cpvs[i] or "")[:digits] in groups for i in ranked)
        days = ctx.corpus.days[ranked]
        assert np.all(days[:-1] >= days[1:])  # newest first


def test_rankers_rank_within_pool(ctx: bm.Context) -> None:
    w = window()
    cases = bm.build_cases(ctx, w.t0, w.t1)
    for name in ("bm25:max", "bm25:mean"):
        rank = bm.make_ranker(ctx, name)
        for case in cases:
            ranked = rank(case)
            assert set(ranked.tolist()) == set(case.pool.tolist())


def test_unknown_method_is_rejected(ctx: bm.Context) -> None:
    with pytest.raises(KeyError):
        bm.make_ranker(ctx, "magic")


def test_run_writes_report_and_records_run(ctx: bm.Context) -> None:
    out = bm.run_baselines(ctx.conn)
    report = Path(out["report"])
    text = report.read_text(encoding="utf-8")
    assert "Choices made on the tuning split" in text
    assert "lower bound" in text  # caveat present
    assert report.with_suffix(".json").exists()
    assert ctx.conn.execute("SELECT count(*) FROM eval_runs").fetchone() == (1,)


def test_stratified_sample_is_proportional() -> None:
    rows = [(f"c{i}", 5, 1, "72" if i < 80 else "45", "PME") for i in range(100)]
    picked = bm.stratified_sample(rows, 10, seed=1)
    assert len(picked) == 10
    assert sum(1 for r in picked if r[3] == "72") == 8
