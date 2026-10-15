"""Service engine end to end, competitor/price backtests and summary (fictitious fixtures)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from avant_offre.eval import backtest_competitors, backtest_prices, brief_faithfulness, report
from avant_offre.service import Engine, week_bounds
from avant_offre.settings import reset_caches
from tests.helpers import add_tenders, build_store

TODAY = date(2026, 10, 15)


@pytest.fixture
def store(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> duckdb.DuckDBPyConnection:
    monkeypatch.setenv("AVANT_OFFRE_EVAL__BOOTSTRAP_RESAMPLES", "50")
    monkeypatch.setenv("AVANT_OFFRE_INTEL__MIN_PRICE_N", "3")
    reset_caches()
    build_store(conn, tmp_path)
    add_tenders(conn, tmp_path, TODAY)
    return conn


def test_week_bounds() -> None:
    assert week_bounds("2026-W42", TODAY) == (date(2026, 10, 12), date(2026, 10, 19))


def test_shortlist_scores_and_excludes_with_reasons(store: duckdb.DuckDBPyConnection) -> None:
    engine = Engine(store, TODAY)
    alpha = store.execute(
        "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert alpha is not None
    sl = engine.shortlist(engine.profile(siret=alpha[0]))
    assert {i.notice_id for i in sl.eligible} == {"T1", "T2", "T4"}
    assert [e.notice_id for e in sl.excluded] == ["T3"]
    assert sl.excluded[0].reasons == ["deadline_too_close"]
    assert sl.eligible[0].notice_id in {"T1", "T4"}  # IT tenders first for an IT company
    assert all(i.band in {"GO", "REVIEW", "NO-GO"} for i in sl.eligible)


def test_intel_values_carry_n_and_sources(store: duckdb.DuckDBPyConnection) -> None:
    intel = Engine(store, TODAY).intel("T2")
    assert intel.n_comparables > 0
    assert intel.price_range.n == len(intel.price_range.sources)
    assert all(c.sources for c in intel.competitors)
    names = {c.name for c in intel.competitors}
    assert "CAMILLE EXEMPLE" not in names  # sole trader is pseudonymized


def test_brief_without_llm_is_the_verified_template(store: duckdb.DuckDBPyConnection) -> None:
    engine = Engine(store, TODAY)
    alpha = store.execute(
        "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert alpha is not None
    b, facts = engine.brief("T1", engine.profile(siret=alpha[0]))
    assert b.fallback and "## Recommandation" in b.text and facts.band in b.text
    assert store.execute("SELECT count(*) FROM briefs WHERE fallback").fetchone() == (1,)


def test_competitor_and_price_backtests_write_reports(store: duckdb.DuckDBPyConnection) -> None:
    c = backtest_competitors.run(store)
    p = backtest_prices.run(store)
    assert Path(c["report"]).exists() and "all" in c
    assert Path(p["report"]).exists()
    text = Path(c["report"]).read_text(encoding="utf-8")
    assert "first-time winner" in text or "history" in text


def test_brief_eval_refuses_to_report_without_llm(store: duckdb.DuckDBPyConnection) -> None:
    out = brief_faithfulness.run(store, today=TODAY)
    assert "not_run" in out
    assert "No number is reported" in Path(out["report"]).read_text(encoding="utf-8")


def test_summary_lists_unrun_backtests(store: duckdb.DuckDBPyConnection) -> None:
    text = report.run().read_text(encoding="utf-8")
    assert "Not run" in text or "not run" in text
    assert "No user testing" in text
