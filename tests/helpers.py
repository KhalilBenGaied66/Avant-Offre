"""Build a fixture store (fictitious data) through the production pipeline functions."""

from __future__ import annotations

from pathlib import Path

import duckdb

from avant_offre.ingest import sirene
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
