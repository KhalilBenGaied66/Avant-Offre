"""Pseudonymized demo snapshot round trip (fictitious fixture store)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
from typer.testing import CliRunner

from avant_offre import demo
from avant_offre.cli import app as cli_app
from avant_offre.service import Engine
from avant_offre.settings import get_settings
from avant_offre.store import db
from tests.fixtures import SIRENE_FIXTURE
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
    camille = conn.execute(
        "SELECT company_key FROM company_names WHERE is_natural_person"
    ).fetchone()
    assert camille is not None  # the fixture's sole trader, put in the slice on purpose
    counts = demo.export(conn, tmp_path / "snap", [alpha[0], camille[0]])
    assert counts["awards"] > 0 and counts["tenders"] == 4
    for f in (tmp_path / "snap").iterdir():
        assert b"CAMILLE" not in f.read_bytes(), f.name  # sole trader never exported
    winners = tmp_path / "snap" / "award_winners.parquet"
    sirets = duckdb.sql(f"SELECT count(winner_siret) FROM read_parquet('{winners}')").fetchone()
    assert sirets == (0,)
    # A sole trader's SIREN would find the person in SIRENE: it appears in no exported value.
    sole = [k for k, v in SIRENE_FIXTURE.items() if v["nature_juridique"] == "1000"]
    for f in (tmp_path / "snap").glob("*.parquet"):
        dump = duckdb.sql(f"SELECT * FROM read_parquet('{f}')").fetchall()
        assert not any(k in str(dump) for k in sole), f.name
    names = tmp_path / "snap" / "company_names.parquet"
    anon = duckdb.sql(
        f"SELECT company_key FROM read_parquet('{names}') WHERE is_natural_person"
    ).fetchall()
    assert anon and all(k.startswith("anon-") for (k,) in anon)

    fresh = duckdb.connect(":memory:")
    demo.load(tmp_path / "snap", fresh)
    engine = Engine(fresh, date(2026, 10, 15))
    sl = engine.shortlist(engine.profile(siret=alpha[0]))
    assert sl.eligible and sl.excluded


def test_demo_load_never_replaces_an_existing_store(tmp_path: Path) -> None:
    store = get_settings().db_path
    store.parent.mkdir(parents=True, exist_ok=True)
    duckdb.connect(str(store)).close()
    before = store.stat().st_mtime_ns
    result = CliRunner().invoke(cli_app, ["demo-load", str(tmp_path / "snap")])
    assert result.exit_code != 0 and "already exists" in result.output
    assert store.stat().st_mtime_ns == before


def test_a_loaded_demo_answers_as_of_its_snapshot_date(tmp_path: Path) -> None:
    """Its week of notices and their deadlines must not drift with the clock."""
    conn = duckdb.connect(":memory:")
    build_store(conn, tmp_path)
    add_tenders(conn, tmp_path, date(2026, 10, 15))
    alpha = conn.execute(
        "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert alpha is not None
    snap = tmp_path / "snap"
    demo.export(conn, snap, [alpha[0]])
    info = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
    info["as_of"] = "2026-10-15"
    (snap / "snapshot.json").write_text(json.dumps(info), encoding="utf-8")
    fresh = duckdb.connect(":memory:")
    demo.load(snap, fresh)
    assert db.as_of(fresh) == date(2026, 10, 15)
    sl = Engine(fresh, db.as_of(fresh)).shortlist(Engine(fresh).profile(siret=alpha[0]))
    assert sl.as_of == date(2026, 10, 15) and sl.eligible
    assert db.as_of(duckdb.connect(":memory:")) == date.today()  # a real store: today
