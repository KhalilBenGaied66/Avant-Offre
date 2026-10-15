"""Build a fixture store (fictitious data) through the production pipeline functions."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from avant_offre.ingest import boamp, sirene
from avant_offre.transform import companies, entity_resolution, first_win, normalize
from tests.fixtures import SIRENE_FIXTURE, write_decp_fixture


def build_store(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> Path:
    raw = write_decp_fixture(tmp_path / "decp_store.parquet")
    normalize.build(conn, raw)
    entity_resolution.resolve(conn)
    sirene.write_records(
        conn,
        {
            k: sirene.SireneRecord(siren=k, legal_category=v["nature_juridique"])
            for k, v in SIRENE_FIXTURE.items()
        },
    )
    companies.build_companies(conn)
    first_win.build(conn, raw)
    companies.build_company_names(conn)
    return raw


def add_tenders(conn: duckdb.DuckDBPyConnection, tmp_path: Path, today: date) -> list[str]:
    """Fictitious open BOAMP notices published in the week before ``today``."""

    def rec(nid: str, objet: str, days: int | None, dept: str = "75") -> dict[str, object]:
        return {
            "idweb": nid,
            "objet": objet,
            "nomacheteur": "VILLE DE TESTVILLE",
            "dateparution": (today - timedelta(days=2)).isoformat(),
            "datelimitereponse": None
            if days is None
            else (today + timedelta(days=days)).isoformat(),
            "code_departement": [dept],
            "procedure_libelle": "Procédure ouverte",
            "donnees": json.dumps(
                {
                    "cac:RequestedTenderTotal": {
                        "cbc:EstimatedOverallContractAmount": {
                            "#text": "150000",
                            "@currencyID": "EUR",
                        }
                    }
                }
            ),
        }

    recs = [
        rec("T1", "Tierce maintenance applicative du logiciel de gestion", 40),
        rec("T2", "Nettoyage des locaux administratifs", 30),
        rec("T3", "Travaux de voirie", 5),
        rec("T4", "Migration du système d'information vers le cloud", 60, "13"),
    ]
    p = tmp_path / "boamp_open.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    boamp.build_tenders(conn, [p])
    return [str(r["idweb"]) for r in recs]
