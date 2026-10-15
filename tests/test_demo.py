"""Pseudonymized demo snapshot round trip (fictitious fixture store)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from avant_offre import demo
from avant_offre.service import Engine
from tests.helpers import add_tenders, build_store


def test_snapshot_round_trip_without_personal_names(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    build_store(conn, tmp_path)
    add_tenders(conn, tmp_path, date(2026, 10, 15))
    alpha = conn.execute(
        "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert alpha is not None
    counts = demo.export(conn, tmp_path / "snap", [alpha[0]])
    assert counts["awards"] > 0 and counts["tenders"] == 4
    for f in (tmp_path / "snap").iterdir():
        assert b"CAMILLE" not in f.read_bytes(), f.name  # sole trader never exported
    winners = tmp_path / "snap" / "award_winners.parquet"
    sirets = duckdb.sql(f"SELECT count(winner_siret) FROM read_parquet('{winners}')").fetchone()
    assert sirets == (0,)

    fresh = duckdb.connect(":memory:")
    demo.load(tmp_path / "snap", fresh)
    engine = Engine(fresh, date(2026, 10, 15))
    sl = engine.shortlist(engine.profile(siret=alpha[0]))
    assert sl.eligible and sl.excluded
