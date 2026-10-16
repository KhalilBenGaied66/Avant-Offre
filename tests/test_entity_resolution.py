"""Step 3 — entity resolution."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from avant_offre.transform import entity_resolution as er
from avant_offre.transform import normalize
from tests.fixtures import luhn_complete, make_siret


def test_luhn_and_siret_rules() -> None:
    siret = make_siret(42)
    assert er.siret_valid(siret)
    assert not er.siret_valid(siret[:-1] + str((int(siret[-1]) + 1) % 10))
    assert er.siren_valid(siret[:9])
    # La Poste: SIREN 356000000, digit sum multiple of 5 instead of Luhn.
    assert er.siret_valid("35600000000001")
    assert not er.siret_valid("35600000000002")
    assert not er.siret_valid("1234")


def test_vat_fr_carries_siren() -> None:
    siren = luhn_complete("12345678")
    assert er.siren_from_vat(f"FR12{siren}") == siren
    assert er.siren_from_vat("DE123456789") is None


def test_normalize_name_drops_legal_forms_and_accents() -> None:
    assert er.normalize_name("Société Générale de Nettoyage SAS") == "generale de nettoyage"
    assert er.normalize_name("ÉTS DUPONT & FILS, S.A.R.L.") == "ets dupont fils"


def test_link_by_identifier_order() -> None:
    siret = make_siret(7)
    exact = er.link_by_identifier(er.WinnerRef(siret, "SIRET", "X", "75"))
    assert exact is not None and exact.method == "exact" and exact.siren == siret[:9]
    siren_only = er.link_by_identifier(er.WinnerRef(siret[:9], "SIRET", "X", "75"))
    assert siren_only is not None and siren_only.method == "siren"
    broken = siret[:-1] + str((int(siret[-1]) + 1) % 10)
    assert er.link_by_identifier(er.WinnerRef(broken, "SIRET", "X", "75")) is None
    known = er.link_by_identifier(er.WinnerRef(broken, "SIRET", "X", "75"), {siret[:9]: {"75"}})
    assert known is not None and known.method == "siren" and known.confidence < 1


def test_siren_link_establishment_tie_goes_to_the_smallest_siret() -> None:
    """Two known establishments with one win each: the pick must not follow input order."""
    siren = make_siret(9)[:9]
    a, b = (luhn_complete(siren + suffix) for suffix in ("0002", "0001"))
    broken = a[:-1] + str((int(a[-1]) + 1) % 10)
    picks = set()
    for order in ((a, b), (b, a)):
        links = {
            er.WinnerRef(s, "SIRET", "X", "75"): er.Link("exact", 1.0, siren=siren, siret=s)
            for s in order
        }
        ref = er.WinnerRef(broken, "SIRET", "X", "75")
        er._siren_links([ref], links)
        picks.add(links[ref].siret)
    assert picks == {min(a, b)}


def _add_winner(conn: duckdb.DuckDBPyConnection, uid: str, wid: str | None, name: str) -> None:
    conn.execute(
        """
        INSERT INTO award_winners (uid, winner_id_raw, winner_id, winner_id_type, winner_name_raw,
            winner_size, winner_naf, winner_dept, winner_siret, winner_siren, company_key,
            link_method, link_confidence, link_flagged)
        VALUES (?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, 'none', NULL, false)
        """,
        [uid, wid, wid or "", name],
    )


def test_resolve_fuzzy_and_never_overwrite_exact(
    conn: duckdb.DuckDBPyConnection, decp_parquet: Path
) -> None:
    normalize.build(conn, decp_parquet)
    uid_alpha_dept = conn.execute(
        "SELECT a.uid FROM awards a JOIN award_winners w USING (uid) "
        "WHERE w.winner_name_raw = 'ALPHA INFORMATIQUE' AND a.exec_dept = '75' LIMIT 1"
    ).fetchone()
    assert uid_alpha_dept is not None
    _add_winner(conn, uid_alpha_dept[0], None, "Alpha Informatique SAS")
    counts = er.resolve(conn)
    assert counts.get("fuzzy", 0) >= 1
    row = conn.execute(
        "SELECT link_method, company_key FROM award_winners "
        "WHERE winner_name_raw = 'Alpha Informatique SAS'"
    ).fetchone()
    exact_key = conn.execute(
        "SELECT DISTINCT company_key FROM award_winners "
        "WHERE winner_name_raw = 'ALPHA INFORMATIQUE'"
    ).fetchone()
    assert row is not None and exact_key is not None
    assert row[0] == "fuzzy" and row[1] == exact_key[0]
    # Every valid SIRET stays an exact link.
    assert conn.execute(
        "SELECT count(*) FROM award_winners WHERE winner_id_type = 'SIRET' "
        "AND link_method <> 'exact'"
    ).fetchone() == (0,)


def test_embedding_fallback_is_flagged(conn: duckdb.DuckDBPyConnection, decp_parquet: Path) -> None:
    normalize.build(conn, decp_parquet)
    uid = conn.execute(
        "SELECT a.uid FROM awards a JOIN award_winners w USING (uid) "
        "WHERE w.winner_name_raw = 'GAMMA BTP' AND a.exec_dept = '13' LIMIT 1"
    ).fetchone()
    assert uid is not None
    _add_winner(conn, uid[0], None, "Entreprise Generale Gama Batiment")

    def embedder(texts: list[str]) -> np.ndarray:  # test double: every text maps to one vector
        v = np.ones((len(texts), 4))
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    er.resolve(conn, embedder=embedder)
    row = conn.execute(
        "SELECT link_method, link_flagged FROM award_winners "
        "WHERE winner_name_raw = 'Entreprise Generale Gama Batiment'"
    ).fetchone()
    assert row == ("embedding", True)
