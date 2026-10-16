"""Service engine end to end, competitor/price backtests and summary (fictitious fixtures)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest

from avant_offre.eval import backtest_competitors, backtest_prices, brief_faithfulness, report
from avant_offre.llm import gateway
from avant_offre.service import Engine, week_bounds
from avant_offre.settings import reset_caches
from avant_offre.store import db
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
    app = duckdb.connect(":memory:")
    engine = Engine(store, TODAY, app_conn=app)
    alpha = store.execute(
        "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert alpha is not None
    b, facts = engine.brief("T1", engine.profile(siret=alpha[0]))
    assert b.fallback and "## Recommandation" in b.text and facts.band in b.text
    assert app.execute("SELECT count(*) FROM briefs WHERE fallback").fetchone() == (1,)


def test_brief_cache_reuses_model_briefs_only(
    store: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = duckdb.connect(":memory:")
    engine = Engine(store, TODAY, app_conn=app)
    alpha = store.execute(
        "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert alpha is not None
    prof = engine.profile(siret=alpha[0])
    calls: list[str] = []

    def answering(task: str, messages: list[dict[str, str]], model: str | None = None) -> Any:
        calls.append(task)
        text = (
            "## Recommandation\nGO sans réserve."  # fails the verifier: template, but a model ran
        )
        return gateway.LLMResult(text, "openai/test", 100, 20, 5.0, 0.0, "stop", "h")

    def down(task: str, messages: list[dict[str, str]], model: str | None = None) -> Any:
        calls.append(task)
        raise gateway.LLMUnavailableError("server down")

    # No model answered: the brief is stored but not reused, the next request tries again.
    monkeypatch.setattr(gateway, "complete", down)
    engine.brief("T1", prof)
    engine.brief("T1", prof)
    assert len(calls) == 2

    # A model answered: the same facts return the stored brief without a second call.
    monkeypatch.setattr(gateway, "complete", answering)
    first, _ = engine.brief("T1", prof)
    second, _ = engine.brief("T1", prof)
    assert len(calls) == 3
    assert second.brief_id == first.brief_id and second.text == first.text
    assert second.removed == first.removed and second.model == "openai/test"


def test_app_tables_gain_new_columns_in_place() -> None:
    app = duckdb.connect(":memory:")
    app.execute("CREATE TABLE briefs (brief_id VARCHAR PRIMARY KEY, notice_id VARCHAR)")
    db.ensure_app_tables(app)
    cols = {r[0] for r in app.execute("DESCRIBE briefs").fetchall()}
    assert {"cache_key", "removed", "latency_ms"} <= cols


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


def test_brief_eval_reports_held_out_notices_and_fallback_reasons(
    store: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer_model = gateway.get_models().tasks["brief_writer"].model
    monkeypatch.setattr(
        gateway,
        "unavailable_reason",
        lambda task, model=None: None if model == writer_model else "no key",
    )

    def short(task: str, messages: list[dict[str, str]], model: str | None = None) -> Any:
        return gateway.LLMResult(
            "## Recommandation\nGO.", writer_model, 50, 5, 1.0, 0.0, "stop", "h"
        )

    monkeypatch.setattr(gateway, "complete", short)
    monkeypatch.setenv("AVANT_OFFRE_EVAL__BRIEF_DEV_NOTICES", '["T1"]')
    reset_caches()
    out = brief_faithfulness.run(store, today=TODAY)
    text = Path(out["report"]).read_text(encoding="utf-8")
    assert "held out" in text and "missing sections" in text
    stats = out["models"][writer_model]
    assert stats["held_out"]["n"] == stats["all"]["n"] - 1
    assert stats["all"]["fallback"] == 1.0


def test_brief_eval_breaks_removed_sentences_down_by_reason(
    store: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer_model = gateway.get_models().tasks["brief_writer"].model
    monkeypatch.setattr(
        gateway,
        "unavailable_reason",
        lambda task, model=None: None if model == writer_model else "no key",
    )

    def sloppy(task: str, messages: list[dict[str, str]], model: str | None = None) -> Any:
        band = json.loads(messages[1]["content"])["recommandation_de_la_grille"]
        text = (
            f"## Recommandation\n{band}.\n## Pourquoi\n- Il reste 999 jours.\n"
            "## Concurrence\n- Trois rivaux [F99].\n## Prix\n- Voir le marché.\n"
            "## Points à vérifier\n- Lire le règlement."
        )
        return gateway.LLMResult(text, writer_model, 50, 5, 1.0, 0.0, "stop", "h")

    monkeypatch.setattr(gateway, "complete", sloppy)
    reset_caches()
    out = brief_faithfulness.run(store, today=TODAY)
    text = Path(out["report"]).read_text(encoding="utf-8")
    assert "number without citation" in text
    assert "cites a fact id that does not exist" in text
    stats = out["models"][writer_model]
    assert stats["all"]["removed"] == 2.0 and stats["all"]["fallback"] == 0.0
    assert all(
        r["removed_kinds"]
        == {"number without citation": 1, "cites a fact id that does not exist": 1}
        for r in stats["notices"]
    )
    samples = (Path(out["report"]).parent / "brief_samples.md").read_text(encoding="utf-8")
    assert "Removed by the verifier" in samples and "Il reste 999 jours." in samples


def test_summary_lists_unrun_backtests(store: duckdb.DuckDBPyConnection) -> None:
    text = report.run().read_text(encoding="utf-8")
    assert "Not run" in text or "not run" in text
    assert "No user testing" in text
