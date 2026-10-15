"""SPEC §7.1: no artifact used in evaluation contains a record dated on or after T0."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from avant_offre.eval import backtest_matching as bm
from avant_offre.eval.splits import LeakageError, assert_before, window
from avant_offre.search.profile import from_company
from avant_offre.settings import reset_caches
from tests.helpers import build_store


@pytest.fixture
def store(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> duckdb.DuckDBPyConnection:
    build_store(conn, tmp_path)
    return conn


def _max_date(conn: duckdb.DuckDBPyConnection, uids: list[str]) -> date | None:
    row = conn.execute(
        "SELECT max(notified_on) FROM awards WHERE uid IN (SELECT unnest(?))", [uids]
    ).fetchone()
    return row[0] if row else None


def test_profiles_use_only_pre_cutoff_awards(store: duckdb.DuckDBPyConnection) -> None:
    t0 = window().t0
    keys = [
        r[0]
        for r in store.execute(
            "SELECT DISTINCT company_key FROM award_winners WHERE company_key IS NOT NULL"
        ).fetchall()
    ]
    assert keys
    for key in keys:
        p = from_company(store, key, t0)
        if p.uids:
            latest = _max_date(store, p.uids)
            assert latest is not None and latest < t0


def test_backtest_cases_have_leak_free_profiles(
    store: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AVANT_OFFRE_EVAL__MIN_WINS_BEFORE_T0", "3")
    reset_caches()
    w = window()
    ctx = bm.Context(store, bm.load_corpus(store, w.t0, w.t1))
    cases = bm.build_cases(ctx, w.t0, w.t1)
    assert cases
    for case in cases:
        latest = _max_date(store, case.profile.uids)
        assert latest is not None and latest < w.t0
    # Candidates are exactly the test window.
    row = store.execute(
        "SELECT min(notified_on), max(notified_on) FROM awards WHERE uid IN (SELECT unnest(?))",
        [ctx.corpus.ids],
    ).fetchone()
    assert row is not None and row[0] >= w.t0 and row[1] < w.t1


def test_guard_raises_on_leak(store: duckdb.DuckDBPyConnection) -> None:
    t0 = window().t0
    late = store.execute("SELECT uid FROM awards WHERE notified_on >= ? LIMIT 1", [t0]).fetchone()
    assert late is not None
    with pytest.raises(LeakageError):
        assert_before(store, [late[0]], t0, "test artifact")
