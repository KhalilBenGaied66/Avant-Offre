"""Personal data rule (SPEC §4.6)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from avant_offre.ingest import sirene
from avant_offre.pipeline import safe_name_lookup
from avant_offre.transform import companies, entity_resolution, first_win, normalize
from avant_offre.transform.privacy import (
    NON_DIFFUSIBLE_MARK,
    PUBLIC_KEY_SQL,
    display_name,
    hash6,
    is_natural_person,
    public_key,
)
from tests.fixtures import SIRENE_FIXTURE
from tests.helpers import build_store


def test_sole_trader_is_pseudonymized() -> None:
    assert is_natural_person("1000", "CAMILLE EXEMPLE") is True
    shown = display_name("CAMILLE EXEMPLE", "123456789", True)
    assert shown == f"Entreprise individuelle #{hash6('123456789')}"
    assert "CAMILLE" not in shown


def test_legal_person_keeps_name() -> None:
    assert is_natural_person("5710", "ALPHA INFORMATIQUE") is False
    assert display_name("ALPHA INFORMATIQUE", "k", False) == "ALPHA INFORMATIQUE"


def test_unknown_status_fails_closed() -> None:
    assert is_natural_person(None, "OMEGA SERVICES") is None
    shown = display_name("OMEGA SERVICES", "k", None)
    assert "OMEGA" not in shown
    assert shown.startswith("Titulaire non vérifié #")


def test_legal_form_in_name_is_evidence_of_legal_person() -> None:
    assert is_natural_person(None, "Zeta GmbH") is False
    assert is_natural_person(None, "Dupont SARL") is False


def test_publisher_masked_names_are_personal() -> None:
    assert is_natural_person(None, NON_DIFFUSIBLE_MARK) is True


def test_hash_is_stable() -> None:
    assert hash6("12345678900011") == hash6("12345678900011")
    assert len(hash6("x")) == 6


def test_company_names_table_never_holds_sole_trader_names(
    conn: duckdb.DuckDBPyConnection, decp_parquet: Path
) -> None:
    normalize.build(conn, decp_parquet)
    entity_resolution.resolve(conn)
    sirene.write_records(
        conn,
        {
            k: sirene.SireneRecord(siren=k, legal_category=v["nature_juridique"])
            for k, v in SIRENE_FIXTURE.items()
        },
    )
    companies.build_companies(conn)
    first_win.build(conn, decp_parquet)
    companies.build_company_names(conn)
    names = [r[0] for r in conn.execute("SELECT display_name FROM company_names").fetchall()]
    assert not any("CAMILLE" in n for n in names)
    assert any(n.startswith("Entreprise individuelle #") for n in names)
    assert any(n.startswith("Titulaire non vérifié #") for n in names)  # OMEGA, no id
    assert "ALPHA INFORMATIQUE" in names


def test_review_sample_hides_sole_trader_siren(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    build_store(conn, tmp_path)
    out = tmp_path / "er_sample.csv"
    entity_resolution.write_review_sample(conn, out, safe_name_lookup(conn))
    text = out.read_text(encoding="utf-8")
    assert "CAMILLE" not in text
    sole = [k for k, v in SIRENE_FIXTURE.items() if v["nature_juridique"] == "1000"]
    assert sole and all(k not in text for k in sole)
    assert "Entreprise individuelle #" in text  # the sole trader is in the sample, masked


def test_public_key_sql_matches_python(conn: duckdb.DuckDBPyConnection) -> None:
    for natural in (True, False, None):
        sql = PUBLIC_KEY_SQL.format(key="?", natural="?")
        got = conn.execute(f"SELECT {sql}", [natural, "123456789", "123456789"]).fetchone()
        assert got == (public_key("123456789", natural),)
    assert public_key("123456789", True).startswith("anon-")
    assert public_key("123456789", False) == "123456789"
